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


class TestUpstreamPathsAndMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.home = Path(self._temp.name) / "home"
        self.home.mkdir()
        con = base_home(self.home)
        con.commit()
        con.close()
        self.db = self.home / ".cc-switch" / "cc-switch.db"
        self.ssot = self.home / ".agents" / "skills"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_codex_override_owns_projection_and_doctor_check(self) -> None:
        settings_path = self.home / ".cc-switch" / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["codexConfigDir"] = str(self.home / "custom-codex")
        settings_path.write_text(json.dumps(settings))
        write_skill_md(self.ssot, "demo")
        with sqlite3.connect(self.db) as con:
            add_skill(con, id="local:demo", name="Demo", directory="demo")

        result = run_cli(
            PIPE, self.home, "dispatch", "--id", "local:demo", "--app", "codex", "--enable"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / "custom-codex" / "skills" / "demo").is_symlink())
        self.assertFalse((self.home / ".codex" / "skills" / "demo").exists())
        report = run_cli(DOCTOR, self.home)
        self.assertNotIn("D9.live-link  id=local:demo", report.stdout)

    def test_register_reads_frontmatter_and_writes_lock_hash(self) -> None:
        source = self.home / "source"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: Demo Skill\ndescription: Local workflow.\n---\n\n# Demo\n"
        )

        result = run_cli(
            PIPE,
            self.home,
            "register",
            "--id",
            "owner/repo:demo",
            "--directory",
            "demo",
            "--source",
            str(source),
            "--repo-owner",
            "owner",
            "--repo-name",
            "repo",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with sqlite3.connect(self.db) as con:
            row = con.execute(
                "SELECT name, description, content_hash FROM skills WHERE id=?",
                ("owner/repo:demo",),
            ).fetchone()
        self.assertEqual(row[0], "Demo Skill")
        self.assertEqual(row[1], "Local workflow.")
        lock = json.loads((self.home / ".agents" / ".skill-lock.json").read_text())
        self.assertEqual(lock["skills"]["demo"]["skillFolderHash"], row[2])

    def test_register_rejects_directory_collision_and_rename(self) -> None:
        write_skill_md(self.ssot, "owned")
        with sqlite3.connect(self.db) as con:
            add_skill(con, id="local:owned", name="Owned", directory="owned")
        collision = run_cli(
            PIPE,
            self.home,
            "register",
            "--id",
            "local:other",
            "--directory",
            "owned",
        )
        self.assertNotEqual(collision.returncode, 0)
        with sqlite3.connect(self.db) as con:
            self.assertIsNone(con.execute("SELECT 1 FROM skills WHERE id='local:other'").fetchone())

        rename = run_cli(
            PIPE,
            self.home,
            "register",
            "--id",
            "local:owned",
            "--directory",
            "renamed",
        )
        self.assertNotEqual(rename.returncode, 0)

    def test_register_rejects_traversal_and_cross_platform_names(self) -> None:
        for skill_id, directory in (
            ("local:../escape", "safe"),
            ("local:good", "../escape"),
            ("owner/repo:skills\\escape", "safe"),
            ("owner/repo:skills", ".hidden"),
        ):
            result = run_cli(
                PIPE,
                self.home,
                "register",
                "--id",
                skill_id,
                "--directory",
                directory,
            )
            self.assertNotEqual(result.returncode, 0, (skill_id, directory))

    def test_register_refreshes_existing_local_lock_hash(self) -> None:
        source = self.home / "source-local"
        source.mkdir()
        (source / "SKILL.md").write_text("# Local\n")
        lock_path = self.home / ".agents" / ".skill-lock.json"
        lock_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "skills": {
                        "local-skill": {
                            "source": "local/local-skill",
                            "sourceType": "local",
                            "sourceUrl": "local:local-skill",
                            "skillFolderHash": "stale",
                        }
                    },
                }
            )
        )
        result = run_cli(
            PIPE,
            self.home,
            "register",
            "--id",
            "local:local-skill",
            "--directory",
            "local-skill",
            "--source",
            str(source),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lock = json.loads(lock_path.read_text())
        with sqlite3.connect(self.db) as con:
            db_hash = con.execute(
                "SELECT content_hash FROM skills WHERE id='local:local-skill'"
            ).fetchone()[0]
        self.assertEqual(lock["skills"]["local-skill"]["skillFolderHash"], db_hash)


if __name__ == "__main__":
    unittest.main()
