"""Model provider selection.

Bedrock is the intended home for this agent. The LiteLLM path exists so the
build is not hostage to a credential problem, but it is NEVER selected
silently: an unavailable Bedrock and a working Bedrock must not produce the
same-looking run, or you end up reporting an AWS-native system that never
touched AWS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Amazon's own model, chosen because it needs no per-provider use-case form and
# therefore works on a fresh AWS account. Anthropic models on Bedrock require an
# approval step, so defaulting to one would mean this project does not run for
# someone who just cloned it. Override with LAPSE_BEDROCK_MODEL.
DEFAULT_BEDROCK_MODEL = "us.amazon.nova-pro-v1:0"
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-west-2")


class ProviderUnavailable(RuntimeError):
    """No usable model provider. Raised loudly rather than degrading quietly."""


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    model_id: str
    detail: str


_ACTIVE: ProviderInfo | None = None


def active_provider() -> ProviderInfo | None:
    """What actually served this run. Used in output so provenance is never guessed."""
    return _ACTIVE


def _bedrock_credentials_present() -> tuple[bool, str]:
    if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        return True, "AWS_BEARER_TOKEN_BEDROCK"
    try:
        import boto3

        creds = boto3.Session().get_credentials()
        if creds is not None and creds.access_key:
            return True, "boto3 session credentials"
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return False, f"boto3 lookup failed: {exc}"
    return False, "no AWS credentials found"


def build_model(temperature: float = 0.2):
    """Return a Strands model, preferring Bedrock.

    Selection is controlled by LAPSE_PROVIDER: "bedrock", "litellm", or unset
    for automatic. Automatic mode prefers Bedrock and falls back only when
    AWS credentials are genuinely absent -- and says so on stderr.
    """
    global _ACTIVE
    requested = os.environ.get("LAPSE_PROVIDER", "auto").lower()

    if requested in {"auto", "bedrock"}:
        ok, why = _bedrock_credentials_present()
        if ok:
            from strands.models.bedrock import BedrockModel

            model_id = os.environ.get("LAPSE_BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL)
            kwargs = {
                "model_id": model_id,
                "region_name": DEFAULT_REGION,
                "temperature": temperature,
            }
            if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
                kwargs["api_key"] = os.environ["AWS_BEARER_TOKEN_BEDROCK"]
            _ACTIVE = ProviderInfo("bedrock", model_id, f"{DEFAULT_REGION} via {why}")
            return BedrockModel(**kwargs)
        if requested == "bedrock":
            raise ProviderUnavailable(
                f"LAPSE_PROVIDER=bedrock was requested but {why}. "
                "Set AWS_BEARER_TOKEN_BEDROCK or configure AWS credentials."
            )
        import sys

        print(
            f"[lapse] Bedrock unavailable ({why}); falling back to LiteLLM. "
            "This run is NOT using Amazon Bedrock.",
            file=sys.stderr,
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ProviderUnavailable(
            "No Bedrock credentials and no GEMINI_API_KEY. Set one of:\n"
            "  AWS_BEARER_TOKEN_BEDROCK  (Bedrock console -> API keys)\n"
            "  standard AWS credentials  (aws configure)\n"
            "  GEMINI_API_KEY            (fallback provider)"
        )
    from strands.models.litellm import LiteLLMModel

    model_id = os.environ.get("LAPSE_LITELLM_MODEL", "gemini/gemini-2.5-flash")
    _ACTIVE = ProviderInfo("litellm", model_id, "fallback provider - not Bedrock")
    return LiteLLMModel(
        client_args={"api_key": api_key}, model_id=model_id, params={"temperature": temperature}
    )
