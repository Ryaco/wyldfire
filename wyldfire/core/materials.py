"""Materials directory hashing and drift detection."""

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple
import pathspec


BUILTIN_IGNORES = [".DS_Store", "Thumbs.db", "desktop.ini"]


def get_effective_ignore_patterns(project_root: Path) -> List[str]:
    """Get list of ignore patterns from built-ins and .wyldignore."""
    patterns = list(BUILTIN_IGNORES)
    wyldignore_path = project_root / ".wyldignore"
    if wyldignore_path.exists():
        content = wyldignore_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def spec_from_patterns(patterns: List[str]) -> pathspec.PathSpec:
    """Create a PathSpec object from a list of patterns."""
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def load_wyldignore(project_root: Path) -> pathspec.PathSpec:
    """Load .wyldignore from project root (full gitignore-style via pathspec).
    
    Built-in defaults (.DS_Store, Thumbs.db, desktop.ini) are always applied.
    Returns a pathspec.PathSpec object.
    """
    return spec_from_patterns(get_effective_ignore_patterns(project_root))


def hash_ignore_patterns(patterns: List[str]) -> str:
    """Produce a stable hash of the effective ignore pattern list."""
    patterns_str = "\n".join(sorted(patterns))
    return hashlib.sha256(patterns_str.encode("utf-8")).hexdigest()


def hash_ignore_spec(spec: pathspec.PathSpec) -> str:
    """Produce a stable hash of the effective ignore pattern list."""
    patterns_str = "\n".join(sorted(str(p.pattern) for p in spec.patterns))
    return hashlib.sha256(patterns_str.encode("utf-8")).hexdigest()


def compute_materials_hash(materials_path: Path, spec: pathspec.PathSpec) -> str:
    """SHA-256 over sorted (rel_path, content) pairs, CRLF normalized.
    
    Raises FileNotFoundError if materials_path does not exist.
    Raises ValueError if materials_path is not a directory.
    """
    if not materials_path.exists():
        raise FileNotFoundError(f"Materials path not found: {materials_path}")
    if not materials_path.is_dir():
        raise ValueError(f"Materials path is not a directory: {materials_path}")

    entries: List[Tuple[str, bytes]] = []
    for root, dirs, files in os.walk(materials_path):
        # Prune ignored dirs in-place to avoid descending
        pruned_dirs = []
        for d in dirs:
            rel_d = (Path(root, d).relative_to(materials_path)).as_posix()
            if spec.match_file(rel_d) or spec.match_file(rel_d + "/"):
                continue
            pruned_dirs.append(d)
        dirs[:] = pruned_dirs

        for fname in files:
            abs_path = Path(root) / fname
            rel_path = (abs_path.relative_to(materials_path)).as_posix()
            if spec.match_file(rel_path):
                continue
            content = abs_path.read_bytes()
            # Normalize CRLF → LF
            content = content.replace(b"\r\n", b"\n")
            entries.append((rel_path, content))

    # Sort by relative path for stable ordering
    entries.sort(key=lambda x: x[0])

    h = hashlib.sha256()
    for rel_path, content in entries:
        h.update(rel_path.encode("utf-8"))
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    return h.hexdigest()


def find_drifted_flames(project) -> List[dict]:
    """Return list of {name, materials_path, last_version_n} for drifted flames."""
    drifted = []
    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.name, f.materials_path,
                   fv.n as last_n, fv.materials_hash as recorded_hash,
                   fv.materials_ignore_hash, fv.ignore_patterns_json
            FROM flames f
            JOIN flame_versions fv ON fv.flame_id = f.id
            WHERE f.materials_path IS NOT NULL AND f.materials_path != ''
              AND fv.materials_hash IS NOT NULL AND fv.materials_hash != ''
              AND fv.n = (SELECT max(n) FROM flame_versions WHERE flame_id = f.id)
              AND f.state NOT IN ('doused', 'crowned')
            """
        ).fetchall()

    for row in rows:
        mat_path = Path(row["materials_path"])
        if not mat_path.is_absolute():
            mat_path = project.root_dir / mat_path
        if not mat_path.exists():
            continue
        try:
            ignore_json = row["ignore_patterns_json"]
            patterns = json.loads(ignore_json) if ignore_json else []
            if patterns:
                spec = spec_from_patterns(patterns)
            else:
                spec = load_wyldignore(project.root_dir)
            current_hash = compute_materials_hash(mat_path, spec)
        except Exception:
            continue
        if current_hash != row["recorded_hash"]:
            drifted.append({
                "name": row["name"],
                "materials_path": row["materials_path"],
                "last_version_n": row["last_n"],
            })
    return drifted
