"""Tests for materials drift detection, hashing, and flame fork."""

import pytest
from pathlib import Path
from wyldfire.services import flame_service
from wyldfire.core.exceptions import WyldError


def _write_material(project, rel_path: str, content: str = "data"):
    """Helper to write a file into the project root."""
    p = project.root_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_materials_hash_stable(temp_project):
    """Same dir, same content → same hash."""
    from wyldfire.core.materials import compute_materials_hash, load_wyldignore
    _write_material(temp_project, "materials/test/card.txt", "card content")
    spec = load_wyldignore(temp_project.root_dir)
    h1 = compute_materials_hash(temp_project.root_dir / "materials/test", spec)
    h2 = compute_materials_hash(temp_project.root_dir / "materials/test", spec)
    assert h1 == h2


def test_materials_hash_crlf_normalized(temp_project):
    """CRLF and LF produce the same hash."""
    from wyldfire.core.materials import compute_materials_hash, load_wyldignore
    spec = load_wyldignore(temp_project.root_dir)

    p1 = temp_project.root_dir / "m1"
    p1.mkdir()
    (p1 / "file.txt").write_bytes(b"hello\r\nworld\r\n")

    p2 = temp_project.root_dir / "m2"
    p2.mkdir()
    (p2 / "file.txt").write_bytes(b"hello\nworld\n")

    assert compute_materials_hash(p1, spec) == compute_materials_hash(p2, spec)


def test_materials_wyldignore_respected(temp_project):
    """Files matching .wyldignore are excluded from hash."""
    from wyldfire.core.materials import compute_materials_hash, load_wyldignore

    mat = temp_project.root_dir / "materials/test"
    mat.mkdir(parents=True)
    (mat / "card.txt").write_text("data")

    spec_without = load_wyldignore(temp_project.root_dir)
    h_without_ignore_file = compute_materials_hash(mat, spec_without)

    # .DS_Store is a builtin ignore
    (mat / ".DS_Store").write_text("mac junk")

    spec_with = load_wyldignore(temp_project.root_dir)
    h_with = compute_materials_hash(mat, spec_with)

    assert h_with == h_without_ignore_file

    # Now add custom pattern to .wyldignore
    (temp_project.root_dir / ".wyldignore").write_text("*.tmp\nbuild/\n")
    spec_custom = load_wyldignore(temp_project.root_dir)
    (mat / "scratch.tmp").write_text("temporary scratch")

    h_custom = compute_materials_hash(mat, spec_custom)
    assert h_custom == h_without_ignore_file


def test_stoke_no_materials_no_drift(temp_project):
    """Flame without materials path: stoke works normally."""
    flame_service.spark_flame(temp_project, "basic")
    flame_service.version_flame(temp_project, "basic", notes="v2 changes")
    res = flame_service.stoke_flame(temp_project, "basic", notes="played it")
    assert res["target_name"] == "basic"


def test_stoke_blocks_on_drift(temp_project):
    """Stoke blocks when materials have drifted since last version."""
    mat = temp_project.root_dir / "materials/combat"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("original rules")

    flame_service.spark_flame(temp_project, "combat", materials="materials/combat")
    flame_service.version_flame(temp_project, "combat", notes="v2")

    # Change materials without versioning
    (mat / "rules.txt").write_text("CHANGED rules")

    # Stoke should be blocked
    with pytest.raises(WyldError) as exc_info:
        flame_service.stoke_flame(temp_project, "combat", notes="playtest")
    err_str = str(exc_info.value).lower()
    assert "blocked" in err_str and "combat" in err_str


def test_stoke_for_version_bypasses_drift(temp_project):
    """--for vN bypasses drift check entirely."""
    mat = temp_project.root_dir / "materials/combat"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("original rules")

    flame_service.spark_flame(temp_project, "combat", materials="materials/combat")
    flame_service.version_flame(temp_project, "combat", notes="v2")

    # Change materials (working on v3)
    (mat / "rules.txt").write_text("CHANGED rules toward v3")

    # Playtest report for v2 arrives — use --for
    res = flame_service.stoke_flame(temp_project, "combat", notes="v2 playtest", for_version=2)
    assert res["pinned_version_n"] == 2
    assert res["version"] == 2


def test_version_path_must_exist(temp_project):
    """version_flame with non-existent --materials path errors."""
    flame_service.spark_flame(temp_project, "ghost")
    with pytest.raises(WyldError):
        flame_service.version_flame(temp_project, "ghost", notes="v2", materials="nonexistent/path")


def test_flame_materials_reverse_lookup(temp_project):
    """wyld flame materials reverse-lookup finds matching versions."""
    mat = temp_project.root_dir / "materials/combat"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("rules v1")

    flame_service.spark_flame(temp_project, "combat", materials="materials/combat")
    flame_service.version_flame(temp_project, "combat", notes="v2 iteration")

    matches = flame_service.get_flame_materials(temp_project, "combat")
    assert any(m["n"] >= 1 for m in matches)


def test_flame_fork_creates_new_flame(temp_project):
    """Fork creates new flame with forked_from set and fresh history."""
    mat = temp_project.root_dir / "materials/mana"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("mana rules")

    flame_service.spark_flame(temp_project, "mana", desc="mana system", materials="materials/mana")
    flame_service.version_flame(temp_project, "mana", notes="v2 polish")

    res = flame_service.fork_flame(temp_project, "cooldowns", source="mana")
    assert res["name"] == "cooldowns"
    assert "mana@v2" in res["forked_from"]

    # New flame exists with fresh history
    forked = flame_service.get_flame(temp_project, "cooldowns")
    assert forked is not None
    assert "mana@v2" in (forked.get("forked_from") or "")
    assert len(forked["versions"]) == 1


def test_flame_fork_copies_materials(temp_project):
    """Fork copies source materials to dest dir."""
    mat = temp_project.root_dir / "materials/mana"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("mana rules")

    flame_service.spark_flame(temp_project, "mana", materials="materials/mana")
    flame_service.version_flame(temp_project, "mana", notes="v2")

    flame_service.fork_flame(temp_project, "cooldowns", source="mana")

    # materials/cooldowns should exist with copied content
    dest = temp_project.root_dir / "materials/cooldowns"
    assert dest.exists()
    assert (dest / "rules.txt").exists()
    assert (dest / "rules.txt").read_text() == "mana rules"

    # Source untouched
    assert (mat / "rules.txt").read_text() == "mana rules"


def test_flame_fork_error_on_nonempty_dest(temp_project):
    """Fork errors if destination dir exists and is non-empty."""
    mat = temp_project.root_dir / "materials/mana"
    mat.mkdir(parents=True)
    (mat / "rules.txt").write_text("mana rules")

    flame_service.spark_flame(temp_project, "mana", materials="materials/mana")

    # Pre-create non-empty dest
    dest = temp_project.root_dir / "materials/cooldowns"
    dest.mkdir(parents=True)
    (dest / "existing.txt").write_text("existing content")

    with pytest.raises(WyldError):
        flame_service.fork_flame(temp_project, "cooldowns", source="mana")


def test_flame_rename(temp_project):
    """rename_flame updates name; old name gone, stokes transfer."""
    flame_service.spark_flame(temp_project, "mana")
    flame_service.stoke_flame(temp_project, "mana", notes="first stoke")

    res = flame_service.rename_flame(temp_project, "mana", "cooldowns")
    assert res["old_name"] == "mana"
    assert res["new_name"] == "cooldowns"

    # Old name gone
    with pytest.raises(WyldError):
        flame_service.get_flame(temp_project, "mana")

    # New name works and has the stoke
    renamed = flame_service.get_flame(temp_project, "cooldowns")
    assert renamed["name"] == "cooldowns"
    assert len(renamed["stokes"]) == 1


def test_flame_rename_conflict(temp_project):
    """rename_flame errors if new name already exists."""
    flame_service.spark_flame(temp_project, "mana")
    flame_service.spark_flame(temp_project, "cooldowns")

    with pytest.raises(WyldError):
        flame_service.rename_flame(temp_project, "mana", "cooldowns")
