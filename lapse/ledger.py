"""Memory across runs.

A background agent that forgets everything between runs cannot honour its own
promises. Without this, "remind me in three days" is a button that does
nothing, "revisit on" is a field nobody reads, and the same denial letter
arriving twice becomes two separate claims.

The ledger is deliberately a plain JSON file. It holds decisions a human made
and dates a machine computed -- both are small, both benefit from being
readable by the person they concern, and neither needs a database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from lapse.models import Adjudication

DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".lapse_state.json"

UserAction = Literal["none", "dismissed", "snoozed", "acted"]


def clock_identity(adj: Adjudication) -> str:
    """A stable id for a clock, so the same right is never counted twice.

    Keyed on what makes a clock *the same clock* regardless of how it reached
    you: who it is against, what kind of right it is, when the window opened,
    and how long it runs.

    Deliberately NOT keyed on `doc_id` or on the summary text. Both are
    model-generated. Keying on the filename would defeat the exact case this
    is for -- the same denial letter arriving twice, as two files, creating
    two clocks -- and any drift in that generated field would silently forget
    every dismissal the user had made against it.
    """
    f = adj.clock.finding
    raw = "|".join(
        [
            f.counterparty.strip().lower(),
            f.clock_kind.strip().lower(),
            f.trigger_date.strip(),
            str(f.window_days),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class Entry:
    clock_id: str
    doc_id: str
    clock_kind: str
    summary: str
    expiry_date: str
    first_seen: str
    last_seen: str
    times_seen: int = 1
    action: UserAction = "none"
    snoozed_until: str | None = None
    note: str = ""
    dispositions: list[str] = field(default_factory=list)

    def is_muted_on(self, today: str) -> tuple[bool, str]:
        """Should this clock be kept off the user's desk today, and why?"""
        if self.action == "dismissed":
            return True, "you dismissed this"
        if self.action == "acted":
            return True, "you have already acted on this"
        if self.action == "snoozed" and self.snoozed_until:
            if date.fromisoformat(today) < date.fromisoformat(self.snoozed_until):
                return True, f"snoozed until {self.snoozed_until}"
        return False, ""


class Ledger:
    """What Lapse remembers between runs."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_PATH
        self.entries: dict[str, Entry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # A corrupt ledger is a real failure, not an empty one. Starting
            # fresh silently would mean forgetting every dismissal the user
            # ever made and pestering them about all of it again.
            raise LedgerUnreadable(f"Cannot read ledger at {self.path}: {exc}") from exc
        for cid, payload in raw.get("entries", {}).items():
            try:
                self.entries[cid] = Entry(**payload)
            except TypeError as exc:
                # An older or newer ledger schema is an unreadable ledger, not
                # an empty one. Starting fresh here would silently discard
                # every decision the user had made.
                raise LedgerUnreadable(
                    f"Ledger at {self.path} has an incompatible entry {cid!r}: {exc}"
                ) from exc

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {"entries": {cid: asdict(e) for cid, e in self.entries.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )

    def record(self, adj: Adjudication, today: str) -> tuple[Entry, bool]:
        """Record a sighting. Returns the entry and whether it is new."""
        cid = clock_identity(adj)
        disposition = adj.decision.disposition.value if adj.decision else "undecided"
        existing = self.entries.get(cid)
        if existing is None:
            entry = Entry(
                clock_id=cid,
                doc_id=adj.clock.finding.doc_id,
                clock_kind=adj.clock.finding.clock_kind,
                summary=adj.clock.finding.right_summary,
                expiry_date=adj.clock.expiry_date,
                first_seen=today,
                last_seen=today,
                dispositions=[disposition],
            )
            self.entries[cid] = entry
            return entry, True
        existing.last_seen = today
        existing.times_seen += 1
        existing.expiry_date = adj.clock.expiry_date
        existing.dispositions.append(disposition)
        return existing, False

    def act(self, clock_id: str, action: UserAction, until: str | None = None, note: str = "") -> Entry:
        """Record a decision the human made."""
        if clock_id not in self.entries:
            raise KeyError(clock_id)
        entry = self.entries[clock_id]
        if action == "snoozed" and not until:
            raise ValueError(
                "a snooze needs a date; without one it would never mute anything"
            )
        entry.action = action
        # Only a snooze carries a date. Clearing it on every action would drop
        # a live snooze on an unrelated note update.
        if action == "snoozed":
            entry.snoozed_until = until
        elif action in {"dismissed", "acted"}:
            entry.snoozed_until = None
        if note:
            entry.note = note
        return entry


class LedgerUnreadable(RuntimeError):
    """The ledger exists but could not be read. Distinct from 'no ledger yet'."""
