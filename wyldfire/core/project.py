"""Project detection, initialization, and layout."""

from pathlib import Path
import os
import uuid
from typing import Optional

from wyldfire.core.config import ProjectConfig, register_project
from wyldfire.core.exceptions import ProjectNotFoundError, WyldError


class Project:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        self.wyld_dir = self.root_dir / ".wyld"
        self.events_dir = self.wyld_dir / "events"
        self.snapshots_dir = self.wyld_dir / "snapshots"
        self.migrations_dir = self.wyld_dir / "migrations"
        self.db_path = self.wyld_dir / "wyld.db"
        self.config = ProjectConfig(self.wyld_dir)

    @property
    def name(self) -> str:
        return self.config.get("name", self.root_dir.name)

    @property
    def project_id(self) -> str:
        return self.config.get("project_id", "")

    @property
    def current_fire(self) -> Optional[str]:
        val = self.config.get("checked_out_fire", None)
        return val if val else None

    def set_current_fire(self, fire_name: Optional[str]) -> None:
        self.config.set("checked_out_fire", fire_name or "")
        # Also update is_current in projection DB if it exists
        if self.db_path.exists():
            with self.get_connection() as conn:
                conn.execute("UPDATE fires SET is_current = CASE WHEN name = ? THEN 1 ELSE 0 END", (fire_name or "",))
                conn.commit()

    @property
    def engine(self):
        from wyldfire.core.projection import ProjectionEngine
        return ProjectionEngine(self.db_path)

    @property
    def store(self):
        from wyldfire.core.projection import EventLogStore
        return EventLogStore(self.events_dir, self.engine)

    def get_connection(self):
        """Get SQLite connection, ensuring all event files on disk are projected first."""
        self.store.replay_all()
        return self.engine.get_connection()


def find_project_root(start_dir: Optional[Path] = None) -> Path:
    """Walk up from start_dir (or cwd) to find directory containing .wyld/."""
    current = (start_dir or Path.cwd()).resolve()
    while True:
        if (current / ".wyld").is_dir():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            raise ProjectNotFoundError()
        current = parent


def get_current_project() -> Project:
    """Resolve project from current working directory."""
    root = find_project_root()
    return Project(root)


def init_project(target_dir: Path, name: Optional[str] = None, server_url: Optional[str] = None) -> Project:
    """Initialize a new Wyldfire project in target_dir."""
    target_dir = target_dir.resolve()
    wyld_dir = target_dir / ".wyld"
    
    if wyld_dir.exists():
        raise WyldError(
            f"project already initialized at {target_dir}",
            "cd to the directory and run 'wyld status'"
        )

    # Create directory structure
    events_dir = wyld_dir / "events"
    snapshots_dir = wyld_dir / "snapshots"
    migrations_dir = wyld_dir / "migrations"

    events_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    proj_name = name or target_dir.name
    proj_id = str(uuid.uuid4())

    # Write initial config
    config = ProjectConfig(wyld_dir)
    config.set("project_id", proj_id)
    config.set("name", proj_name)
    if server_url:
        config.set("server_url", server_url.rstrip("/"))
    config.set("mode", "offline-first")

    # Ensure .gitignore in project root ignores .wyld/ wholesale
    gitignore_path = target_dir / ".gitignore"
    entry = "\n# Wyldfire process & decision layer\n.wyld/\n"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if ".wyld/" not in content and ".wyld" not in content:
            gitignore_path.write_text(content.rstrip() + entry, encoding="utf-8")
    else:
        gitignore_path.write_text(entry.lstrip(), encoding="utf-8")

    # Register in global registry
    register_project(target_dir, proj_name)

    return Project(target_dir)
