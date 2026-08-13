#!/usr/bin/env python3
"""Remote-freshness tests for doctor.py --remote (R1-R4).

Uses a local mock GitHub API server (--remote-base-url) plus a temp fixture
home cloned from fixtures/clean with github-sourced skill rows injected.
Covers: drift detection, rename detection, staleness, repo gone/archived,
upstream-not-installed list, cache reuse, and offline degradation.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "doctor.py"
FIX = ROOT / "fixtures"

# ---- mock GitHub API ------------------------------------------------------

REPO_META = {
    "context7": {"archived": False, "pushed_at": "2026-08-01T00:00:00Z", "default_branch": "master"},
    "drift-repo": {"archived": False, "pushed_at": "2026-07-20T00:00:00Z", "default_branch": "main"},
    "rename-repo": {"archived": False, "pushed_at": "2026-08-10T00:00:00Z", "default_branch": "main"},
    "stale-repo": {"archived": False, "pushed_at": "2026-08-05T00:00:00Z", "default_branch": "main"},
    "archived-repo": {"archived": True, "pushed_at": "2026-01-01T00:00:00Z", "default_branch": "main"},
    "lost-repo": {"archived": False, "pushed_at": "2026-03-01T00:00:00Z", "default_branch": "main"},
    "gone-repo": None,  # 404
}

# path -> (kind, payload)  kind: "list" | "file"
TREE = {
    ("context7", "skills"): ("list", ["find-docs", "context7-cli"]),
    ("context7", "skills/find-docs/SKILL.md"): ("file", "# find-docs\nsame content\n"),
    ("drift-repo", ""): ("list", ["README.md", "skills", "old-place"]),
    ("drift-repo", "skills"): ("list", ["brand-new", "another-new"]),
    # DB path is skills/old-place; real location is root old-place → moved
    ("drift-repo", "old-place"): ("list", ["SKILL.md"]),
    ("drift-repo", "old-place/SKILL.md"): ("file", "# old-place\nmoved here\n"),
    ("drift-repo", "skills/brand-new/SKILL.md"): ("file", "# brand-new\n"),
    ("drift-repo", "skills/another-new/SKILL.md"): ("file", "# another-new\n"),
    ("rename-repo", ""): ("list", ["review", "README.md"]),
    ("rename-repo", "review"): ("list", ["SKILL.md"]),
    ("rename-repo", "review/SKILL.md"): ("file", "# review\nsupersedes pr-review\n"),
    ("stale-repo", "skills"): ("list", ["stale-skill"]),
    ("stale-repo", "skills/stale-skill"): ("list", ["SKILL.md"]),
    ("stale-repo", "skills/stale-skill/SKILL.md"): ("file", "# stale-skill\nNEW REMOTE VERSION\n"),
    ("archived-repo", "skills"): ("list", ["arch-skill"]),
    ("archived-repo", "skills/arch-skill"): ("list", ["SKILL.md"]),
    ("archived-repo", "skills/arch-skill/SKILL.md"): ("file", "# arch-skill\n"),
    ("lost-repo", ""): ("list", ["README.md", "skills"]),
    ("lost-repo", "skills"): ("list", ["other-thing"]),
    ("lost-repo", "skills/other-thing"): ("list", ["SKILL.md"]),
    ("lost-repo", "skills/other-thing/SKILL.md"): ("file", "# other-thing\n"),
}

REQUEST_LOG: list[str] = []


class MockGithub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        REQUEST_LOG.append(self.path)
        m = re.match(
            r"^/repos/([^/]+)/([^/]+)(/contents(?:/(.*))?)?$", self.path
        )
        if not m:
            self._send(404, {"message": "bad route"})
            return
        owner, repo, suffix, content_path = m.groups()
        if suffix is None:
            # /repos/o/r -> repo metadata
            meta = REPO_META.get(repo)
            if meta is None:
                self._send(404, {"message": "Not Found"})
                return
            self._send(200, meta)
            return
        key = (repo, (content_path or "").strip("/"))
        entry = TREE.get(key)
        if entry is None:
            self._send(404, {"message": "Not Found"})
            return
        kind, payload = entry
        if kind == "list":
            data = [{"name": n, "type": "dir"} for n in payload]
            self._send(200, data)
        else:
            self._send(200, {
                "type": "file",
                "content": base64.b64encode(payload.encode()).decode(),
            })

    def _send(self, status: int, body: object) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *a) -> None:  # silence
        pass


def start_mock() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockGithub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# ---- fixture home with github rows ----------------------------------------

REMOTE_ROWS = [
    # (id, directory, owner, repo, branch)
    ("upstash/context7:skills/find-docs", "find-docs", "upstash", "context7", "master"),
    ("acme/drift-repo:skills/old-place", "old-place", "acme", "drift-repo", "main"),
    ("acme/rename-repo:pr-review", "pr-review", "acme", "rename-repo", "main"),
    ("acme/stale-repo:skills/stale-skill", "stale-skill", "acme", "stale-repo", "main"),
    ("acme/archived-repo:skills/arch-skill", "arch-skill", "acme", "archived-repo", "main"),
    ("acme/gone-repo:whatever", "gone-skill", "acme", "gone-repo", "main"),
    ("acme/lost-repo:skills/nothing-here", "lost-skill", "acme", "lost-repo", "main"),
]

LOCAL_MD = {
    "find-docs": "# find-docs\nsame content\n",   # matches remote -> OK
    "old-place": "# old-place\nold local copy\n",  # drift, content differs -> OK-ish
    "pr-review": "# pr-review\n",
    "stale-skill": "# stale-skill\nOLD LOCAL VERSION\n",  # stale -> WARN
    "arch-skill": "# arch-skill\n",
    "gone-skill": "# gone\n",
    "lost-skill": "# lost\n",
}


def build_home(tmp: Path) -> Path:
    home = tmp / "home"
    shutil.copytree(FIX / "clean", home)
    db = home / ".cc-switch" / "cc-switch.db"
    con = sqlite3.connect(db)
    try:
        for sid, directory, owner, repo, branch in REMOTE_ROWS:
            con.execute(
                "INSERT INTO skills (id, name, description, directory, repo_owner,"
                " repo_name, repo_branch, enabled_claude, enabled_codex, installed_at,"
                " content_hash, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, directory, "", directory, owner, repo, branch, 0, 0, 0, "x", 0),
            )
        con.commit()
    finally:
        con.close()
    for directory, md in LOCAL_MD.items():
        d = home / ".agents" / "skills" / directory
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(md)
    return home


def run_doctor(home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(DOCTOR), "--root", str(home), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("[")]


class TestDoctorRemote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "ccs-remote-test"
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.tmp.mkdir(parents=True)
        cls.home = build_home(cls.tmp)
        cls.srv, cls.base = start_mock()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        REQUEST_LOG.clear()
        self.addCleanup(os.environ.pop, "CCSWITCH_DOCTOR_FORCE_URLLIB", None)

    def run_remote(self, fresh: bool = True, *extra: str):
        os.environ["CCSWITCH_DOCTOR_FORCE_URLLIB"] = "1"
        cmd = ["--remote", "--remote-base-url", self.base]
        if fresh:
            cmd.append("--fresh")
        return run_doctor(self.home, *cmd, *extra)

    # -- branches ---------------------------------------------------------

    def test_repo_ok_and_content_same(self):
        r = self.run_remote()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"remote=on")
        # OK findings are filtered from the report; the healthy repo must not
        # produce any R1/R3 ERROR or WARN line.
        bad = [
            ln
            for ln in lines(r.stdout)
            if "upstash/context7" in ln and ln.startswith(("[ERROR:remote]", "[WARN:remote]"))
        ]
        self.assertEqual(bad, [], r.stdout)
        self.assertRegex(r.stdout, r"remote: checked=\d+ ok=\d+ warn=\d+ err=\d+")

    def test_drift_moved(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[WARN:remote\] R2.path  id=acme/drift-repo:skills/old-place path drift → actual upstream location old-place",
        )

    def test_renamed_similar(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[WARN:remote\] R2.path  id=acme/rename-repo:pr-review original name gone, likely replaced by review",
        )

    def test_stale(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[WARN:remote\] R3.stale  id=acme/stale-repo:skills/stale-skill local is behind upstream",
        )

    def test_repo_gone(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[ERROR:remote\] R1.repo  repo acme/gone-repo 404",
        )

    def test_archived(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[WARN:remote\] R1.repo  repo acme/archived-repo archived",
        )

    def test_lost(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[ERROR:remote\] R2.path  id=acme/lost-repo:skills/nothing-here not found upstream",
        )

    def test_upstream_list(self):
        r = self.run_remote()
        self.assertRegex(
            r.stdout,
            r"\[INFO:remote\] R4.upstream  acme/drift-repo has 2 upstream skills not installed: another-new, brand-new",
        )

    def test_summary_line(self):
        r = self.run_remote()
        self.assertRegex(r.stdout, re.compile(
            r"^remote: checked=\d+ ok=\d+ warn=\d+ err=\d+$", re.M))

    # -- mechanics ----------------------------------------------------------

    def test_no_net_degrades_gracefully(self):
        r = run_doctor(self.home, "--remote", "--no-net")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("remote partially unreachable", r.stdout)
        # no per-skill R findings when transport fails
        self.assertFalse(any(ln.startswith("[ERROR:remote]") for ln in lines(r.stdout)))

    def test_cache_reuse_second_run(self):
        self.run_remote(fresh=True)  # populate cache
        n_first = len(REQUEST_LOG)
        REQUEST_LOG.clear()
        self.run_remote(fresh=False)  # all reads served from cache
        n_second = len(REQUEST_LOG)
        self.assertGreater(n_first, 0)
        self.assertEqual(n_second, 0)

    def test_offline_default_no_network(self):
        r = run_doctor(self.home)  # no --remote
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"remote=off")
        self.assertEqual(REQUEST_LOG, [])

    def test_finding_line_format_remote(self):
        r = self.run_remote()
        for ln in lines(r.stdout):
            self.assertRegex(
                ln,
                r"^\[(OK|INFO|WARN|ERROR|FATAL):(design|hygiene|policy|remote)\] "
                r"[RD]\d+[\w.-]*\s+",
                ln,
            )


if __name__ == "__main__":
    unittest.main()
