#!/usr/bin/env python3
"""Report-seam tests for doctor.py (stdlib unittest).

Agreed seam: process boundary of doctor.py — exit code, header, finding line
shape `[LEVEL:category] CODE`, next: clean rules, read-only, D semantics.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "doctor.py"
FIX = ROOT / "fixtures"

FINDING_RE = re.compile(
    r"^\[(FATAL|ERROR|WARN|INFO):(design|hygiene|policy)\] "
    r"(D\d+[\w.-]*)\s+"
)


def run_doctor(*extra: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(DOCTOR)]
    if root is not None:
        cmd += ["--root", str(root)]
    cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def finding_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("[")]


class TestDoctorReportSeam(unittest.TestCase):
    def test_clean_fixture_exit_0_next_clean(self):
        r = run_doctor(root=FIX / "clean")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("doctor ", r.stdout)
        self.assertIn("baseline:", r.stdout)
        self.assertIn("user_version=", r.stdout)
        self.assertIn("ssot=", r.stdout)
        self.assertRegex(r.stdout, r"FATAL \d+  ERROR \d+  WARN \d+  INFO \d+")
        self.assertIn("categories:", r.stdout)
        # no design ERROR / FATAL
        for ln in finding_lines(r.stdout):
            m = FINDING_RE.match(ln)
            self.assertIsNotNone(m, ln)
            level, cat, _code = m.group(1), m.group(2), m.group(3)
            self.assertNotEqual(level, "FATAL", ln)
            self.assertFalse(level == "ERROR" and cat == "design", ln)
        self.assertIsNotNone(re.search(r"^next: clean", r.stdout, re.M), r.stdout)

    def test_parent_link_fatal_exit_1_migrate(self):
        r = run_doctor(root=FIX / "parent_link")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        fatals = [ln for ln in finding_lines(r.stdout) if ln.startswith("[FATAL:")]
        self.assertTrue(any("D3.parent-link" in ln for ln in fatals), r.stdout)
        self.assertTrue(any(":design]" in ln for ln in fatals), r.stdout)
        self.assertIsNotNone(re.search(r"^next:.*\bmigrate\b", r.stdout, re.M), r.stdout)

    def test_illegal_id_design_error_legal_nested_ok(self):
        r = run_doctor(root=FIX / "illegal_id")
        # design ERROR only → exit 0 per map
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = finding_lines(r.stdout)
        bare = [ln for ln in lines if "D4.canonical-id" in ln and "tdd" in ln]
        dot = [ln for ln in lines if "D4.canonical-id" in ln and "owner/repo:." in ln]
        self.assertTrue(bare, r.stdout)
        self.assertTrue(dot, r.stdout)
        self.assertTrue(all("[ERROR:design]" in ln for ln in bare + dot), r.stdout)
        # legal nested must not appear as D4.canonical-id error
        nested_err = [
            ln
            for ln in lines
            if "D4.canonical-id" in ln and "skills/nested-leaf" in ln
        ]
        self.assertEqual(nested_err, [], r.stdout)
        self.assertIsNotNone(re.search(r"^next:.*\bmigrate\b", r.stdout, re.M), r.stdout)
        self.assertIsNone(re.search(r"^next: clean", r.stdout, re.M), r.stdout)

    def test_fat_bound_warn_unbound_silent_no_enable_hint(self):
        r = run_doctor(root=FIX / "fat_profiles")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = finding_lines(r.stdout)
        fat = [ln for ln in lines if "D15.fat-snapshot" in ln]
        bound = [ln for ln in fat if "bound-project" in ln]
        other = [ln for ln in fat if "other-project" in ln]
        # unbound profiles intentionally differ — not findings
        self.assertEqual(other, [], r.stdout)
        self.assertTrue(bound, f"expected bound D15 WARN\n{r.stdout}")
        self.assertTrue(all(ln.startswith("[WARN:policy]") for ln in bound), bound)
        joined = "\n".join(bound).lower()
        self.assertNotIn("bulk enable", joined)
        self.assertIn("not enable", "\n".join(bound))
        # D16 is baseline status, not a finding line
        self.assertFalse(any("D16.binding" in ln for ln in lines), r.stdout)
        self.assertIn("bind=", r.stdout)
        self.assertIn("bound-project", r.stdout)
        self.assertIsNotNone(re.search(r"^next: clean", r.stdout, re.M), r.stdout)

    def test_finding_line_format(self):
        r = run_doctor(root=FIX / "illegal_id")
        for ln in finding_lines(r.stdout):
            self.assertRegex(ln, FINDING_RE.pattern)

    def test_readonly_db_unchanged(self):
        db = FIX / "clean" / ".cc-switch" / "cc-switch.db"
        before = db.read_bytes()
        mtime_before = db.stat().st_mtime_ns
        r = run_doctor(root=FIX / "clean")
        self.assertEqual(r.returncode, 0, r.stdout)
        after = db.read_bytes()
        self.assertEqual(before, after)
        # mtime may or may not bump on some FS with ro open; content is the contract
        _ = mtime_before

    def test_full_flag_accepted(self):
        r = run_doctor("--full", root=FIX / "clean")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("baseline:", r.stdout)

    def test_d12_lock_is_hygiene_info_not_design_error(self):
        # illegal_id has github row owner/repo:. and owner/repo:skills/... possibly without lock
        r = run_doctor(root=FIX / "illegal_id")
        lock_lines = [ln for ln in finding_lines(r.stdout) if "D12.lock" in ln]
        for ln in lock_lines:
            self.assertIn(":hygiene]", ln, ln)
            self.assertFalse(ln.startswith("[ERROR:"), ln)


if __name__ == "__main__":
    unittest.main()
