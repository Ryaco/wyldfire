# Wyldfire — Open Issues

Living list of known issues, spec gaps, and hardening items found during
real-world setup and testing. Pick items from here when there's build
bandwidth. When an item is fixed, move it to the **Fixed** section at the
bottom with the date and commit — don't delete it.

*Started 2026-10-14, after deploying the sync server to GCP and running the
first end-to-end link from a second machine.*

(All active issues currently resolved.)

---

## Fixed

### 1. No way for a second machine to join an existing project — `wyld clone` missing [high]
- **Fixed:** 2026-10-14
- **Resolution:** Added `wyld clone --server <url> --project <project_id> [DIRECTORY]` command and `clone_project()` in `sync_service.py`. Initializes project directory, sets `config.toml` (`project_id`, `server_url`, `mode`), links with the remote server, pulls event history, and projects state into SQLite.

### 2. `WYLD_AGENT=1` guardrail not implemented [medium]
- **Fixed:** 2026-10-14
- **Resolution:** Added `check_agent_guardrail` helper in `wyldfire/core/events.py`. Enforced on gate attestations (`attest_scope`, `finish_slice`, `finish_plan`), waivers (`waive_check`), exclusions (`exclude_stoke`), flame crowns (`crown_flame`), and agent self-scoring on stokes (`stoke_flame`, `stoke_fire`). Bookkeeping actions (`smoke log`, `smoke stage`, transcribing external playtests) remain permitted.

### 3. Hardcoded fallback server token [high — security]
- **Fixed:** 2026-10-14
- **Resolution:** Removed `SERVER_TOKEN` fallback from `wyldfire/server/config.py`. Enforced fail-fast `RuntimeError` at startup in `create_app()` if `WYLD_SERVER_TOKEN` is unset.

### 4. Credentials file is world-readable by default [medium — security]
- **Fixed:** 2026-10-14
- **Resolution:** Updated `wyldfire/core/config.py` to enforce `0o700` directory permissions on `~/.config/wyldfire` and `0o600` file permissions on `~/.config/wyldfire/credentials` upon creation and write.

### 5. `wyld link` is confusing when the project has no `server_url` [low — UX]
- **Fixed:** 2026-10-14
- **Resolution:** If a project has no `server_url` and exactly one credential exists in stored credentials, `wyld link` automatically uses it. If multiple exist, clear suggestions are shown. Additionally, `wyld init --server <url>` can now be re-run on an existing project to update `server_url`.

### 6. `-file` variants for all long-text flags [feature]
- **Fixed:** 2026-10-14
- **Resolution:** Implemented `resolve_text_or_file` utility in `wyldfire/core/text_utils.py`. Added `--desc-file` for `wyld flame spark` and `wyld ember bank`, and `--notes-file` for `wyld smoke log`, `stage`, `identify`, `clear`, and `wyld flame version`. Enforced mutual exclusivity (error if both inline and `-file` are passed). File contents are read as UTF-8.
