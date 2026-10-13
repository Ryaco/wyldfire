# Wyldfire — UX Spec & Command Reference

> Working spec for the Wyldfire CLI. Opinionated FSM for solo / small-team indie game
> developers, based on Benjamin Kean Anderson's *Production Point: How to Plan
> and Finish Your Game as a Solo Developer* (2023).

## 1. Concept

Wyldfire enforces Anderson's discipline as a finite state machine. A project lives in
exactly one phase at a time:

```
prototype ──► gate ──► production
```

You cannot wander into production. You earn it through the gate. The app is
deliberately opinionated: it nags, blocks, and requires evidence before letting
you advance.

No AI anywhere in the app. This is a deliberate scope decision.

## 2. Terminology (fire theme)

| Term   | Meaning |
|--------|---------|
| `wyld` | The CLI root command |
| flame  | A prototype — a juice-less mechanical proof of concept. Can be paper with real-life playtesting. |
| spark  | Verb: create a flame |
| stoke  | Verb: playtest a flame (you stoke a flame to see how it burns) |
| smoke  | An issue / bug. First-class entity, decoupled from flames — usable in prototype, gate, and production. |
| ember  | A parked idea. Wild ideas that belong to production (themes, level sets, content) get banked here instead of acted on during prototype. |
| fire   | A named collection of flames — like a spec list. A flame can belong to multiple fires. Different fires answer different fun questions. |
| wick | An ordered burn-down list of content for a fire — worked one bundle at a time, depth-first. Like a real wick, it delivers the fuel to the fire little by little. |
| lap | A re-gate: a fire that already passed the gate going back through Part 1 (e.g. to adopt a new flame). Numbered and recorded. |
| bundle | A scope unit in a wick (e.g. "area 1"). Holds either sub-bundles or fuel. |
| fuel   | An atomic piece of content to make. Burning fuel is doing the work. A "define" fuel is a deferred design decision. |
| metric | A dev-defined measurement (e.g. enjoyment 1–10), asked the same way every stoke |

## 3. FSM — phases live on fires

Phases live on **fires**, not on the project. The project is a container; each
fire moves independently through:

```
prototype ──► gate ──► production
```

- **prototype** — spark as many flames as you want. Iterate versions, stoke
  them (and the fire), log smoke. The production wick and content
  generation are locked — when a production-sized idea strikes, bank it as an
  ember instead of chasing it.
- **gate** — the bridge. A checklist of requirements must be satisfied before
  the gate opens for a fire. (Criteria TBD — see §9.)
- **production** — a fire in production is a **production stream**. Scope is
  locked per stream; the app gets strict about new mechanics and open smoke.

Multiple fires can be in production at once: `tcg-core` can ship as a
standalone card game (stream 1) while `full-game` is still in prototype.

*Attention discipline:* the data model is multi-stream, but the UX is
single-stream. Commands operate on one fire at a time (`--fire <name>` or a
current-fire context), so you're never ambiguously "in" two phases at once —
the maker's/manager's schedule protection survives multi-stream.

*Two layers:* flame operations (`wyld flame spark`, `version`, `stoke`) are
global and multi-stream — they take no fire context. Creative work stays free:
checked out on `full-game`, you can still spark and stoke a TCG flame without
switching. Fire operations (`gate`, production commands) are scoped to the
checked-out fire. Maker mode is multi-stream; manager mode is single-stream.

## 4. Flame lifecycle (proposed)

```
sparked ──► burning ──► tested ──► stoked (chosen for the gate)
                                  └──► doused (killed, kept as a lesson)
```

- **sparked** — just created, no stoke yet
- **burning** — actively iterated (v1, v2, v3…)
- **tested** — at least one stoke logged
- **stoked / doused** — terminal states: chosen or killed

## 5. Command reference

### `wyld flame` — prototypes

```bash
# Create a flame
wyld flame spark "wildfire" --desc "Top-down wildfire containment: cut firebreaks while wind spreads the fire"

# List / inspect flames
wyld flame list
wyld flame show wildfire

# Record a new iteration of a flame
wyld flame version wildfire --notes "wind die dealt every 2 turns instead of every turn"

# Playtest a flame (a "stoke") — who played, what they said, optional metrics
wyld flame stoke "wildfire" --tester "Jo" --notes "tension is great, turns drag at 4 players"
# Long session notes? Take them from a file (like git commit -F):
wyld flame stoke "wildfire" --tester "Jo" --notes-file session.md
# Ask a defined metric the same way every time:
wyld flame stoke "wildfire" --tester "Jo" --metric enjoyment=8 --notes "much better pacing"
# A stoke is a commit: it also files any smoke staged on this flame.
# A stoke needs at least one of: notes, metric values, staged smoke.

# Testers carry free-form notes — the dev knows their testing base's quirks
wyld tester note "A" --note "not into card games generally, take scores with salt"

# Terminal states
wyld flame stoke-flame wildfire    # mark as chosen (proposed name — TBD)
wyld flame douse wildfire --note "core loop never sang after 5 stokes"
```

### `wyld smoke` — issues, decoupled from flames

Smoke is its own top-level group. Each smoke is anchored to a context
(`--on flame/<name>`, `--on gate`, `--on production`).

```bash
# Log smoke — status: open. Note describes what's happening.
wyld smoke log "wind die feels unfair at 4 players" \
  --on flame/wildfire --severity 2 --tags "balance"

# ...or stage it during a playtest — a stoke commits it, git-style.
# Staging is for bugs found mid-playtest; the stoke files them.
wyld smoke stage "wind die feels unfair at 4 players" --on flame/wildfire --severity 2
wyld smoke stage "firebreak tiles read as walls" --on flame/wildfire --severity 1 --tags "ux"
# → staged, not yet open. Then commit the playtest:
wyld flame stoke wildfire --tester Jo --notes-file session.md
# → stoke recorded; 2 staged smoke opened and linked to this stoke.
# A flame stoke commits smoke staged on that flame; a fire stoke commits
# smoke staged on that fire. `wyld smoke log` still opens immediately —
# use it for bugs found outside playtests.

# Identify — status: identified. Note describes what the problem is.
wyld smoke identify 3 --note "spread rate scales with map size, not player count"

# Clear — status: cleared. Note describes what the fix was.
wyld smoke clear 3 --note "spread rate now scales with player count"

# Tag at any point (open or later); tags emerge organically, no suggestions
wyld smoke tag 3 --tags "balance,spread-rate"

# List / filter
wyld smoke list --on flame/wildfire
wyld smoke list --on flame/wildfire --status open
```

### Smoke lifecycle

```
staged ──► open ──► identified ──► cleared
```

Every transition **requires a note**:

- **staged** — found during a playtest, not yet filed (the symptom, as a title)
- **open** — what's happening (the symptom)
- **identified** — what the problem is (the diagnosis)
- **cleared** — what the fix was (the resolution)

Staged smoke is pre-open: invisible to gate/ship smoke checks until a stoke
commits it. `wyld smoke staged` lists the staging area; `wyld smoke unstage
<id>` discards a staged entry; `wyld doctor` flags staged smoke left sitting
uncommitted.

This turns the tracker into a learning database: every cleared smoke is a
problem + fix pair your future self can search.

### `wyld smoke search` — the learning database

```bash
# Search cleared smoke by tag in the current project first.
# If nothing is found locally, the search auto-widens to all local projects.
wyld smoke search --tags "balance" --status cleared

# Force all local projects
wyld smoke search --tags "balance" --status cleared --all
```

Behavior:

1. Search current project first.
2. If no results, print `nothing in this project — widening to all local projects…`
   and search everything local.
3. `--all` skips straight to all local projects.

Results show the problem note and the fix note, so a past fix is directly reusable.

### `wyld ember` — parked ideas

Banking coals is real fire-tending: you bank embers to keep them alive until you
need them. Same here — an ember is an idea you're not allowed to act on yet.

```bash
# Bank an ember — park a production-sized idea during prototype
wyld ember bank "neon-noir city theme for the level set" \
  --note "struck me mid-stoke: rain-slick streets would sell the fire contrast"

# List banked embers
wyld ember list

# Kindle an ember — pull it into active use (gate or production)
wyld ember kindle 2 --note "approved at gate: becomes level set 2 theme"
```

Embers are reviewed at the gate: each one is either kindled into production
scope or left banked / discarded. This is what keeps prototype phase honest —
the app says "not now, bank it" instead of letting scope creep in through the
back door.

*Rationale:* this is maker's schedule vs. manager's schedule. Mid-prototype,
the dev is in deep maker mode on mechanics. A lore/art/content idea demands a
switch to manager-mode thinking (planning, organizing), and that switch leaves
attention residue on the prototype work. Banking the ember — writing the idea
down with a note — is what lets the brain let go and stay in maker mode. The
idea gets its manager-schedule expansion later, at the gate or in production.

### `wyld fire` — collections of flames

A fire is kindled from flames. The metaphor is literal: flames make a fire.
Membership is many-to-many — a flame can burn in more than one fire.

```bash
# Start a fire from flames
wyld fire start "tcg-core" --flames draft,combat,mulligan \
  --desc "the card battle system, standalone"
wyld fire start "full-game" --flames draft,combat,overworld,quests \
  --desc "the RPG with its card battle system"

wyld fire list                     # like `git branch` — fires with their phases
wyld fire checkout tcg-core       # like `git checkout` — work on one fire at a time
wyld fire show tcg-core
wyld fire add-flames full-game --flames crafting

# Stoke a fire — playtest the composition, not just the components.
# Flame stokes answer "is this mechanic fun?"; fire stokes answer
# "does the composition work?"
wyld fire stoke "tcg-core" --tester "Jo" \
  --notes "draft is the fun part; combat resolves a touch slow"
# Like flame stokes: --notes-file and --metric work, and staged smoke on this fire is committed.
```

*Why fires exist:* some games have separable subsystems. An RPG whose battles
are a tower-defense co-op card game asks two different fun questions — "is the
card game fun on its own?" (fire 1: TCG flames only) and "does it work inside
the RPG loop?" (fire 2: TCG flames + everything else). Paper prototyping makes
both cheap to test; fires keep the two questions — and their stoke histories —
separate. Integration problems ("card rewards break RPG economy pacing") are
fire-level smoke: `--on fire/full-game`.

Open: does the gate evaluate a *fire* rather than a single flame? For simple
games the fire holds one flame, so this generalizes cleanly — but unconfirmed.

### `wyld gate` — the three-part process

The gate answers one question, the book's question: *is this the production point?*

```bash
wyld gate status --fire full-game   # show the checks and what's blocking
wyld gate open --fire full-game     # attempt to pass the gate with this fire
```

**Part 1 — the verdict.** The dev runs `wyld gate open` when they feel ready.
Fun is the smallest part of the production point. The checks:

```
$ wyld gate status
Gate checks:
  ✓ Playtested: 4 stokes on current version v4 (1 excluded) — enjoyment trending 6→8
  ✓ Core loop declared: "spot fire → cut firebreaks → starve it → score"
  ✓ Toys declared: cutting firebreaks, wind die
  ✓ Scope: dev attests the fire's composition covers the whole game
  ✗ Open smoke: 1 at severity ≥ 2 (#4 "downtime between turns at 4p")
  ✓ Embers reviewed: 2 kindled, 1 dismissed
```

- The **core loop** (the repeated play cycle, a sentence or two) and the
  **toy(s)** (the playful systems, win-or-lose aside) are declared on the fire
  and **freeze** on pass — they *are* the spec Part 2 builds the vertical
  slice from.
- "Scope feels complete" is a dev attestation: a deliberate judgment call
  signed off on the record, not something the app computes. The fire's flame
  composition is the scope; the dev says it covers the whole game.
- These three are **reflection checks**: the app cannot answer them, only the
  dev can, honestly. What the app *can* do is put the evidence in front of
  them. Declaring the loop/toys or attesting scope pulls up the fire's stoke
  history — scores across versions, tester notes, the dev's own `--notes` —
  so the judgment is made while looking at the data, not from fuzzy memory.
  The app is a mirror here, not a judge: it requires the question be answered
  and records the answer, but the answer belongs to the dev.

```bash
$ wyld fire set-loop "spot fire → cut firebreaks → starve it → score"
# → stoke history for this fire:
#     v1  6.5  "tension is there, but wind every turn feels chaotic" (Jo)
#     v4  8.0  "much better pacing, 4p game finally sings" (Jo)
# → core loop recorded. Freezes on gate pass.
```

- **Pass** — "Production point reached." Core loop, toys, and fire composition
  freeze as the spec; the fire proceeds to Part 2 (vertical slice).
- **Reject** — "The gate holds." The fire returns to prototype **with a
  reason why**: each failing check becomes a structured, actionable reason
  (not just "no"). The verdict and its reasons are recorded; reasons are the
  prototype todo list.

```
$ wyld gate open
# → The gate holds.
#   Reasons:
#   - 1 open smoke at severity ≥ 2 (#4)
#   - scope not attested (attest with `wyld gate attest-scope` — TBD)
# → fire returns to prototype with structured reasons recorded.
```

**Tester-aware evidence.** The gate shows the stoke history — notes and metric
trends — broken down by tester, and the dev — who knows their testing base's
quirks — can exclude a stoke's evidence with a recorded reason. The exclusion
is recorded against the fire, same as a waived check:

```bash
$ wyld gate exclude-stoke 12 --reason "A isn't into this genre (see tester note)"
# → 4 stokes (1 excluded, reason recorded); enjoyment trend 6→8 across the rest
```

**Part 2 — vertical slice.** Spec is frozen from Part 1. Build a small, playable, feature-complete slice of the game — the pitchable demo for grants, crowdfunding, publishers. The gate gets limited access to the production content wick here: just enough content (art, audio, juice) to make the slice sing, without opening full production scope. Requires at least one stoke on the slice to pass to Part 3.

**Part 3 — content plan.** Plan the first iteration of the content list (levels, cards, quests — whatever the fire's content is). Once that list exists, the fire leaves the gate and enters full production.

**Laps — re-gating a passed fire.** A **lap** is a fire that already passed the
gate going back through Part 1 — e.g. a production fire adopting a new flame
(mechanic). Laps are numbered and recorded; the term is never used for initial
gate attempts. Parts 2 and 3 don't re-run on a lap — the slice and plan
already exist.

```bash
# A mechanic ember from production is kindled into a flame, prototyped/stoked…
wyld gate open --fire full-game   # lap 1: Part 1 re-verdict on the new composition
# → pass: spec re-freezes (new pins incl. the new flame), fire returns to production.
#         new content extends the wick under content-addition rules (ETA shown).
# → hold:  fire stays in production unchanged, flame not added, reasons recorded.
```

### `wyld wick` — the content burn-down (proposed)

Part 3's "content list" and production's work loop are the same mechanism: a
**wick**, an ordered burn-down list worked one bundle at a time, per fire.

Deliberate scope cut: wyld does **not** hook into content-creation software
(Aseprite, Blender, DAWs…). That integration surface is impossibly huge.
Wyldfire tracks the work — metadata and tasks — and the actual making happens
wherever the dev makes it.

- A **bundle** is a scope unit (e.g. "area 1"). It holds either sub-bundles or
  **fuel**, not both. Bundles carry free-form **metadata** (theme, enemies,
  palette, references…) — defining a bundle means filling in its metadata
  plus its tasks.
- **Fuel** is an atomic piece of content to make (a sprite, a track, a quest
  script). Fuel lifecycle, solo-dev edition: `creating` → `finished`. (A
  `reviewing` state would suit small teams; out of scope for now.) You *burn*
  fuel by making it — finishing fuel advances the burn-down.
- A **define fuel** is a deferred design decision. Areas 1 and 3 are fully
  specified, but area 2 is just a name with a hole in the middle. Area 2
  carries a define fuel; when the burn-down reaches it, the fuel enters
  `creating` and the app prompts you to define the bundle — metadata plus its
  sub-bundles/fuel. When the design is done, a command marks the define fuel
  `finished` and the burn-down continues. This is how Part 3 plans the first
  iteration without designing everything up front: placeholders are
  first-class, and they force just-in-time design instead of letting holes hide.
- **Time logging.** Fuel accepts logged time; the wick projects a finish
  date from it — useful for release scheduling. (Open: pace-based projection
  from logged time vs. per-fuel estimates.)

```bash
# Part 3: lay out the first-iteration wick for the fire
wyld wick plan --fire full-game

wyld wick bundle add "area 1" --meta theme="ashen city" --meta enemies="cinder imps"
wyld wick fuel add "cinder imp sprite" --to "area 1"
wyld wick fuel add "rain-slick street tileset" --to "area 1"

# Area 2 is a known unknown: a name plus a define fuel
wyld wick bundle add "area 2"
wyld wick fuel define "area 2" --note "bridge between ashen city and the dam"

wyld wick bundle add "area 3" --meta theme="flooded dam" --meta enemies="drowned husks"

# Production: burn it down, one bundle at a time
wyld wick next                        # what am I burning now?
wyld wick start "cinder imp sprite"   # → creating
wyld wick log "cinder imp sprite" --time 2h30m
wyld wick finish "cinder imp sprite"  # → finished, burn-down advances

# → reaching area 2's define fuel: it enters creating, app prompts to define it
wyld wick bundle define "area 2" --meta theme="canyon pass" --meta enemies="dust wyrms"
wyld wick fuel add "dust wyrm sprite" --to "area 2"
wyld wick finish "define: area 2"     # design done — burn-down continues

wyld wick eta                         # projected finish date from logged pace
```

- Gate Part 2 runs a *small* wick (the vertical slice — maybe a single
  bundle) under the gate's limited content access.
- Production runs the full wick. Scope stays locked: new fuel appears only
  by expanding a define fuel, or by explicit scope change (TBD).

**Templates and typed fuel (proposed).** Game content repeats in predictable
ways: an area needs some Xs, Ys, Zs; an X always needs an A, B, and C. So:

- **Fuel types.** Every fuel carries a type tag (`--type sprite`,
  `--type audio`…). Logged time aggregates per type: the average time per
  finished fuel of each type.
- **Bundle templates.** A named, reusable structure: the `area` template is
  "3 X, 4 Y, 2 Z sub-bundles"; the `X` template is "fuels A, B, C". Defining
  a bundle can instantiate a template instead of starting from a blank page —
  which upgrades the define-fuel prompt from "design area 2 now" to
  "instantiate the `area` template and customize?"
- **Projection.** Remaining work = Σ (average time per fuel type × remaining
  fuels of that type). Undefined bundles are estimated from their defined
  siblings: 8 areas with 2 undefined → each undefined area costs the average
  of the 6 defined ones.

```bash
wyld template new "area" --structure "X x3, Y x4, Z x2"
wyld template new "X" --fuels "A:sprite, B:sprite, C:audio"

# Defining area 2? Start from the template, then customize
wyld wick bundle add "area 2" --template area
wyld wick fuel add "dust wyrm roar" --to "area 2" --type audio

wyld wick eta
# → sprite: 14 finished, avg 2.1h × 9 remaining = 18.9h
# → audio:   6 finished, avg 3.2h × 4 remaining = 12.8h
# → areas: 6 defined (avg 42h each), 2 undefined ≈ 84h
# → projected finish: 2027-01-18
```

Templates live at the project level so every fire's wick can reuse them
(proposed).

### `wyld sync` — offline-first hosted sync (v1)

```bash
# Pair this machine with your server (token stored in ~/.config/wyldfire/,
# never in the project)
wyld login --server https://wyld.example.com
# → token stored. Now link this project:
wyld link
# → paired with server project "wildfire-game" (created it)

# Normal use: work offline freely. When you're back online:
wyld sync
# → pushed 14 events, pulled 3 events
# → conflict: flame "draft" description edited on both sides —
#   kept the newer one (desktop, 10:42). Older value in history.
# → orphan: bundle "area 2" was deleted on laptop, but desktop logged 2h
#   on fuel "dust wyrm roar" inside it — preserved, see `wyld doctor`.

# Anything still needing a human:
wyld doctor
# → 1 orphaned fuel, 1 possible duplicate flame name
```

Rules of thumb: the tool always works offline — sync is a separate,
explicit step. The server is the merge point, not the only truth. Conflicts
resolve automatically by a fixed policy (append-only data merges, state
machines go forward, scalar edits keep the newest, deletes are tombstones
that never lose work, stale gate passes are rejected) and every resolution
is printed in the sync report. Nothing is ever silently lost or silently
overwritten.

## 6. Measurements — dev-defined metrics

No built-in fun score. If you want to ask the same question of every tester,
define a metric once and answer it per stoke:

```bash
wyld metric define enjoyment --prompt "How much did you enjoy it? (1-10)" --type number
wyld metric define replay --prompt "Would you play again? (1-10)" --type number

wyld flame stoke wildfire --tester Jo --metric enjoyment=8 --metric replay=7 \
  --notes "tension is great, turns drag at 4 players"
```

- `--type number` aggregates: `wyld metric show enjoyment` trends the values
  across stokes and versions. `--type text` (the default) just displays.
- Metrics are project-level; they work on flame and fire stokes alike.
- The classic two questions (enjoyment, replay desire) work fine as metrics —
  define them if you want them. The app itself never scores fun; it shows
  your measurements back to you.

Every stoke still records **who** played (`--tester`, defaulting to the dev).
Testers carry free-form notes for the dev's knowledge of their testing base
("not into this genre", "only plays co-op"…). The app never auto-weights
anything — it surfaces who said what, and the metric trends, and lets the
dev judge.

Not every stoke needs metrics. A personal playtest where you found a bug is
complete as notes + staged smoke — log the notable ones, skip the fifty
uneventful run-throughs. Stokes are a log of notable playtests, not a
complete record.

## 7. Walkthrough — the wildfire game

> Game: top-down wildfire containment. You play a smoke jumper cutting firebreaks
> while wind spreads fire across a grid. Core mechanic: fire spreads, you cut
> lines to starve it.

```
$ wyld flame spark "wildfire" \
    --desc "Top-down wildfire containment: cut firebreaks while wind spreads the fire"
# → flame "wildfire" sparked (v1)

# v1 is paper: grid paper, red tokens for fire, a die for wind each turn.
# Define the question you'll ask every tester, once:
$ wyld metric define enjoyment --prompt "How much did you enjoy it? (1-10)" --type number
$ wyld flame stoke "wildfire" --tester Jo --metric enjoyment=6 \
    --notes "tension is there, but wind every turn feels chaotic"

$ wyld smoke log "wind die feels unfair at 4 players" \
    --on flame/wildfire --severity 2 --tags "balance"
# → smoke #1 open

$ wyld smoke identify 1 --note "spread rate scales with map size, not player count"
# → smoke #1 identified

$ wyld flame version wildfire --notes "wind die dealt every 2 turns"
# → v2

$ wyld flame stoke "wildfire" --tester Jo --metric enjoyment=8 \
    --notes "much better pacing, 4p game finally sings"

$ wyld smoke clear 1 --note "spread rate now scales with player count; wind every 2 turns"
# → smoke #1 cleared

$ wyld smoke tag 1 --tags "balance,spread-rate,pacing"

# …two projects later, on a new game, similar symptom:
$ wyld smoke search --tags "balance" --status cleared
# → nothing in this project — widening to all local projects…
# → finds wildfire's smoke #1: problem + fix. Past self debugs future self.

# Mid-stoke, a production-sized idea strikes — bank it, don't chase it:
$ wyld ember bank "ashen city level theme: rain-slick streets vs fire glow" \
    --note "struck me during the v2 stoke; would sell the containment fantasy"
# → ember #1 banked. Reviewed at the gate.
```

## 7b. Walkthrough — fires (RPG + card battler)

> Game: an RPG whose battle system is a tower-defense co-op card game. The card
> game might one day become a standalone TCG.

```
$ wyld flame spark "draft" --desc "card draft: pick 1 of 3, deck of 20"
$ wyld flame spark "combat" --desc "co-op tower defense combat with drafted deck"
$ wyld flame spark "overworld" --desc "move on map, encounters trigger battles"
$ wyld flame spark "quests" --desc "quest flags unlock map regions"

# Two fires, one shared subsystem:
$ wyld fire start "tcg-core" --flames draft,combat \
    --desc "is the card game fun on its own?"
$ wyld fire start "full-game" --flames draft,combat,overworld,quests \
    --desc "does the card game work inside the RPG loop?"

# Paper prototype both, stoke each:
$ wyld fire stoke "tcg-core" --tester Jo --metric enjoyment=9 \
    --notes "draft is crack; combat sings at 2p"
# → the card game is real. TCG future stays alive.

$ wyld fire stoke "full-game" --tester Jo --metric enjoyment=6 \
    --notes "battles feel disconnected from overworld; rewards don't matter yet"
# → the composition needs work, even though the parts are fun.

$ wyld smoke log "card rewards don't feed back into overworld" \
    --on fire/full-game --severity 2 --tags "integration,rewards"
# → integration smoke lives at the fire level, not on any single flame.
```

## 8. Storage

Hybrid (decided): an append-only JSONL event log under `.wyld/events/` is the
source of truth; SQLite (`.wyld/wyld.db`) is a disposable projection rebuilt
by replaying the log. `.wyld/` is gitignored wholesale — the game repo carries
no wyldfire data.

v1 also includes hosted sync: wyld is offline-first (every mutation appends
locally, the tool always works), and `wyld sync` pushes/pulls events against
a personal FastAPI server (single API token, `wyld login`). The server is the
merge point. Conflicts resolve by a fixed, deterministic policy — append-only
data merges, state machines move forward only, scalar edits keep the newest,
deletes are tombstones that never lose work, stale gate passes are rejected —
and every resolution is printed in the sync report. `wyld doctor` lists
anything still needing a human.

Stack: Python + Click (CLI), FastAPI (sync server).

## 9. Open questions

1. **Gate criteria** — what exactly must be true to pass? Candidates: minimum fun
   score, minimum number of stokes, zero open smoke above severity X, core loop
   declared, toy(s) declared, scope-complete attestation, embers reviewed.
2. **Gate smoke** — what does `--on gate` smoke look like in practice?
   ("scope not locked, still adding mechanics"?)
3. **Production rules** — how strict? No new mechanics? No shipping with
   severity-3 smoke open?
4. **Flame terminal commands** — names for choose/kill (`stoke-flame`? `crown`?
   `douse` for kill feels right).
5. **Severity scale** — 1–3? 1–5? What blocks the gate?
6. **Stoke attribution** — resolved: named playtesters. Stokes take `--tester`
   (default: the dev); `wyld tester note` stores free-form notes per tester;
   the gate can exclude a stoke's evidence with a recorded reason.
7. **Gate reject path** — resolved: rejection returns the fire to prototype
   with structured reasons (no lap involved). Open: on re-entry, do the checks
   reset or does history accumulate across attempts?
8. **Stoke ↔ version pinning** — a stoke on v1 shouldn't bless v4. Should stokes
   record the version tested, and should the gate require stokes on the *current*
   version?
9. **Project context** — how does `wyld` know which project you're in? Implicit
   cwd, or explicit? Cross-project smoke search implies a project registry
   (e.g. `~/.wyld/`). This decides the SQLite shape: per-project DB + registry
   vs. one global DB.
10. **Production verbs** — proposal: the wick burn-down (`wyld wick plan` /
    `bundle` / `fuel` / `start` / `finish` / `log` / `eta`), one bundle at a time.
    Finish-date projection uses per-fuel-type time averages × remaining fuel,
    with undefined bundles estimated from defined siblings. Open: does finishing
    a fuel require a note (like smoke transitions do)? Can the wick be
    reordered mid-production, or is order locked with the scope? Do templates
    live at project or fire level, and how deep can they nest?
11. **Bidirectional embers** — in production, a shiny new *mechanic* idea is the
    scope creep. Should embers park those too, for "next game"?
12. **Flame comparison** — with several tested flames, how do you pick one?
    `wyld flame list` should probably rank by most recent stoke; the gate could show a
    side-by-side.

## 10. Decisions log

- CLI-first (`wyld`), GUI / web server later. Commands designed to map 1:1 to
  future API endpoints.
- Fire theme throughout: flames, spark, stoke, smoke.
- Playtest term: **stoke**. Issue term: **smoke** (also a real QA term — double meaning).
- Smoke decoupled from flames; usable in every phase.
- Smoke lifecycle open → identified → cleared, notes required at each step.
- Tags organic, no AI suggestions, no AI in the app at all.
- Search: current project first, auto-widen to all local, `--all` flag.
- UX before storage; storage (SQLite) follows the UX.
- **Embers**: production wick and content generation are locked during
  prototype; wild ideas get banked as embers (`wyld ember bank` / `kindle`) and
  reviewed at the gate. Banking coals is real fire-tending — the metaphor holds.
- **Fires**: named collections of flames (many-to-many). Flame stokes answer
  "is this mechanic fun?"; fire stokes answer "does the composition work?"
  Integration smoke lives at fire level (`--on fire/<name>`). Verb: `wyld fire
  start` (avoids clashing with `ember kindle`).
- **Multi-stream production**: phases live on fires, not the project. Each fire
  runs its own prototype → gate → production; a fire in production is a stream.
  Gate commands take `--fire`. UX stays single-fire-focused to protect attention
  discipline (one fire's schedule at a time).
- **Wicks**: Part 3's content list and production's work loop are one
  mechanism — a wick, an ordered burn-down list worked one bundle at a time
  per fire. Bundles hold sub-bundles or fuel (atomic content units) plus
  free-form metadata; you burn fuel to advance. A "define" fuel is a deferred
  design decision: when the burn-down reaches it, it enters `creating` and the
  app prompts you to define that bundle (metadata + tasks) before continuing.
  Fuel lifecycle is `creating` → `finished` (solo-dev scope; `reviewing` later
  for teams). No hooks into content-creation software — impossibly huge scope;
  wyld tracks metadata and tasks only. Time can be logged on fuel and the
  wick projects a finish date for release planning. Gate Part 2 runs a small
  wick for the vertical slice.
- **Templates and typed fuel**: fuels carry type tags so logged time aggregates
  per type; bundle templates capture repeating structure (an `area` is 3 X, 4 Y,
  2 Z sub-bundles; an `X` is fuels A, B, C). Defining a bundle can instantiate
  a template instead of starting blank. Finish-date projection = per-type
  average time × remaining fuel, with undefined bundles estimated from the
  average of their defined siblings.
- **Stoke attribution**: stokes record `--tester` (default: the dev); testers
  carry free-form notes about the dev's knowledge of their testing base. The
  gate shows stoke history (notes, metric trends) broken down by tester; a
  stoke's evidence can be excluded with a recorded reason. The app never
  auto-weights anything.
- **Dev-defined metrics**: no built-in fun score (cut 2026-10-13 — the app is
  a mirror, not a judge). `wyld metric define` registers a question asked the
  same way every stoke (`--type number` trends across versions, `--type text`
  just displays). A stoke needs at least one of: notes, metric values, staged
  smoke. Stokes are a log of *notable* playtests, not a complete record —
  log the ones that matter, skip the fifty uneventful run-throughs.
- **Storage**: hybrid event log (JSONL source of truth) + SQLite disposable
  projection. Decided 2026-10-13 — the sync design needs the event log.
- **Sync**: v1, offline-first, hosted. Personal FastAPI server as the merge
  point; `wyld login` / `link` / `sync` / `doctor`. Fixed collision policy:
  append-only merges, monotonic FSMs go forward, scalar edits keep newest
  (timestamp, client_id), add-vs-remove → remove wins, deletes are
  tombstones (orphans preserved + reported), stale gate passes rejected.
  Every sync prints a report; nothing is silently lost or overwritten.
  `.wyld/` gitignored — wyld is version control for the decision/process
  layer (versions, pins, laps, history); git is version control for the file
  layer. They compose.
- **Stoke as commit**: a stoke is a commit — smoke found during a playtest is
  *staged* (`wyld smoke stage --on flame/<n>`), then opened and linked when
  the stoke runs, git-style. Staging is anchor-scoped: a flame stoke commits
  smoke staged on that flame, a fire stoke on that fire. Stoke notes accept
  `--notes-file` (like `git commit -F`). Staged smoke is pre-open: invisible
  to gate/ship checks until committed; `wyld doctor` flags it if left
  sitting. `wyld smoke log` still opens immediately for non-playtest bugs.
- **Production point**: fun is the smallest part. The gate's Part 1 verdict
  checks fun + a declared core loop + declared toy(s) + a dev attestation that
  the scope (the fire's flame composition) feels complete. On pass, core loop,
  toys, and composition freeze as the spec for Part 2's vertical slice. Loop,
  toys, and scope are reflection checks: the app can't answer them, so it
  surfaces the dev's stoke logs as evidence and requires an honest recorded
  answer — a mirror, not a judge.
