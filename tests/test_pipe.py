#!/usr/bin/env python3
"""TDD seam tests for pipe.py register + dispatch (+ content_hash SSOT)."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPE = ROOT / "pipe.py"
DOCTOR = ROOT / "doctor.py"
HASH = ROOT / "content_hash.py"
FIX_LIB = ROOT / "fixtures" / "lib"
sys.path.insert(0, str(FIX_LIB))
sys.path.insert(0, str(ROOT))
from build_fixture import add_skill, base_home, write_skill_md  # noqa: E402
from content_hash import dir_hash  # noqa: E402


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def run_pipe(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(PIPE), "--root", str(root), *args])


def run_doctor(root: Path) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(DOCTOR), "--root", str(root)])


def finding_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("[")]


class TestContentHashSSOT(unittest.TestCase):
    def test_dir_hash_stable_and_cli(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"
            d.mkdir()
            (d / "SKILL.md").write_text("# Hi\n")
            a = dir_hash(d)
            b = dir_hash(d)
            self.assertIsNotNone(a)
            self.assertEqual(a, b)
            r = run([sys.executable, str(HASH), str(d)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), a)


class TestPipeRegisterDispatch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "home"
        self.root.mkdir()
        self.con = base_home(self.root)
        self.con.commit()
        self.con.close()
        self.ssot = self.root / ".agents" / "skills"
        self.db = self.root / ".cc-switch" / "cc-switch.db"

    def tearDown(self):
        self._td.cleanup()

    def _row(self, skill_id: str):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        con.close()
        return r

    def _profiles_payloads(self) -> list[str]:
        con = sqlite3.connect(self.db)
        rows = [r[0] for r in con.execute("SELECT payload FROM profiles")]
        con.close()
        return rows

    def test_register_park_no_projection_no_slot_doctor_clean_enables(self):
        src = self.root / "src-skill"
        src.mkdir()
        (src / "SKILL.md").write_text("# Parked\n")
        # seed empty profiles to detect silent writes
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "proj", json.dumps({"skills": {"claude": []}})),
        )
        con.commit()
        before = con.execute("SELECT payload FROM profiles WHERE id='p1'").fetchone()[0]
        con.close()

        r = run_pipe(
            self.root,
            "register",
            "--id",
            "local:parked",
            "--directory",
            "parked",
            "--source",
            str(src),
            "--name",
            "Parked",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        row = self._row("local:parked")
        self.assertIsNotNone(row)
        self.assertEqual(row["enabled_claude"], 0)
        self.assertEqual(row["enabled_codex"], 0)
        self.assertTrue((self.ssot / "parked" / "SKILL.md").is_file())
        proj = self.root / ".claude" / "skills" / "parked"
        self.assertFalse(proj.exists() or proj.is_symlink())
        after = self._profiles_payloads()
        self.assertEqual(after, [before])

        doc = run_doctor(self.root)
        self.assertEqual(doc.returncode, 0, doc.stdout)
        d9 = [ln for ln in finding_lines(doc.stdout) if "D9.live-link" in ln and "parked" in ln]
        self.assertEqual(d9, [], doc.stdout)

    def test_register_named_app_install_enable_clears_d9(self):
        src = self.root / "src-on"
        src.mkdir()
        (src / "SKILL.md").write_text("# On\n")
        r = run_pipe(
            self.root,
            "register",
            "--id",
            "local:on",
            "--directory",
            "on",
            "--source",
            str(src),
            "--app",
            "claude",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        row = self._row("local:on")
        self.assertEqual(row["enabled_claude"], 1)
        link = self.root / ".claude" / "skills" / "on"
        self.assertTrue(link.is_symlink() or link.is_dir())
        doc = run_doctor(self.root)
        self.assertEqual(doc.returncode, 0, doc.stdout)
        d9 = [
            ln
            for ln in finding_lines(doc.stdout)
            if "D9.live-link" in ln and "local:on" in ln
        ]
        self.assertEqual(d9, [], doc.stdout)

    def test_dispatch_enable_disable_keeps_ssot_no_profile_edit(self):
        write_skill_md(self.ssot, "tog", "Tog")
        con = sqlite3.connect(self.db)
        add_skill(
            con,
            id="local:tog",
            name="Tog",
            directory="tog",
            enabled_claude=0,
            content_hash="abc",
        )
        con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "proj", json.dumps({"skills": {"claude": ["local:other"]}})),
        )
        con.commit()
        before = con.execute("SELECT payload FROM profiles").fetchone()[0]
        con.close()

        r = run_pipe(
            self.root, "dispatch", "--id", "local:tog", "--app", "claude", "--enable"
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._row("local:tog")["enabled_claude"], 1)
        self.assertTrue((self.root / ".claude" / "skills" / "tog").exists())

        r = run_pipe(
            self.root, "dispatch", "--id", "local:tog", "--app", "claude", "--disable"
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._row("local:tog")["enabled_claude"], 0)
        self.assertFalse((self.root / ".claude" / "skills" / "tog").exists())
        self.assertTrue((self.ssot / "tog" / "SKILL.md").is_file())
        after = self._profiles_payloads()
        self.assertEqual(after, [before])

    def test_parent_link_blocks_mutate(self):
        write_skill_md(self.ssot, "x", "X")
        con = sqlite3.connect(self.db)
        add_skill(con, id="local:x", name="X", directory="x", content_hash="1")
        con.commit()
        con.close()
        claude = self.root / ".claude" / "skills"
        shutil.rmtree(claude)
        claude.symlink_to(self.ssot)
        r = run_pipe(
            self.root, "dispatch", "--id", "local:x", "--app", "claude", "--enable"
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("parent-link", r.stderr.lower() + r.stdout.lower())

    def test_refuses_opaque_dir_removal(self):
        write_skill_md(self.ssot, "own", "Own")
        con = sqlite3.connect(self.db)
        add_skill(
            con,
            id="local:own",
            name="Own",
            directory="own",
            enabled_claude=1,
            content_hash="1",
        )
        con.commit()
        con.close()
        dest = self.root / ".claude" / "skills" / "own"
        dest.mkdir(parents=True)
        (dest / "not-a-skill.txt").write_text("opaque")
        # no SKILL.md → opaque
        r = run_pipe(
            self.root, "dispatch", "--id", "local:own", "--app", "claude", "--disable"
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(dest.exists())
        self.assertIn("opaque", r.stderr.lower())

    def test_copy_sync_method(self):
        cfg = json.loads((self.root / ".cc-switch" / "settings.json").read_text())
        cfg["skillSyncMethod"] = "copy"
        (self.root / ".cc-switch" / "settings.json").write_text(json.dumps(cfg))
        src = self.root / "src-copy"
        src.mkdir()
        (src / "SKILL.md").write_text("# Copy\n")
        r = run_pipe(
            self.root,
            "register",
            "--id",
            "local:copy",
            "--directory",
            "copy",
            "--source",
            str(src),
            "--app",
            "claude",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dest = self.root / ".claude" / "skills" / "copy"
        self.assertTrue(dest.is_dir())
        self.assertFalse(dest.is_symlink())
        self.assertTrue((dest / "SKILL.md").is_file())


class TestPipeSlotOps(unittest.TestCase):
    """slot subcommands: JSON-only, dry-run default, --apply writes."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "home"
        self.root.mkdir()
        self.con = base_home(self.root)
        add_skill(
            self.con, id="local:a", name="a", directory="a", enabled_claude=1
        )
        add_skill(self.con, id="local:b", name="b", directory="b")
        write_skill_md(self.root / ".agents" / "skills", "a")
        write_skill_md(self.root / ".agents" / "skills", "b")
        payload = {
            "skills": {
                "claude": ["local:a", "local:b", "local:ghost"],
                "codex": ["local:b"],
            }
        }
        self.con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "demo", json.dumps(payload)),
        )
        self.con.commit()
        self.con.close()
        self.db = self.root / ".cc-switch" / "cc-switch.db"

    def tearDown(self):
        self._td.cleanup()

    def _payload(self) -> dict:
        con = sqlite3.connect(self.db)
        p = json.loads(
            con.execute(
                "SELECT payload FROM profiles WHERE name='demo'"
            ).fetchone()[0]
        )
        con.close()
        return p

    def test_slot_list_marks_dangling(self):
        r = run_pipe(self.root, "slot", "list", "--profile", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("local:ghost  # dangling", r.stdout)
        self.assertIn("claude: local:a", r.stdout)

    def test_slot_scrub_dryrun_noop_then_apply(self):
        r = run_pipe(self.root, "slot", "scrub", "--profile", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[dry-run]", r.stdout)
        self.assertIn("local:ghost", self._payload()["skills"]["claude"])

        r = run_pipe(self.root, "slot", "scrub", "--profile", "demo", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        skills = self._payload()["skills"]
        self.assertEqual(skills["claude"], ["local:a", "local:b"])
        self.assertEqual(skills["codex"], ["local:b"])

    def test_slot_resnap_aligns_to_live(self):
        # live claude = {local:a}; slot claude has a + b → resnap drops b
        r = run_pipe(
            self.root, "slot", "resnap", "--profile", "demo",
            "--app", "claude", "--apply",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._payload()["skills"]["claude"], ["local:a"])

    def test_slot_add_remove(self):
        r = run_pipe(
            self.root, "slot", "remove", "--profile", "demo",
            "--app", "codex", "--id", "local:b", "--apply",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._payload()["skills"]["codex"], [])
        r = run_pipe(
            self.root, "slot", "add", "--profile", "demo",
            "--app", "codex", "--id", "local:a", "--apply",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._payload()["skills"]["codex"], ["local:a"])
        # non-canonical rejected
        r = run_pipe(
            self.root, "slot", "add", "--profile", "demo",
            "--app", "codex", "--id", "bare", "--apply",
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)

    def test_slot_never_touches_live(self):
        run_pipe(self.root, "slot", "scrub", "--profile", "demo", "--apply")
        run_pipe(self.root, "slot", "resnap", "--profile", "demo", "--app", "claude", "--apply")
        con = sqlite3.connect(self.db)
        a = con.execute(
            "SELECT enabled_claude FROM skills WHERE id='local:a'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(a, 1)


class TestPipeUninstall(unittest.TestCase):
    """uninstall: dry-run default; full removal; orphan path."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "home"
        self.root.mkdir()
        self.con = base_home(self.root)
        add_skill(self.con, id="local:x", name="x", directory="x", enabled_claude=1)
        write_skill_md(self.root / ".agents" / "skills", "x")
        payload = {"skills": {"claude": ["local:x"]}}
        self.con.execute(
            "INSERT INTO profiles (id, name, payload, updated_at) VALUES (?,?,?,1)",
            ("p1", "demo", json.dumps(payload)),
        )
        self.con.commit()
        self.con.close()
        self.db = self.root / ".cc-switch" / "cc-switch.db"
        (self.root / ".claude" / "skills" / "x").symlink_to(
            self.root / ".agents" / "skills" / "x"
        )

    def tearDown(self):
        self._td.cleanup()

    def test_uninstall_dryrun_noop(self):
        r = run_pipe(self.root, "uninstall", "--id", "local:x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[dry-run]", r.stdout)
        con = sqlite3.connect(self.db)
        self.assertIsNotNone(
            con.execute("SELECT 1 FROM skills WHERE id='local:x'").fetchone()
        )
        con.close()
        self.assertTrue((self.root / ".agents" / "skills" / "x").is_dir())

    def test_uninstall_apply_full_removal(self):
        r = run_pipe(self.root, "uninstall", "--id", "local:x", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = sqlite3.connect(self.db)
        row = con.execute(
            "SELECT count(*) FROM skills WHERE id='local:x'"
        ).fetchone()[0]
        self.assertEqual(row, 0)
        p = json.loads(
            con.execute(
                "SELECT payload FROM profiles WHERE name='demo'"
            ).fetchone()[0]
        )
        con.close()
        self.assertNotIn("local:x", p["skills"]["claude"])
        self.assertFalse((self.root / ".agents" / "skills" / "x").exists())
        self.assertFalse(
            (self.root / ".claude" / "skills" / "x").exists()
        )

    def test_uninstall_orphan_path_when_ssot_missing(self):
        # simulate orphan: SSOT dir already gone (dangling projection remains)
        import shutil
        shutil.rmtree(self.root / ".agents" / "skills" / "x")
        r = run_pipe(self.root, "uninstall", "--id", "local:x", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already missing", r.stdout)
        con = sqlite3.connect(self.db)
        row = con.execute(
            "SELECT count(*) FROM skills WHERE id='local:x'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(row, 0)
        # dangling projection removed
        self.assertFalse(
            (self.root / ".claude" / "skills" / "x").exists()
            or (self.root / ".claude" / "skills" / "x").is_symlink()
        )


if __name__ == "__main__":
    unittest.main()
