#!/usr/bin/env python3
"""Remedy seam tests — doctor findings → treatment, dry-run default, recheck.

Contract: remedy.py runs doctor first (查), prints AUTO/CMD/SKIP plan;
--apply executes auto items (D9→enable, D10→disable, D13→scrub) and re-runs
doctor (查→治→查). Decision items (D6/D7) are never auto-executed.
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
REMEDY = ROOT / "remedy.py"
FIX_LIB = ROOT / "fixtures" / "lib"
sys.path.insert(0, str(FIX_LIB))
from build_fixture import add_skill, base_home, write_skill_md  # noqa: E402


def run_remedy(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REMEDY), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestRemedy(unittest.TestCase):
    """fixture: D9 (a enabled, projection missing), D10 (b disabled, link
    leaked), D13 (slot ref local:ghost), D6 (row without SSOT dir),
    D7 (SSOT dir without row)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "home"
        self.root.mkdir()
        self.con = base_home(self.root)
        add_skill(self.con, id="local:a", name="a", directory="a", enabled_claude=1)
        add_skill(self.con, id="local:b", name="b", directory="b", enabled_claude=0)
        add_skill(self.con, id="local:gone", name="gone", directory="gone")
        write_skill_md(self.root / ".agents" / "skills", "a")
        write_skill_md(self.root / ".agents" / "skills", "b")
        payload = {"skills": {"claude": ["local:a", "local:ghost"]}}
        self.con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "demo", json.dumps(payload)),
        )
        self.con.commit()
        self.con.close()
        self.db = self.root / ".cc-switch" / "cc-switch.db"
        # D10: disabled b but SSOT-link leaked into claude app dir
        (self.root / ".claude" / "skills" / "b").symlink_to(
            self.root / ".agents" / "skills" / "b"
        )
        # D7: SSOT dir without DB row
        write_skill_md(self.root / ".agents" / "skills", "orphan")

    def tearDown(self):
        self._td.cleanup()

    def _row(self, skill_id: str, col: str):
        con = sqlite3.connect(self.db)
        r = con.execute(
            f"SELECT {col} FROM skills WHERE id=?", (skill_id,)
        ).fetchone()
        con.close()
        return r[0] if r else None

    def test_dryrun_lists_plan_and_changes_nothing(self):
        r = run_remedy(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[AUTO] D9.live-link", r.stdout)
        self.assertIn("[AUTO] D10.park-leak", r.stdout)
        self.assertIn("[AUTO] D13.slot-dangling", r.stdout)
        self.assertIn("[CMD ] D6.ssot-db", r.stdout)
        self.assertIn("--apply", r.stdout)
        self.assertIn("[dry-run]", r.stdout)
        # OK rows from doctor must never become suggestions
        self.assertNotIn("[CMD ] D3.parent-link", r.stdout)
        self.assertNotIn("[CMD ] D1.schema", r.stdout)
        # nothing written
        self.assertEqual(self._row("local:a", "enabled_claude"), 1)
        con = sqlite3.connect(self.db)
        p = json.loads(
            con.execute(
                "SELECT payload FROM profiles WHERE name='demo'"
            ).fetchone()[0]
        )
        con.close()
        self.assertIn("local:ghost", p["skills"]["claude"])

    def test_apply_fixes_auto_d6_d7_not_executed(self):
        r = run_remedy(self.root, "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[FIXED] D9.live-link", r.stdout)
        self.assertIn("[FIXED] D10.park-leak", r.stdout)
        self.assertIn("[FIXED] D13.slot-dangling", r.stdout)
        self.assertIn("doctor recheck:", r.stdout)
        # D6 row still there (decision item — command only, never auto-deleted)
        con = sqlite3.connect(self.db)
        gone = con.execute(
            "SELECT count(*) FROM skills WHERE id='local:gone'"
        ).fetchone()[0]
        p = json.loads(
            con.execute(
                "SELECT payload FROM profiles WHERE name='demo'"
            ).fetchone()[0]
        )
        con.close()
        self.assertEqual(gone, 1)
        # D13 scrubbed
        self.assertNotIn("local:ghost", p["skills"]["claude"])
        # D9 fixed: projection now exists
        self.assertTrue(
            (self.root / ".claude" / "skills" / "a").is_symlink()
        )
        # D10 fixed: leaked link removed
        self.assertFalse(
            (self.root / ".claude" / "skills" / "b").exists()
        )


if __name__ == "__main__":
    unittest.main()
