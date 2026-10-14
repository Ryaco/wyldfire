# Wyldfire — Open Issues

Living list of known issues, spec gaps, and hardening items found during
real-world setup and testing. Pick items from here when there's build
bandwidth. When an item is fixed, move it to the **Fixed** section at the
bottom with the date and commit — don't delete it.

*Started 2026-10-14, after deploying the sync server to GCP and running the
first end-to-end link from a second machine.*

## 1. No way for a second machine to join an existing project — `wyld clone` missing [high]

**What:** `wyld init` generates a fresh `project_id` (UUID) in
`.wyld/config.toml`. The server keys projects by `project_id`
(`POST /api/v1/projects` → `wyldfire/server/db.py::get_or_create_project`).
There is no `wyld clone` / `wyld join` command — the CLI surface is init,
status, snapshot, flame, smoke, ember, fire, gate, wick, template, tester,
metric, login, logout, link, sync, doctor.

**Why it matters:** Two machines that each `init` + `link` create two
separate server-side projects that never merge. The offline-first
multi-machine sync (§13 of `docs/BUILD_SPEC.md`) — the core v1 promise — is
unreachable through the CLI today.

**Workarounds (current):** copy `.wyld/` to the second machine (scp, Drive),
then `login` + `link` + `sync`; or `init`, overwrite `project_id` in
`.wyld/config.toml` with the original project's id, then `link` + `sync`
(pulls the full history down).

**Suggested fix:** `wyld clone --server <url> --project <project_id>` →
creates the local project dir, writes `project_id` + `server_url` into
config, then link + sync (pull). Cloning by *name* needs a project-listing
endpoint, which doesn't exist yet (`GET /api/v1/projects` is not
implemented) — id-based clone is the v1 path.

## 2. `WYLD_AGENT=1` guardrail not implemented [medium]

**What:** `docs/BUILD_SPEC.md` proposes `WYLD_AGENT=1`: when set, the CLI
refuses attestation, waiver, exclusion, and scoring commands — bookkeeping
agents may transcribe but never judge. A repo-wide search for `WYLD_AGENT`
returns zero hits; it was never built.

**Why it matters:** The first agent consumer (playtester-form ingestion by
an assistant) is about to operate against live projects. The
bookkeeping-vs-judgment boundary is currently voluntary.

**Suggested fix:** Check the env var in gate attestation, evidence
exclusion/waiver, and any scoring paths; refuse with a clear error naming
the human-only rule.

## 3. Hardcoded fallback server token [high — security]

**What:** `wyldfire/server/config.py` defines a hardcoded default
`SERVER_TOKEN`; `wyldfire/server/app.py::verify_token` uses
`os.environ.get("WYLD_SERVER_TOKEN", SERVER_TOKEN)`. The repo is public
(GPLv3), so the default token is public knowledge.

**Why it matters:** If the container ever starts without the env var (bad
`.env`, compose misread, manual `uvicorn` run), the server silently
authenticates against a publicly-known token.

**Suggested fix:** Fail fast — raise at startup in `create_app()` if
`WYLD_SERVER_TOKEN` is unset. Remove the hardcoded default entirely.

## 4. Credentials file is world-readable by default [medium — security]

**What:** `wyldfire/core/config.py::save_credential` writes
`~/.config/wyldfire/credentials` via `Path.write_text` with no permission
tightening — typically `0644`. It holds plaintext API tokens.

**Suggested fix:** `os.chmod(path, 0o600)` after write; `0o700` on
`~/.config/wyldfire/`.

## 5. `wyld link` is confusing when the project has no `server_url` [low — UX]

**What:** Running bare `wyld link` in a project whose `config.toml` lacks
`server_url` (e.g. `wyld init` was run without `--server`) errors with "no
server URL provided". During real setup this was misread as a credentials
problem.

**Suggested fix:** If exactly one credential is stored, suggest it
explicitly (`did you mean --server <url>?`) — or use it. Also consider
letting `wyld init --server` be re-runnable to set the URL later.


## 6. `-file` variants for all long-text flags [feature]

**What:** Long-form text (flame descriptions, smoke notes, ember
descriptions) is painful to pass as CLI args. Stokes already support
`--notes "..." | --notes-file PATH` (like `git commit -F`); extend the same
pattern everywhere a long text field exists.

**Convention:** every long-text flag gets a `-file` variant with the
*identical stem*, mutually exclusive with the inline version:

- `wyld flame spark --desc ... | --desc-file PATH`
- `wyld ember bank --desc ... | --desc-file PATH`
- `wyld smoke log` / `stage` / `identify` / `clear` — `--notes ... | --notes-file PATH`
- (stokes already have `--notes ... | --notes-file PATH`)

Keep the plural `--notes-file` everywhere for consistency — do not
introduce a singular `--note-file`.

**Rules:** passing both the inline flag and its `-file` variant is an
error, not "last wins". File contents are read as UTF-8 and stored inline
in the JSONL event payload (no storage-layer change needed).

**Why it matters:** some flames need full design documents, not one-line
descriptions; same for detailed smoke symptoms/diagnoses. Agents and
scripts (e.g. playtester-form ingestion) also need a non-interactive way
to supply long text.

---

## Fixed

(none yet)
