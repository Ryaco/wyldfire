"""Event projection engine: replays event log into disposable SQLite database."""

from pathlib import Path
import json
import sqlite3
from typing import Any, List, Optional
import os

from wyldfire.core.events import Event
from wyldfire.core.schema import SCHEMA_SQL
from wyldfire.core.constants import (
    PHASE_PROTOTYPE,
    PHASE_GATE_PART1,
    PHASE_GATE_PART2,
    PHASE_GATE_PART3,
    PHASE_PRODUCTION,
    PHASE_SHIPPED,
    FLAME_SPARKED,
    FLAME_BURNING,
    FLAME_TESTED,
    FLAME_CROWNED,
    FLAME_DOUSED,
    SMOKE_STAGED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    SMOKE_CLEARED,
    FUEL_QUEUED,
    FUEL_CREATING,
    FUEL_FINISHED,
    EMBER_BANKED,
    EMBER_KINDLED,
    EMBER_DISMISSED,
)


class ProjectionEngine:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def is_applied(self, event_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM applied_events WHERE id = ?", (event_id,))
            return cursor.fetchone() is not None

    def apply_event(self, event: Event) -> bool:
        """Apply a single event to the SQLite database. Idempotent by UUID."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM applied_events WHERE id = ?", (event.id,))
            if cursor.fetchone() is not None:
                return False  # Already applied

            cursor.execute(
                "INSERT INTO applied_events (id, ts, type, actor) VALUES (?, ?, ?, ?)",
                (event.id, event.ts, event.type, event.actor),
            )
            self._dispatch_event(conn, event)
            conn.commit()
            return True

    def _dispatch_event(self, conn: sqlite3.Connection, event: Event) -> None:
        p = event.payload
        t = event.type
        ts = event.ts

        # Flame events
        if t == "flame.sparked":
            name = p["name"]
            desc = p.get("description", "")
            cursor = conn.execute(
                "INSERT INTO flames (name, description, state, created_at) VALUES (?, ?, ?, ?)",
                (name, desc, FLAME_SPARKED, ts),
            )
            flame_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO flame_versions (flame_id, n, notes, created_at) VALUES (?, ?, ?, ?)",
                (flame_id, 1, "Initial spark", ts),
            )

        elif t == "flame.versioned":
            name = p["name"]
            notes = p.get("notes", "")
            row = conn.execute("SELECT id, state FROM flames WHERE name = ?", (name,)).fetchone()
            if row:
                flame_id, state = row["id"], row["state"]
                max_row = conn.execute(
                    "SELECT coalesce(max(n), 0) as max_n FROM flame_versions WHERE flame_id = ?",
                    (flame_id,),
                ).fetchone()
                next_n = (max_row["max_n"] if max_row else 0) + 1
                conn.execute(
                    "INSERT INTO flame_versions (flame_id, n, notes, created_at) VALUES (?, ?, ?, ?)",
                    (flame_id, next_n, notes, ts),
                )
                if next_n >= 2 and state == FLAME_SPARKED:
                    conn.execute("UPDATE flames SET state = ? WHERE id = ?", (FLAME_BURNING, flame_id))

        elif t == "flame.crowned":
            conn.execute("UPDATE flames SET state = ? WHERE name = ?", (FLAME_CROWNED, p["name"]))

        elif t == "flame.doused":
            conn.execute("UPDATE flames SET state = ? WHERE name = ?", (FLAME_DOUSED, p["name"]))

        # Tester events
        elif t == "tester.noted":
            conn.execute(
                "INSERT INTO testers (name, note) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET note = excluded.note",
                (p["name"], p.get("note", "")),
            )

        # Metric events
        elif t == "metric.defined":
            conn.execute(
                "INSERT INTO metrics (name, prompt, type, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET prompt = excluded.prompt, type = excluded.type",
                (p["name"], p["prompt"], p.get("type", "text"), ts),
            )
        elif t == "metric.removed":
            conn.execute("DELETE FROM metrics WHERE name = ?", (p["name"],))

        # Stoke events
        elif t == "stoke.logged":
            target_kind = p["target_kind"]
            target_name = p["target_name"]
            tester = p.get("tester", "dev")
            notes = p.get("notes", "")
            flame_version_id = None

            if target_kind == "flame":
                flame_row = conn.execute("SELECT id, state FROM flames WHERE name = ?", (target_name,)).fetchone()
                if flame_row:
                    target_id = flame_row["id"]
                    # Mark flame as tested if sparked or burning
                    if flame_row["state"] in (FLAME_SPARKED, FLAME_BURNING):
                        conn.execute("UPDATE flames SET state = ? WHERE id = ?", (FLAME_TESTED, target_id))
                    # Get latest version id
                    v_row = conn.execute(
                        "SELECT id FROM flame_versions WHERE flame_id = ? ORDER BY n DESC LIMIT 1",
                        (target_id,),
                    ).fetchone()
                    if v_row:
                        flame_version_id = v_row["id"]
                else:
                    target_id = 0
            else:
                fire_row = conn.execute("SELECT id FROM fires WHERE name = ?", (target_name,)).fetchone()
                target_id = fire_row["id"] if fire_row else 0

            cur = conn.execute(
                "INSERT INTO stokes (target_kind, target_id, flame_version_id, tester, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (target_kind, target_id, flame_version_id, tester, notes, ts),
            )
            stoke_id = cur.lastrowid

            # Metrics
            for m_name, m_val in p.get("metrics", {}).items():
                val_text = str(m_val)
                val_num = None
                try:
                    val_num = float(m_val)
                except (ValueError, TypeError):
                    pass
                conn.execute(
                    "INSERT INTO stoke_metrics (stoke_id, metric_name, value_text, value_num) VALUES (?, ?, ?, ?)",
                    (stoke_id, m_name, val_text, val_num),
                )

            # Commit staged smoke
            for sm_id in p.get("staged_smoke_ids", []):
                conn.execute(
                    "UPDATE smoke SET status = ?, stoke_id = ? WHERE id = ? AND status = ?",
                    (SMOKE_OPEN, stoke_id, sm_id, SMOKE_STAGED),
                )
                conn.execute(
                    "INSERT INTO smoke_transitions (smoke_id, to_status, note, created_at) VALUES (?, ?, ?, ?)",
                    (sm_id, SMOKE_OPEN, f"Committed by stoke #{stoke_id}", ts),
                )

        elif t == "stoke.excluded":
            stoke_id = p["stoke_id"]
            reason = p["reason"]
            fire_name = p.get("fire")
            conn.execute("UPDATE stokes SET excluded = 1, exclude_reason = ? WHERE id = ?", (reason, stoke_id))
            if fire_name:
                f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (fire_name,)).fetchone()
                if f_row:
                    conn.execute(
                        "INSERT INTO gate_overrides (fire_id, check_name, kind, ref_id, reason, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (f_row["id"], "playtest", "exclude-stoke", stoke_id, reason, ts),
                    )

        # Smoke events
        elif t == "smoke.staged":
            sm_id = p.get("id")
            title = p["title"]
            ctx_kind = p["context_kind"]
            ctx_ref = p.get("context_ref", "")
            sev = int(p.get("severity", 2))
            tags = p.get("tags", "")
            if sm_id:
                conn.execute(
                    "INSERT INTO smoke (id, title, context_kind, context_ref, severity, status, tags, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sm_id, title, ctx_kind, ctx_ref, sev, SMOKE_STAGED, tags, ts),
                )
            else:
                conn.execute(
                    "INSERT INTO smoke (title, context_kind, context_ref, severity, status, tags, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (title, ctx_kind, ctx_ref, sev, SMOKE_STAGED, tags, ts),
                )

        elif t == "smoke.opened":
            sm_id = p.get("id")
            title = p["title"]
            ctx_kind = p["context_kind"]
            ctx_ref = p.get("context_ref", "")
            sev = int(p.get("severity", 2))
            tags = p.get("tags", "")
            note = p.get("note", title)
            if sm_id:
                cur = conn.execute(
                    "INSERT INTO smoke (id, title, context_kind, context_ref, severity, status, tags, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sm_id, title, ctx_kind, ctx_ref, sev, SMOKE_OPEN, tags, ts),
                )
                actual_id = sm_id
            else:
                cur = conn.execute(
                    "INSERT INTO smoke (title, context_kind, context_ref, severity, status, tags, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (title, ctx_kind, ctx_ref, sev, SMOKE_OPEN, tags, ts),
                )
                actual_id = cur.lastrowid
            conn.execute(
                "INSERT INTO smoke_transitions (smoke_id, to_status, note, created_at) VALUES (?, ?, ?, ?)",
                (actual_id, SMOKE_OPEN, note, ts),
            )

        elif t == "smoke.unstaged":
            conn.execute("DELETE FROM smoke WHERE id = ? AND status = ?", (p["id"], SMOKE_STAGED))

        elif t == "smoke.identified":
            sm_id = p["id"]
            note = p["note"]
            conn.execute("UPDATE smoke SET status = ? WHERE id = ?", (SMOKE_IDENTIFIED, sm_id))
            conn.execute(
                "INSERT INTO smoke_transitions (smoke_id, to_status, note, created_at) VALUES (?, ?, ?, ?)",
                (sm_id, SMOKE_IDENTIFIED, note, ts),
            )

        elif t == "smoke.cleared":
            sm_id = p["id"]
            note = p["note"]
            conn.execute("UPDATE smoke SET status = ? WHERE id = ?", (SMOKE_CLEARED, sm_id))
            conn.execute(
                "INSERT INTO smoke_transitions (smoke_id, to_status, note, created_at) VALUES (?, ?, ?, ?)",
                (sm_id, SMOKE_CLEARED, note, ts),
            )

        elif t == "smoke.tagged":
            sm_id = p["id"]
            conn.execute("UPDATE smoke SET tags = ? WHERE id = ?", (p["tags"], sm_id))

        # Ember events
        elif t == "ember.banked":
            em_id = p.get("id")
            title = p["title"]
            note = p.get("note", "")
            kind = p.get("kind", "content")
            if em_id:
                conn.execute(
                    "INSERT INTO embers (id, title, note, kind, state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (em_id, title, note, kind, EMBER_BANKED, ts),
                )
            else:
                conn.execute(
                    "INSERT INTO embers (title, note, kind, state, created_at) VALUES (?, ?, ?, ?, ?)",
                    (title, note, kind, EMBER_BANKED, ts),
                )

        elif t == "ember.kindled":
            conn.execute(
                "UPDATE embers SET state = ?, state_note = ? WHERE id = ?",
                (EMBER_KINDLED, p.get("note", ""), p["id"]),
            )

        elif t == "ember.dismissed":
            conn.execute(
                "UPDATE embers SET state = ?, state_note = ? WHERE id = ?",
                (EMBER_DISMISSED, p.get("note", ""), p["id"]),
            )

        elif t == "ember.kind_set":
            conn.execute(
                "UPDATE embers SET kind = ?, state_note = ? WHERE id = ?",
                (p["kind"], p.get("note", ""), p["id"]),
            )

        # Fire events
        elif t == "fire.started":
            name = p["name"]
            desc = p.get("description", "")
            flames = p.get("flames", [])
            cur = conn.execute(
                "INSERT INTO fires (name, description, phase, created_at) VALUES (?, ?, ?, ?)",
                (name, desc, PHASE_PROTOTYPE, ts),
            )
            fire_id = cur.lastrowid
            conn.execute(
                "INSERT INTO gate_config (fire_id, min_stokes, blocked_severity) VALUES (?, 3, 2)",
                (fire_id,),
            )
            for fl_name in flames:
                fl_row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_name,)).fetchone()
                if fl_row:
                    conn.execute(
                        "INSERT OR IGNORE INTO fire_flames (fire_id, flame_id, added_at) VALUES (?, ?, ?)",
                        (fire_id, fl_row["id"], ts),
                    )

        elif t == "fire.flames_added":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["name"],)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                for fl_name in p.get("flames", []):
                    fl_row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_name,)).fetchone()
                    if fl_row:
                        conn.execute(
                            "INSERT OR IGNORE INTO fire_flames (fire_id, flame_id, added_at) VALUES (?, ?, ?)",
                            (fire_id, fl_row["id"], ts),
                        )

        elif t == "fire.flames_removed":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["name"],)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                for fl_name in p.get("flames", []):
                    fl_row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_name,)).fetchone()
                    if fl_row:
                        conn.execute(
                            "DELETE FROM fire_flames WHERE fire_id = ? AND flame_id = ?",
                            (fire_id, fl_row["id"]),
                        )

        elif t == "fire.loop_set":
            conn.execute("UPDATE fires SET core_loop = ? WHERE name = ?", (p["core_loop"], p["name"]))

        elif t == "fire.toy_added":
            name = p["name"]
            toy = p["toy"]
            row = conn.execute("SELECT toys_json FROM fires WHERE name = ?", (name,)).fetchone()
            if row:
                try:
                    toys = json.loads(row["toys_json"])
                except Exception:
                    toys = []
                if toy not in toys:
                    toys.append(toy)
                conn.execute("UPDATE fires SET toys_json = ? WHERE name = ?", (json.dumps(toys), name))

        elif t == "fire.shipped":
            conn.execute("UPDATE fires SET phase = ? WHERE name = ?", (PHASE_SHIPPED, p["name"]))

        # Gate events
        elif t == "gate.scope_attested":
            conn.execute(
                "UPDATE fires SET scope_attested_at = ?, scope_attest_note = ? WHERE name = ?",
                (ts, p.get("note", ""), p["fire"]),
            )

        elif t == "gate.config_set":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                min_s = p.get("min_stokes")
                bl_sev = p.get("blocked_severity")
                if min_s is not None:
                    conn.execute("UPDATE gate_config SET min_stokes = ? WHERE fire_id = ?", (min_s, f_row["id"]))
                if bl_sev is not None:
                    conn.execute("UPDATE gate_config SET blocked_severity = ? WHERE fire_id = ?", (bl_sev, f_row["id"]))

        elif t == "gate.check_waived":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                conn.execute(
                    "INSERT INTO gate_overrides (fire_id, check_name, kind, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f_row["id"], p["check_name"], "waive", p["reason"], ts),
                )

        elif t == "gate.slice_set":
            bundles = p.get("bundles", [])
            conn.execute(
                "UPDATE fires SET slice_bundles_json = ? WHERE name = ?",
                (json.dumps(bundles), p["fire"]),
            )

        elif t == "gate.slice_done":
            conn.execute("UPDATE fires SET phase = ? WHERE name = ?", (PHASE_GATE_PART3, p["fire"]))

        elif t == "gate.plan_done":
            conn.execute("UPDATE fires SET phase = ? WHERE name = ?", (PHASE_PRODUCTION, p["fire"]))

        elif t == "gate.part1.passed":
            fire_name = p["fire"]
            is_lap = p.get("is_lap", False)
            lap_no = p.get("lap_no")
            pinned_versions = p.get("pinned_versions", {})
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (fire_name,)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                new_phase = PHASE_PRODUCTION if is_lap else PHASE_GATE_PART2
                conn.execute("UPDATE fires SET phase = ? WHERE id = ?", (new_phase, fire_id))
                conn.execute(
                    "INSERT INTO gate_verdicts (fire_id, kind, lap_no, verdict, reasons_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fire_id, "lap" if is_lap else "initial", lap_no, "pass", "[]", ts),
                )
                for fl_name, ver in pinned_versions.items():
                    fl_row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_name,)).fetchone()
                    if fl_row:
                        conn.execute(
                            "UPDATE fire_flames SET pinned_version = ? WHERE fire_id = ? AND flame_id = ?",
                            (ver, fire_id, fl_row["id"]),
                        )

        elif t == "gate.part1.held":
            fire_name = p["fire"]
            is_lap = p.get("is_lap", False)
            lap_no = p.get("lap_no")
            reasons = p.get("reasons", [])
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (fire_name,)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                if not is_lap:
                    conn.execute("UPDATE fires SET phase = ? WHERE id = ?", (PHASE_PROTOTYPE, fire_id))
                conn.execute(
                    "INSERT INTO gate_verdicts (fire_id, kind, lap_no, verdict, reasons_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fire_id, "lap" if is_lap else "initial", lap_no, "hold", json.dumps(reasons), ts),
                )

        # Wick events
        elif t == "wick.bundle_added":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                parent_id = None
                if p.get("parent"):
                    p_row = conn.execute(
                        "SELECT id FROM wick_bundles WHERE fire_id = ? AND name = ?",
                        (fire_id, p["parent"]),
                    ).fetchone()
                    if p_row:
                        parent_id = p_row["id"]
                pos = p.get("position")
                if pos is None:
                    max_pos = conn.execute(
                        "SELECT coalesce(max(position), 0) as m FROM wick_bundles WHERE fire_id = ? AND (parent_id IS ?)",
                        (fire_id, parent_id),
                    ).fetchone()["m"]
                    pos = max_pos + 1
                conn.execute(
                    "INSERT INTO wick_bundles (fire_id, parent_id, name, metadata_json, position, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fire_id, parent_id, p["name"], json.dumps(p.get("metadata", {})), pos, ts),
                )

        elif t == "wick.bundle_defined":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                fire_id = f_row["id"]
                b_row = conn.execute(
                    "SELECT id, metadata_json FROM wick_bundles WHERE fire_id = ? AND name = ?",
                    (fire_id, p["name"]),
                ).fetchone()
                if b_row:
                    try:
                        meta = json.loads(b_row["metadata_json"])
                    except Exception:
                        meta = {}
                    meta.update(p.get("metadata", {}))
                    conn.execute(
                        "UPDATE wick_bundles SET metadata_json = ? WHERE id = ?",
                        (json.dumps(meta), b_row["id"]),
                    )

        elif t == "wick.bundle_cut":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                conn.execute(
                    "UPDATE wick_bundles SET cut = 1, cut_reason = ? WHERE fire_id = ? AND name = ?",
                    (p.get("reason", ""), f_row["id"], p["name"]),
                )

        elif t == "wick.fuel_added":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                b_row = conn.execute(
                    "SELECT id FROM wick_bundles WHERE fire_id = ? AND name = ?",
                    (f_row["id"], p["bundle"]),
                ).fetchone()
                if b_row:
                    conn.execute(
                        "INSERT INTO wick_fuel (bundle_id, name, fuel_kind, type_tag, note, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            b_row["id"],
                            p["name"],
                            p.get("fuel_kind", "task"),
                            p.get("type_tag", ""),
                            p.get("note", ""),
                            ts,
                        ),
                    )

        elif t == "wick.fuel_started":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                conn.execute(
                    "UPDATE wick_fuel SET state = ? WHERE name = ? AND bundle_id IN "
                    "(SELECT id FROM wick_bundles WHERE fire_id = ?)",
                    (FUEL_CREATING, p["fuel"], f_row["id"]),
                )

        elif t == "wick.fuel_finished":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                note = p.get("note")
                if note:
                    conn.execute(
                        "UPDATE wick_fuel SET state = ?, finished_at = ?, note = ? WHERE name = ? AND bundle_id IN "
                        "(SELECT id FROM wick_bundles WHERE fire_id = ?)",
                        (FUEL_FINISHED, ts, note, p["fuel"], f_row["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE wick_fuel SET state = ?, finished_at = ? WHERE name = ? AND bundle_id IN "
                        "(SELECT id FROM wick_bundles WHERE fire_id = ?)",
                        (FUEL_FINISHED, ts, p["fuel"], f_row["id"]),
                    )

        elif t == "wick.time_logged":
            f_row = conn.execute("SELECT id FROM fires WHERE name = ?", (p["fire"],)).fetchone()
            if f_row:
                mins = int(p.get("minutes", 0))
                conn.execute(
                    "UPDATE wick_fuel SET time_min = time_min + ? WHERE name = ? AND bundle_id IN "
                    "(SELECT id FROM wick_bundles WHERE fire_id = ?)",
                    (mins, p["fuel"], f_row["id"]),
                )

        # Template events
        elif t == "template.created":
            conn.execute(
                "INSERT INTO templates (name, definition_json) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET definition_json = excluded.definition_json",
                (p["name"], json.dumps(p["definition"])),
            )

        elif t == "template.deleted":
            conn.execute("DELETE FROM templates WHERE name = ?", (p["name"],))


class EventLogStore:
    def __init__(self, events_dir: Path, projection: ProjectionEngine):
        self.events_dir = events_dir
        self.projection = projection

    def list_event_files(self) -> List[Path]:
        """List all event files in sorted order."""
        if not self.events_dir.exists():
            return []
        files = list(self.events_dir.glob("*.json"))
        # Sort by filename which starts with YYYYMMDDTHHMMSS
        files.sort(key=lambda p: p.name)
        return files

    def read_event_from_file(self, path: Path) -> Event:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return Event.from_dict(data)

    def append_event(self, event: Event) -> Path:
        """Write event file and immediately project to SQLite."""
        self.events_dir.mkdir(parents=True, exist_ok=True)
        filename = event.filename()
        event_path = self.events_dir / filename
        # In case of filename clash, append suffix
        idx = 1
        while event_path.exists():
            base = filename.rsplit(".", 1)[0]
            event_path = self.events_dir / f"{base}_{idx}.json"
            idx += 1

        event_path.write_text(json.dumps(event.to_dict(), indent=2), encoding="utf-8")
        self.projection.apply_event(event)
        return event_path

    def replay_all(self, force: bool = False) -> int:
        """Replay all event files into projection.
        
        If force=True, removes the DB and rebuilds from scratch.
        Returns count of newly applied events.
        """
        if force and self.projection.db_path.exists():
            self.projection.db_path.unlink()
            self.projection._init_db()

        applied_count = 0
        for path in self.list_event_files():
            try:
                event = self.read_event_from_file(path)
                if self.projection.apply_event(event):
                    applied_count += 1
            except Exception:
                # Log or ignore corrupted file
                pass
        return applied_count
