# Wyldfire — Open Issues

Living list of known issues, spec gaps, and hardening items found during
real-world setup and testing. Pick items from here when there's build
bandwidth. When an item is fixed, move it to the **Fixed** section at the
bottom with the date and commit — don't delete it.

*Started 2026-10-14, after deploying the sync server to GCP and running the
first end-to-end link from a second machine.*

## Open

(none — all caught up as of 2026-10-14)

---

## Fixed

### 2026-10-14 — commit `098da505` ("Fix all 6 issues from docs/ISSUES.md")

**1. No way for a second machine to join an existing project — `wyld clone` missing** [was: high]

`wyld init` generated a fresh `project_id` per machine and the server keys
projects by `project_id`, so two machines could never share a project
through the CLI.

*Fix:* new `wyld clone --server <url> --project <project_id> [directory]`
(`wyldfire/cli/sync.py::clone_cmd`). Clones by project ID, writes
`project_id` + `server_url` into the new local config, and pulls the full
event history. Verified: `--help` shows the command; clone-by-ID is the v1
path (clone-by-name still needs a project-listing endpoint).

**2. `WYLD_AGENT=1` guardrail not implemented** [was: medium]

The spec's agent guardrail (bookkeeping agents may transcribe but never
judge) had zero hits in the codebase.

*Fix:* new `check_agent_guardrail()` in `wyldfire/core/events.py` — raises
`WyldError` when `WYLD_AGENT=1` is set. Called by `gate_service` paths for
attesting scope/slice/plan, excluding stoke evidence, and waiving checks.
Verified behaviorally: `attest-scope` refused under `WYLD_AGENT=1` with
"agent execution refused … requires human judgment", allowed without it.

**3. Hardcoded fallback server token** [was: high — security]

`wyldfire/server/config.py` defined a hardcoded default `SERVER_TOKEN`;
`app.py` fell back to it when `WYLD_SERVER_TOKEN` was unset — and the repo
is public, so the default was public knowledge.

*Fix:* hardcoded default removed. `create_app()` raises `RuntimeError`
("WYLD_SERVER_TOKEN environment variable must be set") at startup when the
env var is missing, with a `MissingTokenApp` fallback. Server fail-fasts
instead of silently running on a known token.

**4. Credentials file is world-readable by default** [was: medium — security]

`wyldfire/core/config.py::save_credential` wrote
`~/.config/wyldfire/credentials` (plaintext tokens) with default umask,
typically `0644`.

*Fix:* `os.chmod(path, 0o600)` on the credentials file, `0o700` on the
config directory, applied on every write.

**5. `wyld link` is confusing when the project has no `server_url`** [was: low — UX]

Bare `wyld link` in a project whose `config.toml` lacked `server_url`
errored with "no server URL provided", which read as a credentials problem
during real setup.

*Fix:* `link_project` now suggests the stored server(s) explicitly
("did you mean --server <url>?") when exactly the URL is what's missing.

**6. `-file` variants for all long-text flags** [was: feature]

Long-form text (flame descriptions, smoke notes) was painful to pass as
CLI args; only stokes had `--notes-file`.

*Fix:* every long-text flag now has a `-file` variant with the identical
stem, mutually exclusive with the inline version — `--desc-file` on
`flame spark` / `ember bank`, `--notes-file` on `smoke log` / `stage` /
`identify` / `clear` and stokes. Plural `--notes-file` kept everywhere;
passing both forms is an error; file contents land inline in the JSONL
event payload (no storage change).
