#!/usr/bin/env python3
"""Rebuild all doctor fixtures under fixtures/. Run from skill root or any cwd."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# allow import of sibling build_fixture
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_fixture import add_skill, base_home, write_skill_md  # noqa: E402

FIX = HERE.parent


def wipe(name: str) -> Path:
    root = FIX / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def build_clean() -> None:
    root = wipe("clean")
    con = base_home(root)
    ssot = root / ".agents" / "skills"
    write_skill_md(ssot, "demo-skill", "Demo")
    add_skill(
        con,
        id="local:demo-skill",
        name="Demo",
        directory="demo-skill",
        content_hash="deadbeef",
    )
    con.commit()
    con.close()


def build_parent_link() -> None:
    root = wipe("parent_link")
    con = base_home(root)
    ssot = root / ".agents" / "skills"
    write_skill_md(ssot, "demo-skill", "Demo")
    add_skill(
        con,
        id="local:demo-skill",
        name="Demo",
        directory="demo-skill",
        content_hash="x",
    )
    con.commit()
    con.close()
    claude_skills = root / ".claude" / "skills"
    shutil.rmtree(claude_skills)
    claude_skills.symlink_to(ssot)


def build_illegal_id() -> None:
    root = wipe("illegal_id")
    con = base_home(root)
    ssot = root / ".agents" / "skills"
    write_skill_md(ssot, "tdd", "TDD")
    add_skill(con, id="tdd", name="TDD", directory="tdd", content_hash="x")
    write_skill_md(ssot, "weird", "Weird")
    add_skill(
        con,
        id="owner/repo:.",
        name="Weird",
        directory="weird",
        repo_owner="owner",
        repo_name="repo",
        content_hash="y",
    )
    write_skill_md(ssot, "nested-leaf", "Nested")
    add_skill(
        con,
        id="owner/repo:skills/nested-leaf",
        name="Nested",
        directory="nested-leaf",
        repo_owner="owner",
        repo_name="repo",
        content_hash="z",
    )
    con.commit()
    con.close()


def build_fat_profiles() -> None:
    root = wipe("fat_profiles")
    con = base_home(root)
    ssot = root / ".agents" / "skills"
    for d, title in (("a", "A"), ("b", "B"), ("c", "C")):
        write_skill_md(ssot, d, title)
    add_skill(
        con,
        id="local:a",
        name="A",
        directory="a",
        enabled_claude=1,
        content_hash="1",
    )
    add_skill(
        con,
        id="local:b",
        name="B",
        directory="b",
        enabled_claude=0,
        content_hash="2",
    )
    add_skill(
        con,
        id="local:c",
        name="C",
        directory="c",
        enabled_claude=0,
        content_hash="3",
    )
    (root / ".claude" / "skills" / "a").symlink_to(ssot / "a")
    con.execute(
        "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
        (
            "p-bound",
            "bound-project",
            json.dumps({"skills": {"claude": ["local:a", "local:b", "local:c"]}}),
        ),
    )
    con.execute(
        "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
        (
            "p-other",
            "other-project",
            json.dumps({"skills": {"claude": ["local:a", "local:b"]}}),
        ),
    )
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        ("current_profile_id_claude", "p-bound"),
    )
    con.commit()
    con.close()


def main() -> None:
    build_clean()
    build_parent_link()
    build_illegal_id()
    build_fat_profiles()
    print("rebuilt:", "clean", "parent_link", "illegal_id", "fat_profiles")


if __name__ == "__main__":
    main()
