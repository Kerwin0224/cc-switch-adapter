#!/usr/bin/env python3
"""Build a minimal fake-home fixture for doctor.py tests. stdlib only."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    directory TEXT NOT NULL,
    repo_owner TEXT,
    repo_name TEXT,
    repo_branch TEXT DEFAULT 'main',
    readme_url TEXT,
    enabled_claude BOOLEAN NOT NULL DEFAULT 0,
    enabled_codex BOOLEAN NOT NULL DEFAULT 0,
    enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
    enabled_grokbuild BOOLEAN NOT NULL DEFAULT 0,
    enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
    enabled_hermes BOOLEAN NOT NULL DEFAULT 0,
    installed_at INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

def base_home(root: Path) -> sqlite3.Connection:
    """Create minimal fake-home layout; return open DB connection."""
    ccs = root / ".cc-switch"
    ccs.mkdir(parents=True, exist_ok=True)
    ssot = root / ".agents" / "skills"
    ssot.mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    settings = {
        "skillStorageLocation": "unified",
        "skillSyncMethod": "symlink",
    }
    (ccs / "settings.json").write_text(json.dumps(settings, indent=2))
    lock = {"version": 3, "skills": {}, "dismissed": {}}
    (root / ".agents" / ".skill-lock.json").write_text(json.dumps(lock, indent=2))
    db = ccs / "cc-switch.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("PRAGMA user_version = 16")
    con.commit()
    return con

def add_skill(con, **kw):
    cols = [
        "id", "name", "description", "directory", "repo_owner", "repo_name",
        "enabled_claude", "enabled_codex", "enabled_gemini", "enabled_grokbuild",
        "enabled_opencode", "enabled_hermes", "content_hash", "installed_at", "updated_at",
    ]
    defaults = {
        "description": "",
        "repo_owner": None,
        "repo_name": None,
        "enabled_claude": 0,
        "enabled_codex": 0,
        "enabled_gemini": 0,
        "enabled_grokbuild": 0,
        "enabled_opencode": 0,
        "enabled_hermes": 0,
        "content_hash": "abc",
        "installed_at": 1,
        "updated_at": 1,
    }
    defaults.update(kw)
    con.execute(
        f"INSERT INTO skills ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [defaults[c] for c in cols],
    )

def write_skill_md(ssot: Path, directory: str, title: str = "Demo") -> None:
    d = ssot / directory
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"# {title}\n")

if __name__ == "__main__":
    print("import me from fixture builders", file=sys.stderr)
    sys.exit(1)
