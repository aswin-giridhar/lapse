# Lapse

**An agent for rights that expire while you're not looking.**

Built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) on Amazon Bedrock.
Submitted to the AWS *Agents for Humans* Hackathon — **Everyday Agents** track.

---

## The problem

Think about the mail you got this month.

Some of it was a **bill** — a demand, with a due date, where ignoring it is loud and immediate.
You don't forget bills. Bills chase you.

Some of it was the other kind. A letter saying a claim was processed at a lower rate than you
expected. A recall notice for a car seat. An email from a client saying *"oh, and can we also add
the mobile screens?"* A statement showing a price that has since dropped.

None of those demanded anything. **That's the point.** Each one quietly opened a window during
which you could have done something — and each window closes on its own. When it closes, nothing
happens. No notice, no penalty, no email. The right simply stops existing, and the money stays with
whoever already has it.

This is the asymmetry Lapse exists to correct:

> **The counterparty has software tracking those clocks. You have your memory.**

An insurer knows to the day when your appeal window shuts. A retailer's system knows when price
protection lapses. Your landlord's management company knows what the statutory response deadline
was, and that you didn't act on it. There is no corresponding system on your side, and the default
outcome of that mismatch is that you lose — quietly, repeatedly, in small amounts.

## The number this is built on

| | denied | appealed | overturned |
|---|---|---|---|
| HealthCare.gov marketplace, 2024 | ~85,000,000 claims (19% denial rate) | **262,982 — under 1%** | 34% |
| Medicare Advantage prior auth, 2024 | — | **11.5%** | **80.7%** |

Source: [KFF, 2024](https://www.kff.org/patient-consumer-protections/claims-denials-and-appeals-in-aca-marketplace-plans-in-2024/)
and [KFF prior-authorization metrics](https://www.kff.org/patient-consumer-protections/prior-authorization-metrics-provide-new-insights-into-insurer-practices-but-gaps-remain/).

**Four out of five appealed prior-authorization denials are reversed — and almost nine in ten are
never appealed.** A denial that would be overturned on request stands permanently because nobody
asked.

That gap is not a legal problem and not a merits problem. It is a **noticing** problem, which is
the only kind of problem an agent that reads your documents can actually solve.

## The insight

These look like six unrelated problems living in six different apps. Structurally they are **one
object**:

> a **right** you hold **+** an **expiry** date **+** a **counterparty** who benefits from your silence

| What arrives | The clock it silently starts | Who wins if you forget |
|---|---|---|
| Insurance claim denial | 180-day internal appeal window | Insurer keeps the money |
| Client email expanding scope | SOW objection window before it becomes the baseline | Client gets free work |
| Landlord ignores a repair request | Statutory response clock, then remedies unlock | Landlord |
| Product recall notice | Free-remedy window | Manufacturer |
| Price drop after purchase | Price-protection window | Retailer |
| Grant condition triggered | Reporting cliff | Funder claws back |

So Lapse isn't an insurance app or a contracts app. It's an agent that reads **any** incoming
document and asks one question: *what right did this silently start a clock on, and when does it
expire against me?*

## Who it's for

Anyone who has ever been denied a claim and not appealed it — which is most people. The appeal
success rate is not the reason people don't appeal; the paperwork is. Lapse is aimed at the person
who would act if someone told them, at the right moment, exactly what to do and what the other side
was going to say back.

## What makes it an *agent* rather than a reminder app

Two things.

### 1. It is silent by design

There is no dashboard and no feed to check. On most days Lapse outputs **nothing**. In the demo run
it finds six expiring rights and deliberately surfaces **one** — and shows you why it suppressed
each of the other five, with a *different reason* for each.

### 2. It argues with itself before it bothers you

Before anything reaches you, a **second agent plays the counterparty** — the insurer, the client,
the landlord — and tries to defeat the claim: *"this is excluded as investigational under §7.2"*,
*"the mobile screens were already in scope"*, *"notice by text isn't written notice under the
lease"*.

Only claims that **survive the other side's best argument** reach you, and they arrive with the
rebuttal already drafted.

This is why "only surfaces when there's a real decision to make" is **structural** here rather than
a line in a prompt. A claim that survives an adversary is, by construction, one where a human
decision matters. And the adversary's isolation is enforced in code — a separate `Agent`, a separate
conversation, an opposed objective. Two agents reading the same evidence under the same framing
converge, and their agreement carries no information; asking a single agent to "consider the
opposing view" produces theatre, not an argument.

## What you actually see

```
  lapse  quiet run  2026-09-14

  Clocks found
  right                               counterparty     closes       left    value   disposition
  Appeal the denial of the MRI claim  Keystone Mutual  2026-09-25     11d   $2,340  SURFACED
  Object that mobile screens are …    Meridian Labs    2026-09-22      8d   $3,400  defeated
  Require repair of the water heater  Brightwater      2026-09-16      2d        —  defeated
  Claim the free harness replacement  SafeNest         2026-11-18     65d        —  withheld
  Submit the mail-in rebate           Orchid Home      2026-09-19      5d       $8  withheld
  Claim the post-purchase price drop  Northgate        2026-08-31  14d ago      $47  lapsed
```

…followed by exactly one thing that needs a decision, the counterparty's predicted argument, why it
fails, and a drafted letter that has **not** been sent.

Note what the table proves: the **most urgent** clock (2 days) and the **most valuable** one
($3,400) are both suppressed. Lapse is not sorting by urgency or by value — it is reasoning about
consequence.

## Architecture

Full detail in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

```
   inbox document
        │
        ▼
   ┌─────────────┐   Strands Agent + 6 tools
   │   DETECT    │   which clock did this open? read the governing instrument
   └─────────────┘   → ClockFindings
        │
        ▼
   ┌─────────────┐   ██ PURE PYTHON — no model ██
   │    DATE     │   when does the window actually close?
   └─────────────┘   → DatedClock
        │
        ▼
   ┌─────────────┐   Strands Agent · ISOLATED context · opposed objective
   │  CHALLENGE  │   the counterparty tries to defeat the claim
   └─────────────┘   → Challenge
        │
        ▼
   ┌─────────────┐   Strands Agent
   │   REBUT     │   answer it, or concede — and draft what to send
   └─────────────┘   → Rebuttal
        │
        ▼
   ┌─────────────┐   Strands Agent + ██ deterministic escalation guard ██
   │   TRIAGE    │   spend a strict interruption budget across the whole docket
   └─────────────┘   → SURFACED · DEFEATED · WITHHELD · LAPSED
```

### Design decisions worth defending

**Dates are computed, never generated.** Ask a language model when a 180-day window opened on
2026-03-29 closes and it will answer confidently and wrongly. The model decides *which* clock
applies; `lapse/dates.py` decides *when* it closes. No date that reaches a user was produced by
token generation.

**Typed objects cross every stage boundary.** Strands' `Graph` and `Swarm` primitives flatten
inter-agent hand-offs to text, so Lapse passes `AgentResult.structured_output` directly between
agents instead. Each stage hands the next a validated Pydantic object, so a hand-off cannot quietly
degrade into prose the next stage has to re-parse.

**The clock registry distinguishes statutory from instrument-defined windows.** Where the law fixes
the window (an ERISA appeal is 180 days), the registry is authoritative. Where the *contract* fixes
it, `default_window` is `None` and the agent is required to read the governing document and cite the
clause. Guessing a typical value would be the most dangerous thing this system could do: a
plausible wrong deadline produces calm inaction right up until the right is gone.

**A deterministic guard sits on the join.** Triage is a model deciding what deserves attention. It
does not get to let a valuable right expire this week — any surviving claim above the attention
floor with ≤3 days remaining is escalated by Python, whatever the model concluded.

**It shows its work.** Every run ends with its own trace — how many model
invocations, across how many isolated agents, which tools were called how many
times, and what it cost:

```
6 clocks examined  ·  1 surfaced  ·  0 muted by you  ·  served by bedrock / us.amazon.nova-pro-v1:0
19 model invocations across 19 isolated agents  ·  186,179 in / 9,625 out tokens  ·  $0.180
tools called: list_reference_documents×13, read_reference_document×12,
              compute_window_expiry×10, search_reference_documents×8, list_clock_types×6
```

That 1:1 agent-to-invocation ratio is evidence the isolation above is real, and
the tool counts show the agent actually opens the governing instruments rather
than reasoning from the incoming document alone. A user being asked to trust a
silence should be able to see that the agent looked.

**Documents are examined in parallel.** They are independent, so detection and
the argument stage run in a thread pool: **120s → 66s** over the six-document
corpus. Each stage still constructs a fresh `Agent`, so concurrency does not
weaken the isolation.

**`doctor` makes a real call.** Having credentials is not the same as being able to infer —
Bedrock will hand you a perfectly good client for a model your account cannot serve. `doctor`
therefore issues an actual one-token request, because a probe that cannot fail is not measuring
anything. The default model is Amazon Nova Pro specifically because it needs no per-provider
use-case approval, so a fresh clone works; Anthropic models on Bedrock require an approval step
first.

**The provider fallback is loud.** If Bedrock credentials are absent, Lapse says so on stderr and in
every run footer. An AWS-native system that quietly ran on something else is a system that reports
falsely about itself.

## Running it

```bash
git clone https://github.com/aswin-giridhar/lapse.git
cd lapse
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Point it at Amazon Bedrock (Bedrock console → API keys; enable Anthropic
# model access in the same region first):
export AWS_BEARER_TOKEN_BEDROCK="..."
export AWS_REGION=us-west-2
#   …or just use standard AWS credentials via `aws configure`.

.venv/bin/python -m lapse.cli doctor          # verifies with a REAL inference call
.venv/bin/python -m lapse.cli watch --today 2026-09-14
```

`watch` options:

| flag | meaning |
|---|---|
| `--today ISO` | date to measure clocks against (the demo corpus is built around `2026-09-14`) |
| `--budget N` | how many items triage may surface (default 1) |
| `--attention-floor USD` | below this, a claim generally isn't worth interrupting you (default 100) |
| `--json PATH` | write the full adjudication record, including every argument, to a file |
| `--quiet` | hide the per-stage progress trace |

### Memory between runs

Lapse remembers what it has already raised and what you decided about it:

```bash
.venv/bin/python -m lapse.cli ledger              # what it is carrying
.venv/bin/python -m lapse.cli snooze a1b2c3 --days 3
.venv/bin/python -m lapse.cli dismiss a1b2c3 --note "already handled by phone"
.venv/bin/python -m lapse.cli acted a1b2c3
```

Each clock gets a stable id, shown in the `watch` table. Muting is checked
*before* the argument stages, so a dismissed clock costs no model calls —
re-litigating a dismissal is the fastest way to teach someone to ignore you.

A clock's identity is keyed on the document, the kind of right and the trigger
date, deliberately **not** on the model-written summary. Keying on generated
text would make every run invent new clocks and re-raise everything you had
already dealt with.

Use `--forget` for a clean demonstration run that neither reads nor writes
your real history.

Run the tests — all offline, no model calls:

```bash
.venv/bin/python -m pytest
```

## The demo corpus

`corpus/` holds six incoming documents and four governing instruments. **Every entity in it is
fictional** — no document is attributed to a real company — and the dates are real, so the clock
arithmetic is genuine rather than narrated.

The four reference documents matter as much as the six inbox ones: an incoming document almost
never states the window that governs it. The 180-day appeal period lives in the Certificate of
Coverage, not in the denial letter. The scope-objection window lives in the SOW. The agent has to
go and find them.

## What a run costs, and what it misses

Measured on Amazon Nova Pro, us-west-2, over the six-document corpus. Two
correctly-instrumented runs agreed to within 3%, which is the only reason the
figure is quoted at all — one run gives a value, two tell you whether it means
anything.

| | |
|---|---|
| Per six-document run | **$0.167** (runs measured at $0.170 and $0.164) |
| Per document | **$0.028** |
| A user receiving 30 documents a month | **~$0.84/month** |
| Tokens per run | ~178k in / ~8.5k out, 18 model invocations |

**And the number that matters more.** Six runs of the identical corpus with
detection pinned at `temperature=0.0` found **4, 5, 5, 5, 6 and 6** clocks.
That is a 50% spread on the same input, and temperature 0 does not fix it —
it constrains sampling, not tool-use paths or structured-output retries.

This is the central open problem, and it is worse here than it would be in most
systems: **a missed clock is silent**, and silence is precisely what the user is
being asked to trust. An agent that says nothing because there was nothing to
say and one that says nothing because it failed to look are indistinguishable
from the outside. The first thing an eval harness should measure is detection
recall against a labelled set, not answer quality.

## Honest limitations

These are real, and worth stating plainly rather than discovering in the demo.

- **The clock registry is hand-curated and small.** Appeal windows, statutory repair clocks and
  chargeback deadlines vary by jurisdiction, plan and card network. Ten clock types with
  carefully-scoped authorities is honest as a demonstration; it is not coverage, and the gap between
  this and something you'd trust with a real denial is larger than a demo makes it look.
- **Drafting is where the legal risk lives, not detecting.** *Nippon Life v. OpenAI*
  (N.D. Ill., 2026) pleads unauthorised practice of law against an AI system for
  autonomous document *drafting* — a closer analogue to Lapse's mechanism than the
  DoNotPay action, which was a deception case rather than a UPL one. And with
  *Upsolve v. James* vacated and cert denied in March 2026, the First Amendment
  route is currently closed. The defensible line is to **surface the deadline and
  leave the drafting to the user** in eviction, debt-collection and court-answer
  territory, even though the same pipeline could draft there.
- **A reminder can itself cause the loss.** FCBA, Reg E and several immigration
  deadlines require *arrival* at the counterparty, not sending by you. A system that
  surfaces "3 days left" for an arrival-anchored right is quietly advising someone
  into a missed deadline. Those clocks need a **mail-by** date, and the registry does
  not yet distinguish the two.
- **Never tell someone a claim is dead.** Government-claim notice periods look
  jurisdictional and often are not — *Kwai Fun Wong* holds FTCA deadlines tollable,
  and California has a late-claim rescue chain. A lapsed clock should read as "this
  looks closed, and here is who to ask", never as a closed door.
- **This is not legal advice**, and the tenancy and insurance-appeal paths sit close to it. Lapse is
  built to hand you a deadline and a draft, never to act for you: nothing is ever sent without an
  explicit human approval, by design and not as a limitation.
- **Jurisdiction is not modelled.** `habitability_repair_notice` carries a 14-day default that is
  correct in some states and wrong in others. The registry flags this
  (`jurisdiction_dependent=True`) but does not yet resolve it.
- **The ledger is a local JSON file.** Fine for one person on one machine;
  a real deployment wants durable, encrypted, multi-device storage, and the
  documents it reasons over are among the most sensitive a person has.
- **Document ingestion is a directory read.** Wiring a real mailbox is straightforward and is the
  obvious next step; it is deliberately not in the demo path, because a live connector is a fragile
  dependency in a recorded run.

## Licence

MIT — see [LICENSE](LICENSE).
