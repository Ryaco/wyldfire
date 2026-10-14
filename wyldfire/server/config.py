"""Server configuration."""

from pathlib import Path
import os

DATA_DIR = Path(os.environ.get("WYLD_DATA_DIR", "/data" if Path("/data").exists() else str(Path.home() / ".wyld" / "server")))
DB_PATH = DATA_DIR / "wyld_server.db"
