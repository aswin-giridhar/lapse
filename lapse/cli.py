"""Lapse's product surface.

Most of this file exists to render silence well. A run that finds five
expiring rights and decides four of them are not worth your attention has to
make that decision legible, or it is indistinguishable from a system that
simply missed them.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from lapse.models import Adjudication, Disposition
from lapse.providers import ProviderUnavailable, build_model, active_provider
from lapse.run import RunReport, quiet_run

console = Console()

_DISPOSITION_STYLE = {
    Disposition.SURFACED: ("bold white on red", "SURFACED"),
    Disposition.DEFEATED: ("yellow", "defeated"),
    Disposition.WITHHELD: ("dim", "withheld"),
    Disposition.LAPSED: ("red dim", "lapsed"),
}


def _money(value: float | None) -> str:
    return f"${value:,.0f}" if value else "—"


def _progress(stage: str, message: str) -> None:
    prefix = {
        "provider": ("dim", "  model   "),
        "detect": ("cyan", "  read    "),
        "detect.none": ("dim", "  quiet   "),
        "clock": ("bold cyan", "  clock   "),
        "challenge": ("magenta", "  attack  "),
        "challenge.result": ("magenta dim", "          "),
        "rebut": ("green", "  answer  "),
        "rebut.result": ("green dim", "          "),
        "triage": ("bold yellow", "  triage  "),
    }.get(stage, ("dim", "          "))
    console.print(Text(prefix[1], style=prefix[0]) + Text(message, style="default"))


def render_ledger(report: RunReport) -> None:
    """Everything Lapse found, and what it decided about each."""
    table = Table(
        title="Clocks found", title_justify="left", header_style="dim", box=None, pad_edge=False
    )
    table.add_column("right", overflow="fold", max_width=44)
    table.add_column("counterparty", style="dim", max_width=18)
    table.add_column("closes", justify="right")
    table.add_column("left", justify="right")
    table.add_column("value", justify="right")
    table.add_column("disposition")

    order = {
        Disposition.SURFACED: 0,
        Disposition.WITHHELD: 1,
        Disposition.DEFEATED: 2,
        Disposition.LAPSED: 3,
    }
    rows = sorted(
        report.adjudications,
        key=lambda a: order.get(a.decision.disposition if a.decision else None, 9),
    )
    for adj in rows:
        disp = adj.decision.disposition if adj.decision else None
        style, label = _DISPOSITION_STYLE.get(disp, ("dim", "—"))
        left = adj.clock.days_remaining
        table.add_row(
            adj.clock.finding.right_summary,
            adj.clock.finding.counterparty,
            adj.clock.expiry_date,
            f"{left}d" if left >= 0 else f"{abs(left)}d ago",
            _money(adj.clock.finding.value_usd),
            Text(label, style=style),
        )
    console.print(table)


def render_reasoning(report: RunReport) -> None:
    """Why each clock was NOT surfaced. This is the part that earns the silence."""
    suppressed = report.withheld + report.defeated + report.lapsed
    if not suppressed:
        return
    console.print()
    console.print(Rule("[dim]why you are not being told about these[/dim]", style="dim"))
    for adj in suppressed:
        disp = adj.decision.disposition
        style, label = _DISPOSITION_STYLE[disp]
        console.print()
        console.print(Text(f"  {adj.clock.finding.right_summary}", style="bold dim"))
        console.print(Text(f"  {label}  ", style=style), end="")
        console.print(Text(adj.decision.reason, style="dim"))
        if disp is Disposition.DEFEATED and adj.challenge is not None:
            console.print(
                Text(
                    f"    {adj.clock.finding.counterparty} argued: "
                    f"{adj.challenge.argument}",
                    style="yellow dim",
                )
            )
            if adj.challenge.authority:
                console.print(Text(f"    relying on: {adj.challenge.authority}", style="dim"))
        if adj.decision.revisit_on:
            console.print(Text(f"    returning on {adj.decision.revisit_on}", style="dim"))


def render_surfaced(report: RunReport) -> None:
    """The one thing worth interrupting someone for."""
    if not report.surfaced:
        console.print()
        console.print(
            Panel(
                Text(
                    "Nothing needs you today.",
                    style="bold green",
                    justify="center",
                ),
                border_style="green",
                padding=(1, 2),
            )
        )
        return

    for adj in report.surfaced:
        f = adj.clock.finding
        body = Text()
        body.append(f"{f.right_summary}\n\n", style="bold white")
        body.append("closes      ", style="dim")
        body.append(f"{adj.clock.expiry_date}  ", style="bold")
        body.append(f"({adj.clock.days_remaining} days)\n", style="bold red")
        body.append("worth       ", style="dim")
        body.append(f"{_money(f.value_usd)}", style="bold")
        body.append(f"  {f.value_basis}\n", style="dim")
        body.append("authority   ", style="dim")
        body.append(f"{f.authority}\n", style="default")

        if adj.challenge is not None:
            body.append("\n")
            body.append(f"{f.counterparty} will argue\n", style="bold yellow")
            body.append(f"{adj.challenge.argument}\n", style="yellow")
            if adj.challenge.authority:
                body.append(f"relying on {adj.challenge.authority}\n", style="dim yellow")

        if adj.rebuttal is not None:
            body.append("\n")
            body.append("why that fails\n", style="bold green")
            body.append(f"{adj.rebuttal.answer}\n", style="green")
            if adj.rebuttal.authority:
                body.append(f"on the strength of {adj.rebuttal.authority}\n", style="dim green")

        console.print()
        console.print(
            Panel(
                body,
                title="[bold white on red] NEEDS YOU [/bold white on red]",
                border_style="red",
                padding=(1, 2),
            )
        )

        if adj.rebuttal is not None and adj.rebuttal.drafted_action:
            console.print()
            console.print(
                Panel(
                    Text(adj.rebuttal.drafted_action.strip(), style="default"),
                    title="[dim]drafted for you — nothing has been sent[/dim]",
                    border_style="dim",
                    padding=(1, 2),
                )
            )
        console.print()
        console.print(
            Text("    [ Send ]", style="bold white on red")
            + Text("   [ Edit ]   [ Dismiss ]   [ Remind me in 3 days ]", style="dim")
        )


def cmd_watch(args: argparse.Namespace) -> int:
    today = args.today or _date.today().isoformat()
    console.print()
    console.print(
        Text("lapse", style="bold") + Text("  quiet run  ", style="dim") + Text(today, style="dim")
    )
    console.print()
    try:
        report = quiet_run(
            today=today,
            budget=args.budget,
            attention_floor_usd=args.attention_floor,
            on_event=None if args.quiet else _progress,
        )
    except ProviderUnavailable as exc:
        console.print(Panel(Text(str(exc), style="red"), title="no model provider", border_style="red"))
        return 2

    console.print()
    console.print(Rule(style="dim"))
    render_ledger(report)
    render_reasoning(report)
    console.print()
    console.print(Rule(style="dim"))
    render_surfaced(report)
    console.print()
    console.print(
        Text(f"  {len(report.adjudications)} clocks examined  ·  ", style="dim")
        + Text(f"{len(report.surfaced)} surfaced  ·  ", style="dim")
        + Text(f"served by {report.provider}", style="dim")
    )
    console.print()

    if args.json:
        payload = {
            "today": report.today,
            "provider": report.provider,
            "adjudications": [json.loads(a.model_dump_json()) for a in report.adjudications],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        console.print(Text(f"  full record written to {args.json}", style="dim"))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report exactly which provider would serve a run, and why."""
    console.print()
    try:
        build_model()
        info = active_provider()
        console.print(Text("  provider  ", style="dim") + Text(info.name, style="bold green"))
        console.print(Text("  model     ", style="dim") + Text(info.model_id))
        console.print(Text("  detail    ", style="dim") + Text(info.detail, style="dim"))
        if info.name != "bedrock":
            console.print()
            console.print(
                Text("  This run would NOT use Amazon Bedrock.", style="bold yellow")
            )
        return 0
    except ProviderUnavailable as exc:
        console.print(Panel(Text(str(exc), style="red"), border_style="red"))
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lapse", description="Find rights that expire while you are not looking."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="run the pipeline over the inbox")
    watch.add_argument("--today", help="ISO date to measure against (default: system date)")
    watch.add_argument("--budget", type=int, default=1, help="max items triage may surface")
    watch.add_argument(
        "--attention-floor", type=float, default=100.0, help="value below which not to interrupt"
    )
    watch.add_argument("--quiet", action="store_true", help="hide per-stage progress")
    watch.add_argument("--json", help="write the full adjudication record to this path")
    watch.set_defaults(func=cmd_watch)

    doctor = sub.add_parser("doctor", help="show which model provider would serve a run")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
