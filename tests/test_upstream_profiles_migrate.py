#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPE = ROOT / "pipe.py"
DOCTOR = ROOT / "doctor.py"
REMEDY = ROOT / "remedy.py"
FIX_LIB = ROOT / "fixtures" / "lib"
sys.path.insert(0, str(FIX_LIB))
from build_fixture import add_skill, base_home, write_skill_md  # noqa: E402


def run_cli(script: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--root", str(home), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestUpstreamProfilesAndMigration(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.home = Path(self._temp.name) / "home"
        self.home.mkdir()
        con = base_home(self.home)
        add_skill(
            con,
            id="local:old",
            name="Old",
            directory="old",
            enabled_codex=1,
        )
        payload = {"skills": {"claude": None, "codex": ["local:old", "local:ghost"]}}
        con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "project", json.dumps(payload)),
        )
        con.commit()
        con.close()
        self.db = self.home / ".cc-switch" / "cc-switch.db"
        self.ssot = self.home / ".agents" / "skills"
        write_skill_md(self.ssot, "old")
        (self.home / ".codex" / "skills").mkdir(parents=True, exist_ok=True)
        (self.home / ".codex" / "skills" / "old").symlink_to(self.ssot / "old")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def payload(self) -> dict[str, dict[str, list[str] | None]]:
        with sqlite3.connect(self.db) as con:
            raw = con.execute("SELECT payload FROM profiles WHERE id='p1'").fetchone()[0]
        return json.loads(raw)

    def test_uninstall_preserves_snapshot_and_dangling_is_not_auto(self) -> None:
        dry_run = run_cli(PIPE, self.home, "uninstall", "--id", "local:old")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertNotIn("scrub profile", dry_run.stdout)

        report = run_cli(DOCTOR, self.home)
        self.assertIn("[WARN:policy] D13.slot-dangling", report.stdout)
        remedy = run_cli(REMEDY, self.home)
        self.assertNotIn("[AUTO] D13.slot-dangling", remedy.stdout)

    def test_slot_rejects_apps_without_profile_scope(self) -> None:
        before = self.payload()
        result = run_cli(
            PIPE,
            self.home,
            "slot",
            "resnap",
            "--profile",
            "project",
            "--app",
            "gemini",
            "--apply",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.payload(), before)

    def test_migrate_preserves_enable_and_rewrites_snapshot_id(self) -> None:
        result = run_cli(
            PIPE,
            self.home,
            "migrate",
            "--from-id",
            "local:old",
            "--to-id",
            "local:new",
            "--directory",
            "new",
            "--name",
            "New",
            "--apply",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with sqlite3.connect(self.db) as con:
            old = con.execute("SELECT 1 FROM skills WHERE id='local:old'").fetchone()
            new = con.execute(
                "SELECT directory, enabled_codex FROM skills WHERE id='local:new'"
            ).fetchone()
        self.assertIsNone(old)
        self.assertEqual(new, ("new", 1))
        self.assertEqual(
            self.payload()["skills"]["codex"], ["local:new", "local:ghost"]
        )
        self.assertTrue((self.home / ".codex" / "skills" / "new").is_symlink())
        self.assertFalse((self.home / ".codex" / "skills" / "old").exists())


if __name__ == "__main__":
    unittest.main()
