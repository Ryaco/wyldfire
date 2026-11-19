# Wyldfire — Update Specification (draft — next cycle)

> Status: DECIDED 2026-11-19 (Ryan) — the five open calls below were answered as recommended; implementation on branch `users-0.2.0`. Holds the planned delta from
> the 0.1.2 build (see `BUILD_SPEC.md` 0.1.2 draft) to the next version:
> the users build (roles, requests, server-side enforcement, auth layer),
> the remotes group, and the auth CLI UX.
>
> Folded into this document: the auth CLI UX draft (as §3) and the UX
> section from `UX_SPEC.md` (as §4). `UX_SPEC.md` is deleted from the repo
> in the same push that lands this spec, per Ryan's call.
>
> Document hygiene (from `BUILD_SPEC.md`): this file holds only the
> not-yet-built delta. When the cycle is complete and verified, fold it
> into `BUILD_SPEC.md` (as-built description, not plans), update the
> version marker, then retire this file. Exception: §4 (UX) is standing
> guidance, not a per-cycle delta — when this spec folds, §4 moves into
> `BUILD_SPEC.md` as a standing section, so it survives for the web UI
> cycle.
>
> Decided 2026-11-19 (Ryan, all as recommended): project creation —
> any logged-in user (creator becomes Owner); agent token expiry — none by
> default (revocable, last-used shown); master token after bootstrap —
> stays valid (alternate admin login + recovery credential); version number
> for this cycle — 0.2.0; repo filename — standing `UPDATE_SPEC.md`.
> Sequenced AFTER this cycle: the web UI spec
> draft (job + mockups settled 2026-10-28; needs the sessions/tiers from
> this cycle). Still pending, outside this cycle's build scope: Google
> Forms connection, field mapping, and end-to-end test (external personal
> workflow, never an app feature).

## 1. Users + authentication

### 1.1 Roles and tiers (§2 core, unchanged from the 0.1.2-cycle spec)

- Roles: `admin` / `member`.
- Tiers: member-direct (free edits), member-via-request (needs admin
  approval), admin-only.
- Admin-only: gate transitions, attestations, waivers, exclusions, ship,
  request approvals.
- Consuming a define-fuel to define a bundle = free edit; changing a
  defined bundle's pipeline = request.
- New mechanic in production = lap flow (admin-only via gate).
- `wick scope-change` = request tier.
- Fire membership changes and ember kindles = request tier.
- Members may withdraw their own open requests (recorded event).
- Requests are events with revalidation on approval, surfaced via `wyld
  req list` + a `wyld status` nudge. No `wyld log --by`.

### 1.2 Identity and agents

- Identity is stamped with **username + email, never the token**. On
  push, the server replaces the stamp with the token owner's identity, so
  a self-declared stamp can't impersonate anyone in the shared record.
- Agent tokens are **capped at member scope even for admins**.
  Attribution displays the user with the agent as a caveat — "GameGrue
  (Alder)" — with event data `actor` = agent, `on_behalf_of` = user.
- Restrictions are enforced **server-side**; `WYLD_AGENT=1` client
  refusal is a backstop, not the control.
- Revocation cascades user → agent tokens, and (confirmed 2026-10-31)
  also → active sessions and the held user token.
- **Solo invisibility** (server-side too): one admin, no members → no
  users apparatus. It activates when a second user joins. Identity and
  attribution still apply solo; solo agents act on behalf of the solo
  user directly, but judgment actions — attestations, waivers,
  exclusions, smoke diagnosis/clearing, gate verdicts, ship — stay
  refused for agent tokens in every mode.

### 1.3 Auth layer (decided 2026-10-28)

- **MFA required for everyone.** Users: password + TOTP. Admin: master
  token + TOTP.
- **Signup creates a request for admin approval, never instant access.**
- **MFA may be enrolled before approval (at signup).** Harmless:
  pending accounts cannot log in, approval remains the trust gate,
  secrets are encrypted at rest, and denial deletes the pending
  account and its secret (see §3).
- The **master token is the bootstrap and recovery credential**. The
  admin sets a username and password at first login (see §1.5) and
  thereafter logs in day-to-day like any user: username + password +
  TOTP. The master token also stays valid as an alternate admin login
  (master token + TOTP) — see §1.5 (decided 2026-11-19: stays valid). No admin email
  is collected.
- **Master rotation = hard cutover**, with user tokens surviving, plus an
  audit list (old token hash prefix + timestamp).
- **User revocation cascades** to that user's agent tokens (and sessions
  + held token, §1.2).
- **Project membership gated by project admins. Public = visible to
  server members, joining still gated.** The project creator is
  automatic Owner. Lesser project admins share all project-admin powers
  except elevation (owner-only).
- **Hardening trio:** master token stored in the database as hashes no
  shorter than the token; `.env` kept for initial setup only;
  token-for-session exchange; login rate limits.

### 1.4 Security decisions (confirmed 2026-10-31)

- Passwords: argon2id, minimum length 12, no complexity rules.
- All tokens (user, agent, session, master): stored as SHA-256 hashes,
  never the token itself.
- Agent token verification: server-side hash-and-compare. No derivation
  from a master secret (derivation would tangle per-token revocation).
- TOTP secrets: encrypted at rest with a `.env` key (they cannot be
  hashed — the server needs the secret to verify codes).
  Verify-a-code-before-enable on enrollment. Enrollment renders the
  otpauth URI as a terminal QR code (pure-Python library; segno
  verified 2026-10-31 — a realistic TOTP URI renders as a version-5,
  37-module code, 39 chars wide × 20 rows in compact half-block mode)
  scaled to the terminal width, with the text secret printed below as
  fallback (secret-only if the terminal is too narrow).
- Login rate limits: 5 failed attempts → 15-minute lockout, per account
  and per IP, covering password, TOTP, and master-token attempts. Admin
  recovery via the server console.
- Server-side enforcement on every call: the CLI is untrusted. No tokens
  in URLs (Authorization header only). No tokens, passwords, or TOTP
  codes in logs.
- Master token used only at login and rotation; everyday requests carry
  the session.
- Sessions: 90 days, sliding. No TOTP backup codes (recovery: admin
  reset for users, server console for the admin).
- Signup: open-with-approval + rate limit (see §3).
- Wyld holds per-remote tokens (master for admin, user token for users)
  as durable credentials; sessions renew silently from them (§3).

### 1.5 Admin user bootstrap — created at first admin login (decided 2026-10-31, revised same day)

- **Not created at server creation.** If no users exist, the admin user
  is created when the admin first logs in: the admin proves possession
  of the master token, then sets a username and a password, then
  enrolls TOTP — all in that one login flow (§3).
- **The whole bootstrap completes atomically on TOTP verification.**
  Aborting mid-flow (before a code verifies) leaves no user behind;
  the next login retries bootstrap from the start.
- **No reserved usernames.** The admin picks their own username (it
  becomes the attribution name for admin actions — e.g. `GameGrue`,
  matching the existing "GameGrue (Alder)" agent attribution). No admin
  email is collected.
- **Day-to-day admin login is a user login** with the admin username:
  username + password + TOTP. The `--admin` path (master token + TOTP)
  remains for bootstrap and recovery.
- **Migration = the same path.** An existing server's first admin
  login after this build — no users exist yet — runs bootstrap. The
  master token value is unchanged, so nothing else about the deployment
  changes.
- **Master token after bootstrap (DECIDED 2026-11-19: stays
  valid).** The master token remains valid as an alternate admin login
  and as the recovery credential (password reset / TOTP re-enrollment
  via server console or a recovery flow). Rationale: the token holder
  already has server-level access (the token lives in the server
  `.env`), so keeping it valid does not expand the threat model — and
  retiring it would risk total lockout if the admin password is lost.
  The bootstrap-only alternative was not taken.

### 1.6 Resolved details (were open, now decided)

- (a) Agent token verification = server-side hash store (§1.4).
- (b) Session parameters = bearer tokens, 90 days sliding, no separate
  refresh-token type — the held master/user tokens serve renewal (§3).
- (c) `.env`-to-hash migration = first-boot hashing, database
  authoritative, token value unchanged (§1.5).
- (d) TOTP secret storage = encrypted at rest (§1.4).

## 2. Remotes

- A global `wyld remote` group — global as in directory
  (`~/.config/wyldfire/remotes.toml`), not linked to a project — where
  servers are registered once by name. Management commands: `add`,
  `list`, `show`, `set-url`, `rename`, `remove`, `set-default`. Bare
  `wyld remote` lists remotes.
- Auth commands live under the group (§3): `wyld remote login`,
  `signup`, `logout`. Top-level `wyld login` / `logout` / `signup`
  from 0.1.2 are replaced (pre-1.0 breaking change, no aliases).
- Project configs store the remote *name*; the URL resolves at runtime.
  `set-url` updates all linked projects at once (and clears the stored
  session for that remote). `rename` rewrites referencing project
  configs (found via the registry) and prints which changed. `remove`
  deletes the stored session and held token for that remote; projects
  still referencing the name fail with a clear error and fix.
- With exactly one remote, `--remote` is omittable everywhere; with
  several, it is required unless a default is set. `--server <url>`
  stays as an ad-hoc escape hatch for unregistered servers.
- This replaces the 0.1.1 heuristic (one stored credential → use it,
  several → suggest) with something explicit and robust.
- Admin commands (`req list`, user/session administration) take
  `--remote` and work outside any project directory — the remote, not
  the project, is the server context.
- Migration: `wyld remote login` reuses existing URL-keyed credentials,
  so no re-login on upgrade; existing projects re-link once to adopt
  the name.

## 3. Auth CLI UX (folded from the auth draft)

*Scope: the CLI flows for logging in, signing up, and using an authenticated
server — admin login, user login, signup + approval, agent tokens, sessions,
remotes, and what the security decisions mean for `link`, `sync`, `clone`,
and `logout`. Feeds the §2 update spec section. Follows the UX section:
secrets are hidden input, every mutation prints what changed, errors are
one line with a fix, never a bare "no".*

### Conventions

- Secrets (tokens, passwords, TOTP codes) are hidden input — never echoed,
  never logged, never in event payloads.
- **Wyld holds tokens per remote.** The admin's machine holds the master
  token for a remote; a user's machine holds their user token for a
  remote (issued at login). Tokens are the durable credential, stored
  `0600` in the credentials file, keyed by remote name.
- **Sessions are the working credential.** Login issues a session (90
  days, sliding) used for everyday requests. When a session expires, the
  CLI silently exchanges the held token for a fresh one — no re-prompt.
  If the held token is missing or invalid, the CLI denies the work and
  says to log in again. (This supersedes the earlier draft line that the
  master token is not stored: per Ryan's call, wyld holds the tokens.)
- **Admin gating rule.** Wyld admin work — request approvals/denials,
  user administration, session administration (`--all`), master rotation
  — is denied unless the caller holds valid admin auth for that remote
  (a valid admin session, or the master token to exchange for one).
  Missing or invalid → denied, one line, naming the fix. There is no
  degraded admin mode.
- Humans use sessions + held tokens. Automation uses **agent tokens**
  (no expiry by default, revocable any time, `token list` shows last-used
  so stale ones can be pruned). Agent tokens are capped at member scope,
  even for admins, and judgment actions stay refused for them
  server-side.
- Identity: login confirms who you are. `wyld status` and sync reports
  show the logged-in identity. Event stamps carry username + email; the
  server replaces the stamp with the token owner's identity on push.

### `wyld remote` — the server group (global, not per-project)

Remotes live in the global config (`~/.config/wyldfire/remotes.toml`),
shared by every project on the machine. Project configs store the remote
*name*; the URL resolves at runtime. Bare `wyld remote` lists remotes
(git parity).

```
$ wyld remote add main https://35.202.3.19
→ remote "main" added (https://35.202.3.19).
$ wyld remote
  main  https://35.202.3.19  logged in as admin (session valid until 2027-01-29)
$ wyld remote show main
  name: main | url: https://35.202.3.19
  login: admin (session valid until 2027-01-29)
  projects using this remote: ember_tdl
$ wyld remote set-url main https://35.202.3.20
→ remote "main" now points at https://35.202.3.20 (stored session cleared — log in again).
$ wyld remote rename main primary
→ remote renamed main → primary (1 project config updated: ember_tdl).
$ wyld remote remove primary
→ remote "primary" removed (stored session and held token deleted).
$ wyld remote set-default main
→ "main" is now the default remote.
```

- With exactly one remote, `--remote` is omittable everywhere; with
  several, it is required unless a default is set. This replaces the
  0.1.1 heuristic (one stored credential → use it, several → suggest).
- `set-url` clears the stored session for that remote (a changed address
  must not silently use a stale session); the held token is kept, so
  re-login is one command, not a re-entry of secrets.
- `remove` deletes the stored session and held token for that remote.
  Projects still referencing the name fail with a clear error and fix
  (re-link to a live remote).
- Top-level `wyld login` / `logout` / `signup` from 0.1.2 are **replaced**
  by the remote-group commands below (pre-1.0 breaking change; one way
  to do each thing, no aliases).

### Admin login — the Wyld admin, under remotes

The admin's day-to-day credential is a username + password (+ TOTP),
set at first login (see §1.5). The **master token is the bootstrap and
recovery credential**, plus TOTP for the `--admin` path.

```
$ wyld remote login main --admin
Master token: ********
→ master token accepted.
TOTP code: ******
→ logged in to remote "main" as admin (session valid 90 days, sliding).
→ master token held for remote "main" (renews sessions silently).
```

- **First admin login (no users exist yet):** after the token is
  accepted, the CLI runs bootstrap — set a username, set a password,
  enroll TOTP (terminal QR code + text secret) — and the admin user is
  created atomically when a code verifies. No session is issued until
  then:

```
$ wyld remote login main --admin
Master token: ********
→ master token accepted. No users exist yet — setting up the admin account.
Set admin username: GameGrue
Set password: ********
Password (again): ********
→ scan this QR code with your authenticator app, or enter the secret manually:
  [QR code, terminal-rendered, scaled to fit]
  Secret: JBSWY3DPEHPK3PXP
→ enter the code from your app to confirm enrollment:
TOTP code: ******
→ TOTP enrolled and confirmed.
→ admin user "GameGrue" created.
→ logged in to remote "main" as GameGrue (admin, session valid 90 days, sliding).
→ master token held for remote "main" (bootstrap + recovery credential).
```

- **Subsequent admin logins, two paths.** Day-to-day: a user login
  with the admin username (`wyld remote login main --user GameGrue` →
  password + TOTP). Recovery/alternate: the `--admin` path (master
  token + TOTP). See §1.5 for the open point on whether the master
  token stays valid after bootstrap (recommended: yes).

- Already logged in with a valid session: `wyld remote login main
  --admin` prints the current session (`→ already logged in as admin
  (session valid until …)`) and exits; `--force` replaces it.
- Wrong token: `Error: incorrect master token (check the token and try
  again)`. Wrong code: `Error: incorrect code (codes refresh every 30s;
  wait for a new code and retry)`. Locked out: `Error: too many failed
  attempts — login locked for 15 minutes (wait, or recover via the server
  console)`.
- **Admin gating in action:** any admin command without valid admin auth
  for the target remote is denied, e.g.
  `Error: admin access required for remote "main" (log in as admin with
  `wyld remote login main --admin`)`. An invalid held token fails the
  same way: `Error: held master token for remote "main" is invalid (log
  in again with `wyld remote login main --admin`)`.

### User login — under remotes

```
$ wyld remote login main --user ryan
Password: ********
TOTP code: ******
→ logged in to remote "main" as ryan (member, session valid 90 days, sliding).
→ user token held for remote "main" (renews sessions silently).
```

- With `--user` omitted, the CLI prompts `Username:` first.
- The admin's day-to-day login is this command with their admin
  username (role admin rides on the session).
- **First user login (if TOTP not enrolled at signup):** same
  enrollment walk as admin, inside the password-verified login; no
  session until a code verifies.
- Wrong credentials: `Error: incorrect username or password (check caps
  lock and try again)` — generic on purpose; it never says whether the
  username exists.
- **Pending account** (signed up, not yet approved): `Error: account
  pending approval (the admin hasn't approved your signup yet — try again
  after approval)`.
- **Revoked account:** `Error: account revoked (ask the admin)`.
- Locked out: same 15-minute message as admin, ending with `(ask the
  admin to unlock, or wait)`.
- **User gating:** member commands require valid auth for the remote
  (user or admin session, or a held token to exchange). Missing/invalid:
  `Error: not logged in to remote "main" (log in with `wyld remote login
  main`)`.

### Signup — under remotes, a request, never instant access

```
$ wyld remote signup main
Username: ryan
Email: rj.cupar@gmail.com
Password: ********
Password (again): ********
→ set up MFA now (optional — otherwise at first login). Scan this QR code or enter the secret manually:
  [QR code, terminal-rendered, scaled to fit]
  Secret: JBSWY3DPEHPK3PXP
TOTP code: ******
→ TOTP enrolled (stored with your pending request; it takes effect when the admin approves).
→ signup request sent for ryan on remote "main" (pending admin approval).
→ you can log in once the admin approves — no access until then.
```

- Passwords that don't match re-prompt (`→ passwords didn't match, try
  again`) instead of erroring out.
- Username taken: `Error: username taken (choose another)`. Email taken:
  `Error: email already registered (log in, or sign up with another
  email)`. (Existence leaks here are inherent — two users can't share a
  username.)
- Rate-limited: `Error: too many signup requests from this address (try
  again later)`.
- Signup creates only a pending request. MFA enrollment is offered
  during signup (QR + secret + verify code) and is optional —
  declining skips straight to the request, and first login enrolls
  if not already enrolled. Enrolling early changes nothing about
  trust: the pending account cannot log in either way.

### Approval + denial (admin, via requests, remote-scoped)

Signup requests surface through the existing request machinery, with the
mirror pattern — show the request before the verdict. Admin commands take
`--remote` and work outside any project directory:

```
$ wyld req list --remote main
  #12  signup  ryan <rj.cupar@gmail.com>  requested 2026-10-31  (open)
$ wyld req show 12 --remote main
  type: signup | username: ryan | email: rj.cupar@gmail.com
  requested: 2026-10-31 13:05 UTC
$ wyld req approve 12 --remote main
→ signup approved for ryan (they can now log in; TOTP enrollment at first login if not already enrolled at signup).
$ wyld req deny 13 --remote main --reason "not a collaborator on this server"
→ signup denied for ryan2 (reason recorded; pending account and its TOTP secret deleted).
```

- Approvals/denials are admin actions, denied without valid admin auth
  (see Admin gating rule), recorded as events.
- The approved user gets no email (no email infrastructure) — they learn
  by trying to log in, or the admin tells them. The pending-login error
  changes to a normal login once approved, so "try again" is the whole
  notification story for now.

### Agent tokens (users build: server-registered)

`wyld token` exists in 0.1.2 client-side only. In the users build, minting
registers the token server-side (hash stored); the server validates it on
every call.

```
$ wyld token mint --name alder
→ agent token minted for alder (member scope — agents never inherit admin).
→ token (shown once — store it securely, it won't be shown again):
  wyld_at_9f3a2c1d8e7b4a5c6d3f2e1a0b9c8d7e6f5a4b3c2d1e0f
$ wyld token list
  alder  member  last used 2026-10-31  (created 2026-10-22)
$ wyld token revoke alder
→ agent token alder revoked (sessions made with it are revoked too).
```

- Minting requires a logged-in user session (humans mint their own agents;
  an admin's agents are still member-capped).
- Revocation prints the cascade, by name, like user revocation below.

### Sessions

```
$ wyld session list --remote main
  self  ryan  valid until 2027-01-29 (last used 2026-10-31)
$ wyld session revoke <id> --remote main
→ session revoked (that machine is logged out).
$ wyld session revoke-all --remote main
→ all sessions and held tokens revoked (every machine logged out — log in again everywhere).
```

- Users list/revoke their own sessions. The admin lists/revokes any
  session (`wyld session list --all --remote main`).
- Sessions renew silently from the held token, so expiry alone never
  locks anyone out — only a missing/invalid/revoked token does.
- **User revocation cascade:** revoking a user revokes their agent tokens
  AND their active sessions AND their held user token, and refuses future
  logins. Past events stay in history untouched, attribution intact:
  `→ user ryan revoked (3 agent tokens revoked, 2 sessions revoked, user
  token revoked)`.

### Logout — under remotes

```
$ wyld remote logout main
→ logged out of remote "main" (session and held token revoked on the server, removed locally).
```

- Logout revokes server-side AND deletes locally, so a copied session
  file or token dies. If the server is unreachable, logout still deletes
  locally and warns: `→ logged out locally; server unreachable, so the
  session and token remain valid until revoked — re-run logout when
  online to revoke them`.

### What this means for link, sync, clone

### `wyld link` — now requires login, and shows who you are

```
$ wyld link
Error: not logged in to any remote (log in with `wyld remote login <name>` first).
$ wyld remote login main --admin   # …then…
$ wyld link --remote main
→ linked to remote "main" (https://35.202.3.19) as admin — server project "ember_tdl" (created it).
```

- With exactly one remote and a login, `--remote` is omittable on link.
- The stored-credential suggestion behavior is gone, replaced by
  remotes: no remote and one remote defined → uses it; several → the
  command says which remote to pick (`--remote <name>`), or set a
  default.
- Link help text stays: link is the handshake, sync is the conversation.
- Link stores the remote *name* in `.wyld/config.toml` (not the URL).
- **Project creation:** any logged-in user can link (creating a project
  makes them its Owner — creator is automatic Owner per the Oct 28
  decisions). Membership is the control, not creation.
  *(Decided 2026-11-19: any-user creation.)*

### `wyld sync` — runs on the session, reports identity + rejections

```
$ wyld sync
→ synced as ryan (member) via remote "main" (https://35.202.3.19)
→ pushed 14 events, pulled 3 events
```

- Not logged in: `Error: not logged in to remote "main" (log in with
  `wyld remote login main`)`. Expired session with a valid held token:
  silent renewal, no error. Expired session with a missing/invalid held
  token: `Error: session expired and held token invalid (log in again
  with `wyld remote login main`)`.
- The sync report keeps its existing shape (pushed/pulled, conflicts with
  the rule applied and both values, orphans, rejected events) and gains
  one new rejection cause: tier/authorization rejections, e.g.
  `→ rejected: event "gate.part1.passed" refused — agent tokens cannot
  record gate verdicts`. Nothing is silently dropped.
- Events pushed carry the username + email stamp; the server replaces it
  with the token owner's identity, so a crafted stamp can't impersonate
  anyone in the shared record.

### `wyld clone` — requires login AND membership

```
$ wyld clone --remote main --project e1089ab5-... ember_tdl
→ joined project ember_tdl as ryan (member) via remote "main" — full event history pulled.
```

- Not logged in → the login error above. Logged in but not a member:
  `Error: not a member of this project (ask a project admin to add you)`.
- Adding members is a project-admin command (`wyld project add-member`,
  specified with the project commands — the membership list lives with
  the project, gated by project admins; the creator is automatic Owner).
- Clone-by-name still needs a project-listing endpoint (future, as in
  0.1.1 notes); clone-by-ID is the path.

### Identity + status integration

- Login confirms identity: the login output names the account and role
  (admin / member).
- `wyld status` gains one line: `→ logged in as ryan (member) via remote
  "main" (https://35.202.3.19)` — or `→ not logged in` when no session
  exists.
- `wyld identity show` reflects the logged-in account (username + email
  from the server record), not just local config.

### Decided 2026-11-19 (Ryan, all as recommended)

1. **Project creation:** any logged-in user can create a project (and
   becomes its Owner). Membership gating is the control, and solo/small-team
   servers shouldn't bottleneck on the admin for new projects.
2. **Agent token expiry:** none by default (revocable any time; last-used
   shown for pruning). Automation needs stability, and revocation is the control.
3. **Top-level login/logout/signup removed** (moved under `wyld
   remote`). Pre-1.0 breaking change; one way to do each thing, no aliases.
   (This was already decided Oct 31; the draft had listed it as open in error.)

## 4. UX — how wyld feels

*Folded from `UX_SPEC.md` (deleted from the repo on fold — this section is
now the single source of UX guidance; where `UX_SPEC.md` and `BUILD_SPEC.md`
disagreed, `BUILD_SPEC.md` wins, e.g. the flame terminal command is `crown`,
not `UX_SPEC.md`'s proposed `stoke-flame`. `UX_SPEC.md` §9 open questions are
resolved in `BUILD_SPEC.md` §10 unless listed as open in this update spec.)*

*Note on intent: `UX_SPEC.md` was written to convey the intended UX of the
HTML interface to the builder. This section preserves that intent for the
web UI build, and applies it to this cycle's CLI flows meanwhile. This
section is standing guidance, not a per-cycle delta: when this update spec
folds into `BUILD_SPEC.md`, this section moves with it (as a standing
section), so it is still present for the web UI cycle.*

Every new flow in this cycle — login, TOTP enrollment, signup requests,
approvals, revocation — must feel like wyld already feels. The rules:

### Standing principles (from `BUILD_SPEC.md` §9)

- **Mirror, not judge.** For judgment calls the app cannot answer, it
  surfaces the user's own data and requires an honest, recorded answer.
  Reflection checks (loop, toys, scope/slice/plan attestations) display the
  relevant stoke history *before* prompting — the judgment is made while
  looking at the data, not from fuzzy memory.
- **Never a bare "no".** Blocks always list structured, actionable reasons.
  A gate hold returns the fire to prototype *with* the reasons — the reasons
  are the prototype todo list.
- **No silent state changes.** Every mutation prints what changed and the
  new state (`→ smoke #3 identified`, `→ fire "full-game" is now in
  gate:part2`). Nothing is silently lost or silently overwritten.
- **Single-fire focus.** Fire-scoped commands act on `--fire` or the
  checked-out fire; if neither is set, the error tells the user to
  checkout. Maker mode is multi-stream (flame ops are global); manager
  mode is single-stream — never leave the user ambiguously "in" two
  phases at once.
- **Fire vocabulary in copy.** Prefer burn/kindle/douse; keep
  `wick`/`fuel`/`bundle` consistent — never say "pipeline" or "task".
- **Notes are evidence.** Required: smoke transitions, flame crown/douse,
  waivers, stoke exclusions, attestations, wick cut/scope-change, ember
  kindle/dismiss/set-kind, flame versions. Every long-text flag has a
  `-file` variant with the identical stem; passing both is an error.
- **Errors:** non-zero exit, one line `Error: <what> (<how to fix>)`.
  Never a traceback for user errors.
- **Timestamps** UTC ISO-8601, stored on every row.

### Copy standards (sample outputs to match)

Gate status — one line per check, pass/fail plus provenance and evidence:

```
Gate checks:
  ✓ Playtested: 4 stokes on current version v4 (1 excluded) — enjoyment trending 6→8
  ✓ Core loop declared: "spot fire → cut firebreaks → starve it → score"
  ✓ Toys declared: cutting firebreaks, wind die
  ✓ Scope: dev attests the fire's composition covers the whole game
  ✗ Open smoke: 1 at severity ≥ 2 (#4 "downtime between turns at 4p")
  ✓ Embers reviewed: 2 kindled, 1 dismissed
```

Gate hold — verdict word plus structured reasons, each naming its fix:

```
→ The gate holds.
  Reasons:
  - 1 open smoke at severity ≥ 2 (#4)
  - scope not attested (attest with `wyld gate attest-scope`)
→ fire returns to prototype with structured reasons recorded.
```

Gate pass — short and final: `→ Production point reached.`

Mirror before attestation — declaring loop/toys or attesting scope first
shows the fire's stoke history:

```
$ wyld fire set-loop "spot fire → cut firebreaks → starve it → score"
→ stoke history for this fire:
    v1  6.5  "tension is there, but wind every turn feels chaotic" (Jo)
    v4  8.0  "much better pacing, 4p game finally sings" (Jo)
→ core loop recorded. Freezes on gate pass.
```

Sync report — pushed/pulled counts, then every resolution with the rule
applied and both values, then orphans needing a human:

```
→ pushed 14 events, pulled 3 events
→ conflict: flame "draft" description edited on both sides —
  kept the newer one (desktop, 10:42). Older value in history.
→ orphan: bundle "area 2" was deleted on laptop, but desktop logged 2h
  on fuel "dust wyrm roar" inside it — preserved, see `wyld doctor`.
```

Search widening — current project first, then a spoken widening, never a
silent jump:

```
→ nothing in this project — widening to all local projects…
```

Results show the problem note *and* the fix note, so a past fix is
directly reusable: past self debugs future self.

### Rationale to preserve when designing new flows

- **Maker/manager schedule, attention residue.** Mid-prototype the dev is
  in maker mode; a planning-shaped interruption leaves residue on the
  creative work. So: bank, don't interrupt (embers exist for this); keep
  new flows short, single-purpose, and completable without a mode switch.
  An approval or login flow should not drag the dev into admin work
  mid-thought — show what's needed, take the answer, get out.
- **Stokes are notable playtests, not a complete record.** Log the ones
  that matter; skip the fifty uneventful run-throughs. Never nag for
  completeness — no streaks, no coverage guilt. The same restraint applies
  to any new tracking: record what the dev chooses to record.
- **No auto-weighting, ever.** The app surfaces who said what and the
  metric trends; the dev judges. No tag suggestions, no summaries, no
  auto-ranking — and no AI anywhere.
- **Deterministic + visible beats clever.** For sync, auth, and approvals
  alike: fixed policy, printed resolutions, preserved history. A user
  should never wonder what the app did on their behalf.

### Applying this to this cycle's new flows

- **Login / TOTP enrollment:** prompts hide secrets; enrollment
  shows a terminal-rendered QR code (compact half-block mode, scaled
  to the terminal width) with the text secret printed below as the
  manual-entry fallback (secret-only if the terminal is too narrow);
  each step prints what happened (`→ session established`,
  `→ TOTP confirmed`) and the next step, if any.
- **Signup requests / approvals:** an approval flow shows the request
  and its evidence before asking for the verdict — the mirror-before-
  attestation pattern, applied to admin decisions.
- **Revocation:** prints what was revoked *and* what cascaded (user
  revocation cascades to that user's agent tokens — say so, by name).
- **New errors** follow the one-line rule and always name the fix
  (`Error: <what> (<how to fix>)`), including auth errors — a rejected
  login says what to do next, not just "unauthorized".
