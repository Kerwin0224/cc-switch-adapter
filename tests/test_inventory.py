#!/usr/bin/env python3
"""Inventory-seam tests for inventory.py (stdlib unittest).

Covers: full scan table, non-trio live seam, trio drift seam, and the
--profile slot-vs-live diff (live / slot-only / dangling). The fixture home
is never mutated by the run (read-only seam).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "inventory.py"
LIB = ROOT / "fixtures" / "lib"
sys.path.insert(0, str(LIB))
from build_fixture import base_home, add_skill, write_skill_md  # noqa: E402


def run_inventory(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(INVENTORY), "--root", str(root)]
    cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def build_home(root: Path) -> None:
    con = base_home(root)
    ssot = root / ".agents" / "skills"
    for directory in ("alpha", "beta", "gamma", "delta"):
        write_skill_md(ssot, directory, directory)
    add_skill(con, id="local:alpha", name="Alpha", directory="alpha",
              enabled_claude=1, enabled_codex=1, enabled_opencode=1)
    add_skill(con, id="owner/repo:skills/beta", name="Beta", directory="beta",
              enabled_claude=1, enabled_codex=1)
    add_skill(con, id="local:gamma", name="Gamma", directory="gamma",
              enabled_hermes=1)
    add_skill(con, id="local:delta", name="Delta", directory="delta")
    payload = json.dumps({
        "skills": {
            "claude": ["local:alpha", "owner/repo:skills/beta", "local:gamma", "local:gone"],
            "codex": ["local:alpha"],
        }
    }, ensure_ascii=False)
    con.execute(
        "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?, ?, ?, ?)",
        ("p1", "开发", payload, 1),
    )
    con.commit()
    con.close()


class TestInventory(unittest.TestCase):
    def test_full_scan_and_policy_seams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_home(root)
            r = run_inventory(root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("inventory ", r.stdout)
            self.assertIn("baseline: ssot=", r.stdout)
            self.assertIn("local:alpha", r.stdout)
            self.assertIn("owner/repo:skills/beta", r.stdout)
            self.assertIn("policy: non-trio live (default off)  1", r.stdout)
            self.assertIn("on HERMES  local:gamma", r.stdout)
            self.assertIn("policy: trio drift (claude/codex/opencode differ)  1", r.stdout)
            self.assertIn("on CLAUDE,CODEX  owner/repo:skills/beta", r.stdout)
            self.assertIn("profile: 开发  claude=4  codex=1", r.stdout)
            self.assertIn("summary: skills=4", r.stdout)

    def test_profile_diff_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_home(root)
            r = run_inventory(root, "--profile", "开发")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("[live]       local:alpha", r.stdout)
            self.assertIn("[dangling]   local:gone", r.stdout)
            self.assertIn("[slot-only]  local:gamma", r.stdout)
            self.assertIn("claude: 4 refs", r.stdout)
            self.assertIn("codex: 1 refs", r.stdout)

    def test_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_home(root)
            db = root / ".cc-switch" / "cc-switch.db"
            con = sqlite3.connect(db)
            before = list(con.execute(
                "SELECT id, enabled_hermes FROM skills ORDER BY id"))
            con.close()
            r = run_inventory(root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            con = sqlite3.connect(db)
            after = list(con.execute(
                "SELECT id, enabled_hermes FROM skills ORDER BY id"))
            con.close()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
