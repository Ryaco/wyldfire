# Wyldfire — Build Specification (v1)

> Self-contained handoff for implementing Wyldfire. Everything an engineer (human
> or agent) needs to build the v1 CLI. Decided items are stated as fact;
> recommendations for still-open items are marked **[REC]**.

## 0. Agent brief

Build **Wyldfire**, an opinionated finite-state-machine CLI for solo indie game
developers, based on Benjamin Kean Anderson's *Production Point: How to Plan
and Finish Your Game as a Solo Developer* (2023). The app enforces Anderson's
discipline: a developer prototypes freely, then must pass a three-part **gate**
before entering **production**. The CLI root is `wyld`. Fire-themed
vocabulary throughout. No AI features anywhere — deliberate scope decision.

Stack: **Python 3.11+ with Click**, **SQLite** (stdlib `sqlite3`, no ORM for
v1), `pytest` for tests. CLI-first; every command must map 1:1 to a future
API endpoint (so keep I/O logic separate from Click wrappers).

## 1. Non-negotiable design principles

1. **Opinionated FSM.** The app nags, blocks, and requires evidence. You
   cannot wander into production — you earn it through the gate.
2. **Accountability over prohibition.** Where the user must be able to
   override the app (waiving a gate check, excluding a playtest), the override
   is always allowed but always **recorded with a reason**. The paper trail
   *is* the opinionation.
3. **Mirror, not judge.** For judgment calls (is the core loop defined? does
   the scope feel complete?), the app cannot answer — it surfaces the user's
   own data (stoke logs) and requires an honest, recorded answer.
4. **Maker mode is multi-stream; manager mode is single-stream.** Creative
   operations (spark/version/stoke flames) are global and need no context.
   Managerial operations (gate, wick) are scoped to one checked-out fire.
   This protects against maker/manager schedule-switching (attention residue).
5. **No AI, no external tool hooks.** No tag suggestions, no summaries, no
   integrations with Aseprite/Blender/DAWs. Wyldfire tracks metadata and tasks;
   the making happens elsewhere.
6. **Notes are evidence.** Smoke transitions, waivers, exclusions, and
   attestations all require a `--note`/`--reason`. Timestamps everywhere.
   Every long-text flag has a `-file` variant with the identical stem
   (`--desc`/`--desc-file`, `--notes`/`--notes-file`, resolved by
   `wyldfire/core/text_utils.py::resolve_text_or_file`); passing both forms
   is an error, file contents are read as UTF-8 and stored inline in the
   event payload.

## 2. Terminology

| Term | Meaning |
|------|---------|
| `wyld` | CLI root |
| project | Container (a directory with `.wyld/`). Holds fires, flames, templates. |
| flame | A prototype: juice-less mechanical proof of concept (can be paper). |
| spark | Create a flame. |
| version | An iteration of a flame (v1, v2, …). |
| stoke | A playtest. Logs tester, notes, optional dev-defined metrics, and commits staged smoke. |
| metric | A dev-defined measurement (e.g. enjoyment 1–10). Asked consistently across stokes; numeric metrics trend across versions. |
| smoke | An issue/bug. First-class, decoupled from flames. Lifecycle: open → identified → cleared, note required at each step. |
| ember | A parked idea, banked during prototype, reviewed at the gate. |
| fire | A named collection of flames (many-to-many), like a spec list. **Phases live on fires, not projects.** |
| core loop | The repeated play cycle, declared as a sentence or two on the fire. |
| toy | A playful system (win/lose aside), declared on the fire. |
| wick | Ordered burn-down list of content for a fire, worked one bundle at a time. |
| bundle | A scope unit (e.g. "area 1"): holds sub-bundles OR fuel, plus free-form metadata. |
| fuel | Atomic content unit. Types: `task` or `define`. Lifecycle: queued → creating → finished. |
| define fuel | Deferred design decision; entering `creating` prompts the user to design the bundle. |
| template | Named reusable bundle structure (project-level). |
| lap | One gate attempt (Part 1 verdict), recorded pass or hold with reasons. |
| tester | Named playtester with free-form notes about their quirks. |

## 3. Architecture & storage

- **Project detection:** a project is any directory containing `.wyld/`.
  `wyld` resolves the project by walking up from the cwd. `wyld init [name]`
  creates `.wyld/` in the cwd.
- **Registry:** `~/.wyld/registry.json` maps project paths → names, maintained
  automatically on `init` (needed for cross-project smoke search).
- **Source of truth: append-only JSONL event log.** Every wyld mutation
  appends one event file under `.wyld/events/`, named
  `<utc-timestamp>-<uuid>.json` (e.g.
  `events/20261013T065812-9f3a2c1d.json`). The event is the write; nothing
  else is. Event schema:
  ```json
  { "id": "<uuid>", "ts": "<utc ISO-8601>", "actor": "<who>",
    "type": "<entity>.<past-tense-verb>", "payload": { ... } }
  ```
  Examples: `flame.sparked`, `flame.versioned`, `stoke.logged`,
  `metric.defined`, `smoke.staged`, `smoke.unstaged`, `smoke.opened`,
  `smoke.identified`,
  `smoke.cleared`, `ember.banked`, `ember.kindled`, `fire.started`,
  `fuel.finished`, `time.logged`, `gate.part1.passed`. Event *types* follow
  `<entity>.<past-tense-verb>`;
  the build agent enumerates the full list from the command reference.
- **SQLite is a disposable projection.** `.wyld/wyld.db` (WAL mode) is derived
  state, rebuilt by replaying `.wyld/events/` in `(timestamp, client_id)`
  order. One "apply event → update tables" layer sits behind every command
  handler; the §4 schema becomes the projection schema, unchanged in shape.
  Because the DB is derived, **it is gitignored** — it never syncs, never
  backs up.
- **`.wyld/` is gitignored wholesale.** The game repo carries no wyldfire
  data — wyld is the decision/process layer, git is the file layer, and they
  stay separate. (`.wyld/config.toml` holds the server URL and project id; a
  new machine joins an existing project with
  `wyld clone --server <url> --project <id>`.)
- **Writes go through the CLI only.** Agents, importers (e.g. Google Form
  ingestion), and any future GUI all call `wyld` commands. Validation,
  version-pinning, and event generation live in exactly one place.
- **Idempotent apply.** An `applied_events` table records event UUIDs already
  folded into the projection, so re-applying the log (or receiving the same
  event twice over sync) is harmless.
- **Snapshots.** Every few hundred events (or on `wyld snapshot`), write a
  snapshot DB next to the log so fresh rebuilds are fast. Snapshot + log
  tail = full state.
- **Actor attribution.** `actor` is a first-class event field. Human actions
  record the user; agent actions record the agent. When `WYLD_AGENT=1` is set,
  the CLI *refuses* judgment commands — gate attestations, stoke-evidence
  exclusions, check waivers — via `check_agent_guardrail()`
  (`wyldfire/core/events.py`), called at the top of those service functions.
  Bookkeeping agents may transcribe (stokes, smoke symptoms) but never judge;
  the refusal error names the human-only rule.
- **`.wyld/` layout:** `config.toml` (server URL, project id, mode),
  `events/`, `wyld.db` (gitignored), `snapshots/`, `migrations/`
  (projection migrations only).
- **Output:** human-readable tables by default; every `list`/`show`/`status`
  command supports `--json` for scripting and the future GUI.
- **Errors:** non-zero exit, one-line `Error: <what> (<how to fix>)`. Never a
  traceback for user errors.

## 4. Data model (proposed v1 schema)

`.wyld/wyld.db` (WAL mode) is the disposable SQLite **projection** of the
`.wyld/events/` log (§3) — the schema below is the projection schema,
**proposed v1**. Keep migrations in `.wyld/migrations/` if it evolves. All
timestamps UTC ISO-8601.

```sql
-- Fires: phases live here. phase ∈ prototype | gate:part1 | gate:part2 |
-- gate:part3 | production | shipped
CREATE TABLE fires (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  phase TEXT NOT NULL DEFAULT 'prototype',
  is_current INTEGER NOT NULL DEFAULT 0,
  core_loop TEXT DEFAULT '',
  toys_json TEXT NOT NULL DEFAULT '[]',      -- JSON array of strings
  scope_attested_at TEXT,                    -- NULL until attested
  scope_attest_note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

-- Many-to-many flame membership, with pinned versions on gate pass.
-- pinned_version NULL until the fire's first Part 1 pass.
CREATE TABLE fire_flames (
  fire_id INTEGER NOT NULL REFERENCES fires(id),
  flame_id INTEGER NOT NULL REFERENCES flames(id),
  pinned_version INTEGER,
  added_at TEXT NOT NULL,
  PRIMARY KEY (fire_id, flame_id)
);

CREATE TABLE flames (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'sparked',     -- sparked|burning|tested|crowned|doused
  created_at TEXT NOT NULL
);

CREATE TABLE flame_versions (
  id INTEGER PRIMARY KEY,
  flame_id INTEGER NOT NULL REFERENCES flames(id),
  n INTEGER NOT NULL,
  notes TEXT NOT NULL,                       -- required
  created_at TEXT NOT NULL,
  UNIQUE (flame_id, n)
);

-- Stokes target flames or fires. A stoke needs at least one of: notes,
-- metric values, or staged smoke committed at stoke time. (No beta
-- special-case: a production stoke is just a stoke, usually notes + smoke.)
CREATE TABLE stokes (
  id INTEGER PRIMARY KEY,
  target_kind TEXT NOT NULL,                 -- flame | fire
  target_id INTEGER NOT NULL,
  flame_version_id INTEGER REFERENCES flame_versions(id),  -- auto = current version
  tester TEXT NOT NULL DEFAULT 'dev',
  notes TEXT DEFAULT '',
  excluded INTEGER NOT NULL DEFAULT 0,
  exclude_reason TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

-- Dev-defined metrics (project-level). The same question, asked every time.
CREATE TABLE metrics (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  prompt TEXT NOT NULL,                      -- e.g. "How much did you enjoy it? (1-10)"
  type TEXT NOT NULL DEFAULT 'text',         -- number | text
  created_at TEXT NOT NULL
);

CREATE TABLE stoke_metrics (
  stoke_id INTEGER NOT NULL REFERENCES stokes(id),
  metric_name TEXT NOT NULL,
  value_text TEXT NOT NULL,
  value_num REAL,                            -- set when metric type = number
  PRIMARY KEY (stoke_id, metric_name)
);

CREATE TABLE testers (
  name TEXT PRIMARY KEY,
  note TEXT DEFAULT ''
);

-- Smoke: context_kind ∈ flame | fire | gate | production (+ context_id or name)
CREATE TABLE smoke (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  context_kind TEXT NOT NULL,
  context_ref TEXT NOT NULL DEFAULT '',
  severity INTEGER NOT NULL,                 -- 1=nit/polish 2=problem 3=critical [REC]
  status TEXT NOT NULL DEFAULT 'open',       -- staged|open|identified|cleared
  stoke_id INTEGER REFERENCES stokes(id),    -- set when a stoke commits staged smoke
  tags TEXT NOT NULL DEFAULT '',             -- comma-separated, organic
  created_at TEXT NOT NULL
);

CREATE TABLE smoke_transitions (
  id INTEGER PRIMARY KEY,
  smoke_id INTEGER NOT NULL REFERENCES smoke(id),
  to_status TEXT NOT NULL,
  note TEXT NOT NULL,                        -- required at every transition
  created_at TEXT NOT NULL
);

CREATE TABLE embers (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  note TEXT DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'content',      -- content | mechanic (changeable)
  state TEXT NOT NULL DEFAULT 'banked',      -- banked|kindled|dismissed
  state_note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

-- Wick: ordered depth-first burn plan per fire.
CREATE TABLE wick_bundles (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id),
  parent_id INTEGER REFERENCES wick_bundles(id),
  name TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  position INTEGER NOT NULL,                 -- order among siblings
  cut INTEGER NOT NULL DEFAULT 0,
  cut_reason TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (fire_id, parent_id, name)
);

CREATE TABLE wick_fuel (
  id INTEGER PRIMARY KEY,
  bundle_id INTEGER NOT NULL REFERENCES wick_bundles(id),
  name TEXT NOT NULL,
  fuel_kind TEXT NOT NULL DEFAULT 'task',    -- task | define
  type_tag TEXT NOT NULL DEFAULT '',         -- e.g. sprite, audio (for ETA)
  state TEXT NOT NULL DEFAULT 'queued',      -- queued|creating|finished
  time_min INTEGER NOT NULL DEFAULT 0,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE templates (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  definition_json TEXT NOT NULL              -- {bundles:[{name,count}], fuels:[{name,type}]}
);

CREATE TABLE gate_config (
  fire_id INTEGER PRIMARY KEY REFERENCES fires(id),
  min_stokes INTEGER NOT NULL DEFAULT 3,
  blocked_severity INTEGER NOT NULL DEFAULT 2
);

-- Verdicts: kind ∈ initial | lap. Rejections of initial verdicts are rows
-- with verdict='hold' too (history accumulates); only laps get numbers.
CREATE TABLE gate_verdicts (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id),
  kind TEXT NOT NULL,                        -- initial | lap
  lap_no INTEGER,                            -- NULL for initial
  verdict TEXT NOT NULL,                     -- pass | hold
  reasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE gate_overrides (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id),
  check_name TEXT NOT NULL,
  kind TEXT NOT NULL,                        -- waive | exclude-stoke
  ref_id INTEGER,                            -- stoke id for exclusions
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

## 5. Finite-state machines

### Fire phase (per fire)
```
prototype ──► gate:part1 ──► gate:part2 ──► gate:part3 ──► production ──► shipped
                  │                                                │
                  │ hold                                           │ lap (Part 1 re-verdict)
                  ▼                                                ▼
              prototype                                    gate:part1 ──► production
```
- `gate:part1 --hold--> prototype` (initial rejection; reasons recorded, no lap).
- Lap: `production --gate open--> gate:part1`; pass → production (re-freeze);
  hold → production unchanged (reasons recorded on the lap).
- `ship` is only valid from production.

### Flame
```
sparked ──► burning ──► tested ──► crowned
                               └──► doused
```
- `sparked` on `flame spark`; → `burning` on second `version`; → `tested` on
  first stoke. `crown`/`douse` are terminal, note required.

### Smoke
```
staged ──► open ──► identified ──► cleared
```
`staged` is the pre-commit state: smoke staged during a playtest, opened
when the stoke commits (see §6). Note required at every transition
(symptom → diagnosis → fix). `wyld smoke log` skips `staged` and opens
directly.

### Fuel
```
queued ──► creating ──► finished
```
- `start` → creating; `finish` → finished. Define-fuels auto-enter creating
  when the burn reaches them.

### Ember
```
banked ──► kindled
      └──► dismissed
```
Note required on kindle/dismiss. Content embers kindle toward the wick/scope;
mechanic embers kindle into new flames.

## 6. Command reference (complete)

Global: `--fire <name>` selects the fire (defaults to checked-out fire).
`list`/`show`/`status`/`eta` accept `--json`. Names are unique per scope
(flames/bundles per project; fires per project; fuel per bundle).

### Project
```
wyld init [name] [--server <url>]  # create .wyld/ here, register in ~/.wyld/registry.json
wyld status [--json]        # dashboard: fires+phases, checked-out fire, wick position, open smoke counts
```

### wyld sync — hosted sync (v1, offline-first)
```
wyld login --server <url>   # prompt for API token, store in ~/.config/wyldfire/credentials (0600; never in project)
wyld logout                 # forget the token for this server
wyld link [--server <url>]  # pair this project with a server-side project (creates it if needed);
                            # with no URL and exactly one stored credential, uses it; with several,
                            # suggests them ("did you mean --server <url>?")
wyld clone --server <url> --project <id> [directory]
                            # join an existing project on a new machine: writes the project id +
                            # server URL into a fresh local config, then pulls the full event history
wyld sync [--json]          # push local events, pull remote events, apply, print sync report
wyld doctor [--json]        # orphans, rejected events, possible duplicates needing a human
```

### wyld flame — prototypes (global, no fire context)
```
wyld flame spark <name> --desc "..." | --desc-file PATH
wyld flame list [--json]                    # sorted by most recent stoke, desc [REC]
wyld flame show <name> [--json]             # incl. versions, stokes, state
wyld flame version <name> --notes "..."     # required notes; sparked→burning on 2nd version
wyld flame stoke <name> [--tester NAME] [--notes "..." | --notes-file PATH] [--metric name=value ...]
                                            # --tester defaults to dev; records flame version automatically
                                            # needs ≥1 of: notes, metric values, staged smoke (bare stoke rejected)
                                            # commits staged smoke anchored flame/<name> → open, linked to this stoke
wyld flame crown <name> --note "..."        # mark chosen (terminal) [REC name]
wyld flame douse <name> --note "..."        # mark killed, kept as lesson (terminal)
```

### wyld tester
```
wyld tester note <name> --note "..."        # free-form notes on quirks
wyld tester list [--json]
```

### wyld metric — dev-defined measurements (project-level)
```
wyld metric define <name> --prompt "..." [--type number|text]
                                            # type defaults to text; number trends across versions
wyld metric list [--json]                   # shows prompts (ask these of every tester)
wyld metric show <name> [--json]            # definition + values across stokes (mean for numbers)
wyld metric remove <name>                   # definition only; recorded stoke values are kept
```

### wyld smoke — issues (global; anchored via --on)
```
wyld smoke log <title> --on <ctx> --severity 1-3 [--tags "a,b"] [--notes "..." | --notes-file PATH]
                                            # ctx: flame/<n> | fire/<n> | gate | production ; → open, notes=symptom
wyld smoke stage <title> --on <ctx> --severity 1-3 [--tags "a,b"] [--notes "..." | --notes-file PATH]
                                            # ctx: flame/<n> | fire/<n> only ; → staged (pre-open)
                                            # a stoke on that flame/fire commits staged smoke → open, linked to the stoke
wyld smoke staged [--on <ctx>]              # list staged smoke
wyld smoke unstage <id>                     # discard staged smoke (never opened; prints what was dropped)
wyld smoke identify <id> --notes "..." | --notes-file PATH   # → identified, notes=diagnosis (required)
wyld smoke clear <id> --notes "..." | --notes-file PATH      # → cleared, notes=fix (required)
wyld smoke tag <id> --tags "a,b"
wyld smoke list [--on <ctx>] [--status staged|open|identified|cleared] [--severity N] [--json]
wyld smoke show <id> [--json]
wyld smoke search --tags "a,b" [--status cleared] [--all] [--json]
                                            # current project first; auto-widens to all local if empty; --all skips ahead
```

### wyld ember — parked ideas
```
wyld ember bank <title> [--desc "..." | --desc-file PATH] [--kind content|mechanic]   # default kind content; --note is an alias of --desc
wyld ember list [--kind ...] [--state ...] [--json]
wyld ember show <id> [--json]
wyld ember kindle <id> --note "..."         # content→ toward wick/scope (dev adds bundle/fuel, notes where);
                                            # mechanic→ sparks a flame from the ember
wyld ember dismiss <id> --note "..."
wyld ember set-kind <id> --kind <k> --note "..."   # reclassify as understanding evolves
```

### wyld fire — collections of flames (fire-scoped)
```
wyld fire start <name> --flames a,b [--desc "..."]
wyld fire list [--json]                     # like git branch: names + phases
wyld fire checkout <name>                   # like git checkout
wyld fire show <name> [--json]              # flames+pinned versions, loop, toys, phase, wick summary
wyld fire add-flames <name> --flames ...
wyld fire remove-flames <name> --flames ...
wyld fire set-loop "<sentence or two>"      # shows stoke history first (mirror, not judge)
wyld fire add-toy "<text>"
wyld fire stoke <name> [--tester NAME] [--notes "..." | --notes-file PATH] [--metric name=value ...]
                                            # composition test; NOT version-pinned (fire-level)
                                            # needs ≥1 of: notes, metric values, staged smoke (bare stoke rejected)
                                            # commits staged smoke anchored fire/<name> → open, linked to this stoke
wyld fire ship [--fire <n>]                 # final gate out of production (see §7)
```

### wyld gate — the three-part process (fire-scoped)
```
wyld gate status [--fire <n>] [--json]      # each check: pass/fail + provenance (default|custom|waived)
wyld gate open [--fire <n>]                 # Part 1 verdict; on a passed fire starts a LAP (re-gate)
wyld gate config [--fire <n>] [--min-stokes N] [--blocked-severity S]
                                            # no flags → show current (defaults: 7.0, 3, 2)
wyld gate attest-scope --note "..."         # dev attests composition covers the whole game
wyld gate exclude-stoke <id> --reason "..." # drop a stoke's evidence from the gate (recorded)
wyld gate waive <check> --reason "..."      # override a failing check (recorded)
wyld gate slice set --bundles a,b           # designate slice = head bundles of the wick
wyld gate slice-done --note "..."           # Part 2 exit: slice designated+built+stoked+attested
wyld gate plan-done --note "..."            # Part 3 exit: no unresolved define-fuels + attestation
wyld gate laps [--fire <n>] [--json]        # lap history (numbered re-gates)
```

### wyld wick — the content burn-down (fire-scoped)
```
wyld wick plan [--fire <n>]                 # initialize the wick
wyld wick bundle add <name> [--under <parent>] [--meta k=v ...] [--template <t>]
wyld wick bundle define <name> [--meta k=v ...]   # fill metadata during a define-fuel
wyld wick bundle list [--json]              # tree view, depth-first order
wyld wick bundle show <name> [--json]
wyld wick fuel add <name> --to <bundle> [--type <tag>] [--note "..."]
wyld wick fuel define <bundle> --note "..." # create a define-fuel (deferred design)
wyld wick start <fuel>                      # → creating
wyld wick finish <fuel> [--note "..."]      # → finished; burn advances (note optional [REC])
wyld wick log <fuel> --time 2h30m           # accepts 2h30m | 90m | 1.5h
wyld wick next [--json]                     # current burn position
wyld wick list [--json]
wyld wick cut <bundle> --reason "..."       # remove bundle (light, recorded)
wyld wick scope-change --reason "..."       # content addition: shows ETA impact, then applies
wyld wick eta [--json]                      # per-type breakdown + projected finish date
```

### wyld template — reusable bundle structures (project-level [REC])
```
wyld template new <name> [--bundles "X x3, Y x4, Z x2"] [--fuels "A:sprite, B:sprite, C:audio"]
wyld template list [--json]
wyld template show <name> [--json]
wyld template delete <name>
```

## 7. Gate design

### Part 1 — the verdict (fixed checklist [REC], per-fire thresholds)
`wyld gate open` evaluates, in order. Defaults: `min_stokes=3`
(on current versions), `blocked_severity=2`.

| # | Check | What passes |
|---|-------|-------------|
| 1 | Playtest evidence | ≥ min_stokes non-empty stokes (notes, metric values, or committed smoke). Fire stokes preferred; falls back to member-flame stokes at pinned/current versions. History — notes and metric trends — shown broken down by tester as the mirror. |
| 2 | Core loop | non-empty declaration on the fire (freezes on pass). |
| 3 | Toys | ≥1 declared toy (freezes on pass). |
| 4 | Scope attested | `attest-scope` recorded with note (dev judgment; stoke history shown at attest time). |
| 5 | Smoke | zero open smoke with severity ≥ blocked_severity in the fire's contexts (flame/*, fire/<name>, gate). |
| 6 | Embers | zero embers in `banked` state (all kindled or dismissed). |

- **Provenance:** `gate status` shows each check as default / custom / waived(+reason).
- **Waivers:** every check waivable via `gate waive <check> --reason` [REC: no unwaivable checks — the paper trail is the control].
- **Pass:** core loop + toys + composition freeze; each flame pinned at its
  current version (`fire_flames.pinned_version`); phase → `gate:part2`.
  Verdict row written (`kind=initial`).
- **Hold:** phase → `prototype`; structured reasons recorded (they become the
  prototype todo list). Verdict row written. No lap.

### Part 2 — vertical slice
1. `gate slice set --bundles` designates the slice = head bundles of the wick
   (slice work is not throwaway — it becomes the first burned bundles).
2. Gate grants limited content access: wick commands work, but only within
   the designated slice bundles (enforce by refusing fuel ops outside them).
3. Burn the slice, then stoke it: **≥1 stoke required** (fire-level stoke on
   the slice; scores required here).
4. `gate slice-done --note`: app verifies slice designated, all slice fuel
   finished, ≥1 stoke present; the note is the dev's pitch-ready attestation
   (reflection check — slice stoke history shown). → phase `gate:part3`.

### Part 3 — content plan
Plan the iteration-1 wick (bundles, fuel, define-fuels for known unknowns,
templates welcome). `gate plan-done --note` requires:
- zero unresolved define-fuels (every deferred decision expanded), and
- the attestation note (dev judges the plan covers iteration 1).
→ phase `production`.

### Laps — re-gating a passed fire
`wyld gate open` on a fire in `production` (or any post-pass phase) starts a
**lap**: Part 1 re-verdict only. Typical trigger: adopting a new flame.
- New flame must already be prototyped/stoked (flame ops are global).
- Pass → re-freeze (new pins incl. the new flame; loop/toys re-declared if
  changed) → back to `production`. Wick may then be extended under
  content-addition rules.
- Hold → stays in `production`, flame not added, reasons recorded on the lap.
- Laps numbered per fire; `gate laps` lists history.

### Ship — leaving production
`wyld fire ship` (final gate). Requires ALL of:
- wick complete: every fuel `finished` or in a `cut` bundle;
- ≥1 production (beta) stoke — scores optional, **notes required** (its
  purpose is surfacing smoke);
- zero open smoke with severity ≥ 2 in the fire's contexts;
- zero open smoke tagged `polish`.
- (staged smoke doesn't count — it's not filed until a stoke commits it;
  `wyld doctor` flags staged smoke left sitting uncommitted.)
→ phase `shipped` (terminal).

## 8. Wick design (detail)

- **Traversal:** depth-first, in `position` order. `wick next` shows the first
  unfinished, uncut fuel in traversal order. Reaching a bundle whose first
  item is a define-fuel auto-moves that fuel to `creating` and prompts the
  dev to define the bundle (`wick bundle define` + add sub-bundles/fuel),
  then `wick finish "define: <bundle>"` resumes the burn.
- **Scope discipline:** new fuel appears only by (a) expanding a define-fuel,
  (b) `wick scope-change` (content addition: logged reason + app shows added
  hours and new projected date before applying), or (c) kindling a content
  ember. New *mechanics* are never a scope change — bank as ember / new lap.
- **Cut:** `wick cut <bundle> --reason` marks cut (recorded, light). Cut
  bundles are skipped by traversal and excluded from ETA.
- **Time & ETA:** `wick log <fuel> --time` accumulates minutes. `wick eta`
  computes per fuel-type: `avg(finished fuel of type) × remaining fuel of
  type`; bundles still behind define-fuels are estimated at the average total
  time of defined sibling bundles (same template preferred, else all).
  Output: per-type lines + `projected finish: <date>`. With no data:
  `not enough data yet`.
- **Templates** live at project level [REC]; `wick bundle add --template`
  scaffolds sub-bundles + typed fuel, then the dev customizes.

## 9. UX rules (apply everywhere)

1. **Notes are evidence.** Required: smoke transitions, flame crown/douse,
   waivers, stoke exclusions, attestations, wick cut/scope-change, ember
   kindle/dismiss/set-kind, flame versions. Optional: wick finish, stoke notes.
   Every long-text flag (`--desc`, `--notes`) has a `-file` variant with the
   identical stem; passing both is an error.
2. **No silent state changes.** Every mutation prints what changed and the new
   state (`→ smoke #3 identified`, `→ fire "full-game" is now in gate:part2`).
3. **Never a bare "no".** Blocks always list structured, actionable reasons.
4. **Mirror, not judge.** Reflection checks (loop, toys, scope/slice/plan
   attestations) display the relevant stoke history before prompting.
5. **Single-fire focus.** Fire-scoped commands act on `--fire` or the
   checked-out fire; if neither is set, error tells the user to checkout.
6. **Fire theme in copy.** Prefer fire vocabulary in user-facing strings
   (burn, kindle, douse); keep `wick`/`fuel`/`bundle` consistent — never say
   "pipeline" or "task".
7. **Timestamps** UTC ISO-8601, stored on every row.

## 10. Open decisions → recommendations

| # | Question | Recommendation | Status |
|---|----------|----------------|--------|
| 1 | Flame choose/kill command names | `crown` / `douse` | [REC] |
| 2 | Severity scale | 1=nit/polish, 2=problem, 3=critical/blocker | [REC] |
| 3 | Unwaivable gate checks | none — all waivable with reason | [REC] |
| 4 | Template scope | project-level, shared by all fires | [REC] |
| 5 | Repinning a flame in a gated fire | only via lap (re-gate) | [REC] |
| 6 | Gate re-entry: reset checks? | history accumulates; re-evaluate fresh each attempt | [REC] |
| 7 | Stoke↔version pinning | stokes auto-record version; fun check needs min_stokes on current version | [REC] |
| 8 | Note on wick finish | optional | [REC] |
| 9 | Wick reorder mid-production | allowed with `--reason`, logged | [REC] |
| 10 | Beta stoke shape | scores optional, notes required | decided |
| 11 | Scope-change ceremony | content: logged reason + ETA impact shown; mechanical: not a scope change (ember/lap) | decided |
| 12 | Storage | hybrid: JSONL event log is the source of truth, SQLite is a disposable projection | decided |
| 13 | Sync | v1: hosted service, offline-first, server = merge point; deterministic collision policy (§13) | decided |

## 11. Build milestones (with acceptance)

- **M1 — foundation.** `init`/registry, DB+schema, flame lifecycle
  (spark/version/list/show), smoke lifecycle + tag + search (incl.
  cross-project widening). *Accept: the §12 walkthrough's prototype half runs
  end to end.*
- **M2 — playtests & fires.** stokes/testers/metrics, crown/douse, fire CRUD +
  checkout + many-to-many membership, fire stokes. *Accept: two fires sharing
  flames, each with own stoke histories.*
- **M3 — gate Part 1.** checks engine, `config`, verdicts, waivers,
  exclusions, attestations (loop/toys/scope), pinning, `status` provenance.
  *Accept: a fire passes Part 1 with frozen pins; a hold returns it to
  prototype with reasons.*
- **M4 — gate Parts 2–3 + wick.** slice set/done, wick CRUD, define-fuels,
  `plan-done`, traversal/`next`. *Accept: slice built→stoked→done; plan with
  a define-fuel completes after expansion.*
- **M5 — production.** burn loop, time log, ETA, cut/scope-change (with ETA
  impact), templates, beta stokes, `ship`, laps, ember kinds + reverse kindle.
  *Accept: full run prototype→ship, plus a lap adding a flame.*
- **M6 — polish.** `status` dashboard, `--json` everywhere, shell completion,
  `pytest` suite green, README.
- **M7 — sync.** event push/pull, `login`/`link`/`sync`/`doctor`, offline
  queue, idempotent apply, collision policy (§13) with sync report.
  *Accept: two clients edit offline — a conflicting scalar edit, an
  add-vs-delete, concurrent smoke transitions; after sync both converge,
  nothing is lost, and the report explains every resolution.*

Work milestone by milestone; each must be demoable before the next.

## 12. Condensed end-to-end walkthrough

```
$ wyld init wildfire-game && cd wildfire-game
$ wyld flame spark "wildfire" --desc "cut firebreaks, starve the fire"
$ wyld metric define enjoyment --prompt "How much did you enjoy it? (1-10)" --type number
$ wyld flame stoke wildfire --tester Jo --metric enjoyment=6 --notes "wind chaos"
$ wyld flame version wildfire --notes "wind every 2 turns"
$ wyld flame stoke wildfire --tester Jo --metric enjoyment=8 --notes "sings now"
$ wyld ember bank "ashen city theme" --note "rain-slick streets vs fire glow"
$ wyld fire start "game" --flames wildfire --desc "the full game"
$ wyld fire checkout game
$ wyld fire stoke game --tester Jo --metric enjoyment=8 --notes "composition works"
$ wyld fire set-loop "spot fire → cut firebreaks → starve it → score"
$ wyld fire add-toy "cutting firebreaks"
$ wyld gate attest-scope --note "one mechanic, one game"
$ wyld ember kindle 1 --note "becomes area 1 theme"
$ wyld gate open                      # → Production point reached. Phase: gate:part2
$ wyld wick plan
$ wyld gate slice set --bundles "area 1"
$ wyld wick bundle add "area 1" --meta theme="ashen city"
$ wyld wick fuel add "firefighter sprite" --to "area 1" --type sprite
$ wyld wick start "firefighter sprite" && wyld wick log "firefighter sprite" --time 3h
$ wyld wick finish "firefighter sprite"
$ wyld fire stoke game --tester Jo --metric enjoyment=9 --notes "slice sings"
$ wyld gate slice-done --note "pitch-ready"     # → gate:part3
$ wyld wick bundle add "area 2" && wyld wick fuel define "area 2" --note "bridge"
$ wyld wick bundle add "area 3" --meta theme="flooded dam"
$ wyld gate plan-done --note "iteration 1 covers areas 1-3"  # → production
# ... burn the wick, beta stokes, cut/scope-change as needed ...
$ wyld fire ship                      # → shipped
```

## 13. Sync — offline/online hybrid (v1)

wyld is **offline-first**: every mutation appends to the local event log
immediately, and the tool always works with no network. When the server is
reachable, mutating commands opportunistically push; `wyld sync` does a full
push + pull + apply and prints a report. No network → work locally, sync
later. The server is the **merge point**, not the sole origin — either side
can originate events.

### Server (v1)

- **Stack:** FastAPI + SQLite, single-tenant personal use (Postgres later if
  ever needed).
- **Deployment:** containerized. A multi-arch (amd64/arm64) `Dockerfile`
  (python:3.11-slim, installs `wyldfire[server]`, serves via uvicorn on
  `$PORT`) plus a `docker-compose.yml` defining the `wyld-server` service.
  Run `docker compose up -d` on any always-on host — one small VM (e.g.
  Oracle Always Free) or a Raspberry Pi is plenty. Note: sleeping free tiers
  (Render free) wake too slowly for a CLI client; prefer always-on.
  - Server state (SQLite) lives in the `/data` volume — back it up; it
    holds the merge point's copy of every event.
  - The API token is supplied via the `WYLD_SERVER_TOKEN` env var at
    deploy time, never baked into the image. The server **refuses to start**
    without it — there is no default token (fail-fast); a misconfigured
    deploy crashes loudly instead of running on a publicly-known secret.
  - Health check: `GET /health`.
- **Auth:** single API token generated at server setup. `wyld login --server
  <url>` prompts for it once and stores it in
  `~/.config/wyldfire/credentials` — never in the project directory. The
  credentials file is written with `0600` permissions (config dir `0700`).
- **API (v1 minimal):**
  - `POST /api/v1/events` — push a batch of events. Idempotent by UUID: the
    server appends unseen events, skips known ones, returns
    `{accepted, skipped}`.
  - `GET /api/v1/events?since=<ts>` — pull events newer than `since`.
  - `POST /api/v1/projects` — create-or-get the server-side project record
    backing `wyld link` and `wyld clone`.
- **UI state never syncs:** the checked-out fire, cursor positions, and other
  per-machine UI state stay local. Only domain events travel.

### What can collide (taxonomy)

The event log makes most things conflict-free. What remains:

1. **Never conflicts (append-only):** stokes, time logs, notes, attestations,
   waivers, exclusions, flame versions, laps, tester notes,
   `smoke.staged` / `smoke.unstaged`. Merged by UUID.
2. **Monotonic state machines** (fuel `creating→finished`, smoke
   `staged→open→identified→cleared`): forward-only — the merged state is the
   *furthest* state reached across all events. Concurrent same-state writes
   are idempotent. (A smoke marked `identified` on one machine and `cleared`
   on another simply ends `cleared`; both notes survive in history. Two
   clients committing the same staged smoke → the second commit is a no-op.)
3. **Scalar field edits** (flame description, ember kind, bundle metadata):
   last-writer-wins by `(timestamp, client_id)` tiebreak. Full history stays
   in the log. Clock skew across a solo dev's machines is small and every
   resolution is reported, so perfection isn't required.
4. **Fire membership** (add/remove flame): concurrent add + remove of the
   same flame → **remove wins** (a removal is an explicit scope decision;
   re-adding is one command). Reported; reversible.
5. **Wick ordering** (reorder/move): position is a fractional order key per
   item. Concurrent moves of *different* items compose; concurrent moves of
   the *same* item → last-writer-wins per item. No whole-list clobbering.
6. **Duplicate flame names:** two clients spark different flames with the
   same name offline. Identity is the UUID, so both survive; the second one
   merged is flagged in the sync report as a possible duplicate for the user
   to rename or merge. Never auto-renamed, never rejected.
7. **Add-vs-delete:** deletes are **tombstones**, never hard deletes. If one
   client deletes a bundle while another logs work inside it, the delete wins
   structurally — but the orphaned work is **preserved** and surfaced in the
   sync report and `wyld doctor` for re-homing. No silent data loss, ever.
8. **Gate transitions:** re-validate preconditions at *apply* time against
   the merged log. A stale gate pass (e.g. the fire's composition changed on
   another client after the verdict) is **rejected and reported**, never
   applied blindly. The user re-runs the verdict.

### Resolution policy (automatic, deterministic, visible)

1. Events are immutable and idempotent by UUID. Nothing is ever rewritten.
2. Append-only data merges freely; monotonic FSMs take the furthest state.
3. Concurrent scalar edits → last-writer-wins `(timestamp, client_id)`.
4. Concurrent add/remove → remove wins; one command reverses it.
5. Deletes are tombstones; orphaned work is preserved and reported.
6. Gate transitions re-validate at apply time; stale ones are rejected.
7. The **same merge function** runs on client and server — resolution is
   identical wherever it happens.
8. Every `wyld sync` prints a **sync report**: events pushed/pulled, each
   conflict with the rule applied and both values, orphans needing a home,
   rejected events. `wyld doctor` lists anything still needing a human.

Design principle: **deterministic + visible beats clever.** For a solo dev
with two or three machines, true conflicts are rare — usually "I did X on
the laptop, forgot, did Y on the desktop." The policy never loses work and
never surprises; the user fixes the rest by hand.

---
*End of build spec v1. Feed this to your coding agent milestone by milestone.
Decisions marked [REC] are the designer's recommendations, not gospel —
flag any you disagree with before building on them.*
