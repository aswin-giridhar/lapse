"""Lapse's product surface.

Most of this file exists to render silence well. A run that finds five
expiring rights and decides four of them are not worth your attention has to
make that decision legible, or it is indistinguishable from a system that
simply missed them.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
import sys
from datetime import date as _date

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from datetime import timedelta

from lapse.ledger import Ledger, LedgerUnreadable, clock_identity
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
    table.add_column("id", style="dim")

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
            clock_identity(adj) + (" ·new" if report.is_new(adj) else ""),
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


def _scratch_ledger() -> Ledger:
    """A throwaway ledger for a clean demonstration run.

    Writes to a temp file that is discarded, so `--forget` neither reads the
    user's real history nor pollutes it. Pointing this at the real path with
    saving disabled would be subtler and worse: the run would silently differ
    from what the ledger says happened.
    """
    tmp = Path(tempfile.mkdtemp(prefix="lapse-scratch-")) / "state.json"
    return Ledger(path=tmp)


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
            ledger=_scratch_ledger() if args.forget else None,
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
        + Text(f"{report.muted_count} muted by you  ·  ", style="dim")
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


def cmd_ledger(args: argparse.Namespace) -> int:
    """What Lapse is carrying between runs."""
    try:
        ledger = Ledger()
    except LedgerUnreadable as exc:
        console.print(Panel(Text(str(exc), style="red"), border_style="red"))
        return 2
    if not ledger.entries:
        console.print()
        console.print(Text("  Nothing remembered yet. Run `lapse watch` first.", style="dim"))
        return 0
    table = Table(title="Remembered clocks", title_justify="left", header_style="dim", box=None)
    table.add_column("id", style="dim")
    table.add_column("right", overflow="fold", max_width=42)
    table.add_column("closes", justify="right")
    table.add_column("seen", justify="right")
    table.add_column("you")
    for e in sorted(ledger.entries.values(), key=lambda e: e.expiry_date):
        state = e.action if e.action != "none" else "—"
        if e.action == "snoozed" and e.snoozed_until:
            state = f"snoozed → {e.snoozed_until}"
        table.add_row(e.clock_id, e.summary, e.expiry_date, str(e.times_seen), state)
    console.print()
    console.print(table)
    console.print()
    return 0


def cmd_act(args: argparse.Namespace) -> int:
    """Record a decision, so Lapse stops raising it."""
    try:
        ledger = Ledger()
    except LedgerUnreadable as exc:
        console.print(Panel(Text(str(exc), style="red"), border_style="red"))
        return 2
    until = None
    if args.command == "snooze":
        until = (_date.today() + timedelta(days=args.days)).isoformat()
        action = "snoozed"
    elif args.command == "dismiss":
        action = "dismissed"
    else:
        action = "acted"
    try:
        entry = ledger.act(args.clock_id, action, until=until, note=args.note or "")
    except KeyError:
        console.print()
        console.print(
            Text(f"  No clock with id '{args.clock_id}'. Run `lapse ledger` to list them.", style="red")
        )
        return 2
    ledger.save()
    console.print()
    console.print(Text("  noted  ", style="dim") + Text(entry.summary, style="bold"))
    console.print(
        Text("         ", style="dim")
        + Text(
            f"{action}" + (f" until {until}" if until else "") + " — Lapse will not raise this again"
            + (" before then." if until else "."),
            style="dim",
        )
    )
    console.print()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report exactly which provider would serve a run, and why."""
    console.print()
    try:
        model = build_model()
        info = active_provider()
        console.print(Text("  provider  ", style="dim") + Text(info.name, style="bold green"))
        console.print(Text("  model     ", style="dim") + Text(info.model_id))
        console.print(Text("  detail    ", style="dim") + Text(info.detail, style="dim"))
        if info.name != "bedrock":
            console.print()
            console.print(Text("  This run would NOT use Amazon Bedrock.", style="bold yellow"))

        # Having credentials is not the same as being able to infer. Bedrock
        # will hand you a perfectly good client for a model your account may
        # not serve, so the only honest check is to actually call it.
        from strands import Agent

        try:
            Agent(model=model, callback_handler=None)("Reply with the single word: ready")
        except Exception as exc:  # noqa: BLE001 - reported in full, not swallowed
            console.print()
            console.print(
                Panel(
                    Text(
                        "Credentials resolve, but the model refused a real "
                        f"request:\n\n{type(exc).__name__}: {exc}",
                        style="red",
                    ),
                    title="[red]provider is NOT usable[/red]",
                    border_style="red",
                )
            )
            return 2
        console.print()
        console.print(Text("  inference ", style="dim") + Text("verified with a live call", style="bold green"))
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
    watch.add_argument(
        "--forget",
        action="store_true",
        help="ignore and do not update the ledger (for a clean demonstration run)",
    )
    watch.set_defaults(func=cmd_watch)

    led = sub.add_parser("ledger", help="what Lapse remembers between runs")
    led.set_defaults(func=cmd_ledger)

    for name, helptext in [
        ("dismiss", "stop raising this clock"),
        ("acted", "mark that you have dealt with this clock"),
        ("snooze", "hold this clock back for a number of days"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("clock_id", help="id from the ledger or the watch table")
        sp.add_argument("--note", help="why, for your own records")
        if name == "snooze":
            sp.add_argument("--days", type=int, default=3, help="how long to hold it")
        sp.set_defaults(func=cmd_act)

    doctor = sub.add_parser("doctor", help="show which model provider would serve a run")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
