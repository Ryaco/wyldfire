# Wyldfire — Update Spec, week of 2026-10-19

Build spec for agy. All sections resolved 2026-10-21; build order at
the end.

## Where we stand (2026-10-20)

- v1 CLI + containerized sync server live on GCP (`http://35.202.3.19:8000`).
- All 6 `docs/ISSUES.md` items fixed and behaviorally verified; version 0.1.1.
- Specs updated to match the implementation (`5afd84b8`).
- `WYLD_AGENT=1` guardrail enforced — agents transcribe, never judge.
- Assistant has a persistent wyld install + server login.
- Known debt: server token is burned (rotation pending); server is plain
  HTTP (§3).

## Ops (do first — 10 minutes)

- **Token rotation:** fresh token → VM `.env` → recreate container →
  `wyld login` on every linked machine.

## Ideas list

### 1. Playtester workflow: Google Forms → stokes — personal workflow, NOT an app feature

Decided: form ingestion stays a *personal workflow* (Alder transcribes
responses into stokes), it does not get ingrained in wyldfire. Same instinct
as "no AI in the app" — the app stays pure, the workflow lives around it.

Pieces to set up while using it:
- Connect Google Forms; map fields → metrics / `--tester` / `--notes` /
  staged smoke (symptoms only).
- Dedup ledger of ingested response IDs.
- Convention: one form (or prefilled URL) per flame; the version is an
  explicit question ("which print run / version did you test?"),
  transcribed as `--for <version>` — since 2026-10-15 drift blocks blind
  stokes, a per-version prefilled form can't cover late reports on older
  versions (see STOKE_FORM_QUESTIONS_DRAFT.md).
- `WYLD_AGENT=1` is now enforced, so the transcribe-only boundary is
  mechanical, not just a promise.

### 2. "Users" in wyldfire — designed 2026-10-14, resolved 2026-10-20

Three decisions landed in the afternoon design session. What's settled:

- **Pull-request model for scope changes (decided).** Members edit the
  wick and its content list freely — burn fuel, log time, edit bundle
  metadata. But *changing the plan* goes through a request, approved by
  an admin: adding a bundle to the wick, cutting (deleting) a bundle,
  sparking a flame, starting a fire. The command opens a request, it
  doesn't apply the change.
- **Per-action attribution (decided).** A record of who did what: smoke
  transitions (who opened / identified / cleared), fuel burning (who
  finished the fuel), and likely flames (who created it, who advanced
  the version).
- **User-mintable agent tokens (decided).** Users mint their own agent
  tokens; agents work on behalf of the user and the record shows the
  agent's identity — everyone knows it was the agent, not the user. (This
  also names our current sin: the assistant operates on Ryan's token, so
  today anything it does looks like Ryan did it.)

Resolved 2026-10-20 (Ryan working through the session's open questions):

- **Tiers and roles.** Three tiers stand: member-direct (work the
  plan: burn fuel, log time, edit bundle metadata, stokes, smoke,
  embers) / member-via-request (change the plan) / admin-only (gate
  transitions, attestations, waivers, exclusions, ship,
  approving/denying requests). Roles: `admin` / `member` for users;
  agent tokens are a delegated class bound to a user (below).
- **Fuel and bundle definition.** Consuming a define-fuel to define
  a bundle is a free edit — definition is working the plan. Once a
  bundle is defined, changing its pipeline (adding/removing fuel
  outside the define-fuel path, restructuring) is a request.
- **Scope change.** Two things share the name. A new mechanic or
  feature in production is the lap flow — banked as an ember,
  prototyped, re-gated — and gate transitions are admin-only, so
  laps are admin-only. `wick scope-change` (adding *content* beyond
  the plan, ETA impact shown at the moment of adding) is request
  tier, by the same logic as pipeline changes above.
- **Fire membership.** Adding/removing flames on a fire is request
  tier — composition is what the gate freezes.
- **Ember kindle.** Request tier, both kinds: a content kindle adds
  to the wick, a mechanic kindle sparks a flame, and both are
  already request-tier actions.
- **Withdraw.** A member can withdraw their own open request freely.
  The withdrawal is recorded as an event (attribution holds); the
  request just leaves the open list.
- **Requests and surfacing.** Requests are events
  (`bundle.add_requested` → `request.approved`); author vs. approver
  is git's author/committer split; approval re-validates against
  current state so stale requests fail loudly instead of applying.
  `wyld req list` for review; `wyld status` nudges when open
  requests exist. No activity view (`wyld log --by`) in this spec —
  deferred until dogfooding asks for it.
- **Identity.** Events are stamped with username + email — never
  with a token. The token's job is internal: it binds the identity
  to a server account and authorizes the user to the server.
  Identity is asked once at `wyld init` (username + email, stored
  in local config) and works identically offline and logged in;
  `wyld login` binds that identity to the account and makes it
  authoritative. The client stamps `actor` (username/email) on
  every event; on push, the server replaces the stamp with the
  token owner's username/email, so a self-declared stamp can't
  impersonate anyone in the shared record. Skipped at init →
  placeholder stamp until set.
- **Agent tokens.** Users mint their own agent tokens, bound to
  their account. Agent tokens are capped at member scope — even an
  admin's agents never inherit admin, because admin-tier actions
  (approvals, gate transitions, ship) are the bigger decisions the
  admin must make themselves. Attribution shows the user with the agent named as
  a caveat: "Stoke recorded on card core rules — GameGrue (Alder)".
  (Event data: `actor` = the agent, `on_behalf_of` = the user.)
  Agent restrictions are enforced **server-side**, not only by the
  CLI — the API can be connected to directly, bypassing wyld, so
  the server is the real boundary; the client-side `WYLD_AGENT=1`
  refusal stays as a backstop. Revocation cascades: revoke your
  token → your agents' tokens die; revoke one agent → just that one.

- **Solo invisibility.** The whole users apparatus is invisible
  while a project has exactly one user (an admin) and no members —
  no roles, no requests, commands apply directly. This holds on
  the server too: a solo project gets no extra enforcement
  ceremony. The apparatus activates when a second user joins the
  project. Identity and agent attribution still apply in solo mode
  (Ryan + Alder is the proof case). An agent in a solo project acts
  on behalf of the solo user directly — no request queue in the
  way — but the agent protocols are the hard floor in every mode:
  judgment actions (attestations, waivers, exclusions, smoke
  diagnosis and clearing, gate verdicts, ship) stay refused for
  agent tokens, solo or not.

Note the interplay: per-user tokens also soften the whole "burned
token" class of problem.

### 3. HTTPS for the sync server (decided 2026-10-20: IP cert via Caddy)

Bearer token currently crosses the open internet in plaintext — bad.
Decision: encrypt via HTTPS. Constraint: no domain, just the bare IP
(35.202.3.19).

**Chosen path: Let's Encrypt IP-address certificate, served by Caddy.**
Since Jan 2026 LE issues publicly trusted certs for bare IPs — free, no
domain purchase, no client TLS config; client URLs just flip `http://`
→ `https://`. IP certs are mandatory short-lived (160 h), so Caddy's
automated renewal must stay healthy. ACME validation runs on port 80
(HTTP-01) or 443 (TLS-ALPN-01) no matter what — keep one reachable.
Serving defaults to the standard HTTPS port 443 (so TLS-ALPN-01 can
validate on the same port); the env var `WYLD_HTTPS_PORT` overrides
the listen port if ever needed — the cert binds to the IP, not the
port, and with a non-443 port validation falls back to HTTP-01 on
port 80. Also: reserve the VM's
external IP as static (free while attached) so cert and client configs
survive VM restarts.

Rejected: buying a domain (~$12/yr — revisit if collaborators arrive);
private CA (per-client install ceremony); SSH tunnel (strongest
posture, worst ergonomics); Tailscale (extra moving part).

### 4. Spec hygiene (done 2026-10-14)

Was: the specs (`docs/BUILD_SPEC.md`, `docs/UX_SPEC.md`) were stale after the
6 fixes. Fixed in commit `5afd84b8` — both docs now describe `main`: `wyld
clone`, `-file` flags, `WYLD_AGENT=1` enforcement, fail-fast token, `0600`
credentials, `link` UX, plus 5 new entries in the UX spec's decisions log.

### 5. Dogfood with Ember — docs stay vague

Real use: the Ember games get tracked in wyldfire for real next week —
flames, stokes, embers, the works. Anything that hurts becomes an issue.
But in docs/examples, Ember is not the canonical example: keep it vague,
"a TCG JRPG". (Real project in private use; generic example in public docs.)

Dogfooding finds (2026-10-15, first real use of `ember_tdl`, project ID
`e1089ab5-2f0f-4076-85d6-cb34d86e586e`):
- **`wyld link` vs `wyld sync` confusion.** Ryan ran `wyld link` expecting the
  flame to appear, when the thing that moves events is `wyld sync`. Link is
  the handshake, sync is the conversation — as a new user he reached for the
  wrong one. The link/sync distinction needs clearer help text.
  **Decided 2026-10-21:** clarify both commands' help text — link is
  the handshake, sync is the conversation.
- **No rename in v1.** Ryan asked to rename "radio and save system" to
  "radio system" plus a separate "save system" flame. The Wyldfire way
  worked — doused the combined flame (kept as a lesson: "split into two
  focused flames") and sparked two fresh ones — but a small v1 UX gap is
  logged. **Decided 2026-10-21:** add a real `wyld flame rename`
  command — a rename is a metadata event and version history carries
  over (unlike douse-and-respark, which loses it).
- **The story bible has no home.** A narrative design document is reference
  material — flames are mechanical, embers are parked *ideas*, wicks are
  production content. Ryan keeps the canonical bible in `~/Documents` and
  the assistant mirrors it in the goal workspace. Dogfooding find: narrative
  content may need a slot in the design (bundles of define-fuels were
  considered and judged a stretch).

### 6. "Thesis" — the GDD that locks in the game (resolved 2026-10-21)

The gate freezes the *what* (loop, toys, composition) but nowhere records the
*why*. The thesis is the argument the game makes — essentially the GDD,
starting with the inspiration. Two common origins: a **story looking for a
game loop** (narrative-first) or a **solid core toy looking for a full game**
to sprout around it (mechanics-first).

Proposed shape:
- **Per fire** (fires are the unit of "game"; thesis locks with the phase).
- Fields: `origin` (freeform — document the two shapes, don't enum them) +
  `statement` (long-form, `--statement-file` supported).
- Commands: `wyld fire set-thesis --origin ... --statement ... | --statement-file`
  (matching `set-loop`/`add-toy`); `wyld fire thesis` shows the GDD view
  (origin, statement, loop, toys, flames, phase).
- **Gate integration:** new Part 1 check — thesis declared. Freezes on pass
  alongside loop/toys/composition; revising a locked thesis goes through a lap.
- The thesis becomes the *criterion* for scope decisions: "does this flame
  serve the thesis?" On a lap, the first question is whether the thesis still
  holds.
- Reframe: **gate Part 1 is a thesis defense** — declare in prototype, gather
  evidence (stokes), defend at the gate.

Resolved 2026-10-21:
- **Per fire.** Each fire carries its own thesis. The project may also
  carry a plain description of the project as a whole — descriptive
  only: not a thesis, never frozen, no gate role.
- **Required at Gate Part 1.** Declarable anytime during prototype;
  the Part 1 check requires it declared.
- **Revision via lap only.** The thesis freezes when Gate Part 1
  passes. Revising it means a lap: the fire returns to prototype,
  the thesis is revised there, and re-defended at the lap's gate.

### 7. Materials drift check (locked 2026-10-15)

**Problem.** A stoke's validity depends on *what was actually tested*. If a
flame's materials changed since the recorded version, a blind stoke on
"current" is mislabeled evidence — and the gate would reason about playtests
of a game that no longer exists.

**Design.** Per-flame materials directories + content hashing. No git
dependency (deep git integration was considered and dropped as overkill;
commit↔version accounting stays a human convention in commit messages).

- **Configuring materials:** `wyld flame spark <name> --materials <dir>`
  (also settable via `wyld flame version --materials <dir>`). The suggested
  layout is `materials/<flame>/`, but any subdirectory works — the dev sets
  up their file structure however they want; wyld just hashes whatever path
  it's given. Stored on the flame. Unset → no drift checking for that flame.
  The path must exist when a version is recorded (error otherwise — catches
  typos).
- **Hash:** SHA-256 over sorted relative paths + file contents, with line
  endings normalized (`\r\n`→`\n`) so cross-platform checkouts don't
  false-positive. Recorded in the version event as `materials_hash`,
  alongside `materials_path` and the effective ignore set.
- **Drift check:** `wyld flame stoke` and `wyld fire stoke` re-hash and
  **block** on mismatch — no blind stokes on drifted materials. The block
  leads with the common case (forgot to version):
  ```
  ✗ blocked: 'combat' materials changed since v5.
    Did you forget to record the new version, or was this playtest of v5?
      wyld flame version combat --notes "..."   # record v6, then stoke
      wyld flame stoke combat --for v5 ...      # no — tested v5 as recorded
  ```
  `--for v5` is an attestation, not a bypass: the explicit version pin is
  recorded on the stoke event. The human judges version-worthiness (a README
  typo → `--for v5`; real changes → v6) — mirror, not judge.
- **Late feedback:** dev mid-changes toward v6, v5 playtest report arrives →
  `--for v5` records it honestly against v5. The gate's current-version rule
  still applies (v5 stokes don't bless v6).
- **Surfacing:** `wyld status` lists drifted flames; `wyld flame show`
  carries an ambient materials-match line (`→ v5 ✓` / `→ DRIFTED since v5`).
- **Reverse lookup:** `wyld flame materials <name>` — "which version are
  these materials?" Hashes the current dir and reports every recorded
  version with a matching hash (comparison uses each version's recorded
  ignore set). Multiple matches possible (shared content) — report all.
  No match → suggest `wyld flame version`.
- **`.wyldignore`:** project-root file, gitignore-style patterns (`*`,
  `**`, trailing `/` for dirs; no negation in v1). Built-in defaults always
  apply (`.DS_Store`, `Thumbs.db`, `desktop.ini`); user patterns additive.
  The effective ignore set is recorded per version and drift checks use the
  *recorded* set, so editing `.wyldignore` can't false-drift old versions.
- **Forms interplay:** the playtester form asks which version/print run was
  tested; the ingestion bot transcribes it as `--for <version>` (the tester
  asserts, the bot transcribes — judgment stays with the human at the table).

### 8. Flame fork (locked 2026-10-21)

Exploring a mechanic in two directions at once (mana vs. cooldowns)
is core prototyping, but full branch namespaces were rejected —
every version reference in the app (pins, `--for`, drift hashes,
gate evidence) would need branch awareness. Instead: two separate
flames, related by a recorded fork.

- **Command:** `wyld flame spark <name> --fork <source>` creates a
  new flame starting from the source's current state.
- **Copies:** the source's desc (overridable with `--desc`) and the
  materials directory *contents* (working tree as it sits) into the
  new flame's materials dir — `materials/<name>/` by default, or
  the `--materials` destination if given. Source with no materials
  → nothing copied; `--materials` just sets the path.
- **Never touches the source.** A fork writes only to its own
  materials directory; the source flame and its materials are
  untouched, and the two diverge independently from the fork point.
  A destination equal to the source's materials path is an error,
  as is a destination that exists and is non-empty (no clobbering).
- **Lineage:** the new flame records `forked_from: <source>@<vN>` —
  source plus its version at fork time. Stokes on the source up to
  that version are the shared base; the gate display can group
  variant evidence on that line.
- **Fresh history:** version and stoke history are not copied; the
  new flame's first `wyld flame version` is its own v1 (§7 drift
  rules apply as usual).

## Build order for agy (decided 2026-10-21)

1. Materials drift check (§7)
2. Flame fork (§8)
3. Thesis (§6)
4. Users (§2)
5. HTTPS (§3) + token rotation (Ops)
6. Rename + link/sync help text (§5)

This spec lives in the repo at `docs/UPDATE_SPEC_2026-10-19.md`;
every open question from the drafting sessions is resolved above.

## Non-goals

- Forms ingestion *inside* the app — decided: personal workflow only.
- Clone-by-name (ID-based clone covers v1).
- GUI/web UI — CLI-first holds.
- Any AI inside the app — the mirror-not-judge line holds.
