#!/usr/bin/env python3
"""Remote freshness engine for cc-switch-adapter doctor --remote (stdlib only).

Read-only GitHub client plus the three checks the adapter cares about:
  - repo existence / archived status      (R1)
  - path drift: DB path vs upstream tree  (R2)
  - staleness: local SKILL.md vs remote   (R3)
  - upstream alternatives not installed   (R4)

Transport: `gh api` when available (authenticated, 5000 req/h), plain urllib
otherwise.  Results are cached under <home>/.cc-switch/remote-cache.json so a
repeat doctor run does not re-fetch an unchanged tree.  Never writes DB, lock,
or SSOT.  Pure logic lives here; doctor.py wires it into the report seam.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True

DEFAULT_API_BASE = "https://api.github.com"

# Candidate roots probed when the DB path 404s. Only repo-agnostic layouts
# are listed; deeper containers (e.g. skills/engineering) are discovered
# recursively from these, so no per-repo structure is hardcoded.
DRIFT_ROOTS = ("", "skills", ".claude/skills")

# cap on discovered sub-containers probed per repo (keeps first run bounded)
MAX_SUB_ROOT_PROBES = 12

# cache TTLs (seconds)
TTL_REPO = 24 * 3600
TTL_LIST = 24 * 3600
TTL_FILE = 6 * 3600
CACHE_FILE = "remote-cache.json"

# max upstream "not installed" entries printed per repo
MAX_UPSTREAM_LIST = 12

# entries that are repo plumbing, not skills (R4 noise filter)
NON_SKILL_NAMES = {
    "README.md", "LICENSE", "CHANGELOG.md", "CONTEXT.md", "AGENTS.md",
    "CLAUDE.md", "skills", "docs", "scripts", "tests", "assets", "dist",
    "src", "archive", "deprecated", "examples", "packages", "plugins",
    "commands", "agents", "hooks", "workflows", "mcp-configs", "registry",
    "registry.json", "registry.toml", "cookbook", "extensions",
    "instructions", "eng", "website", "themes", "releases", "plans",
    "updates", "build", "spec", "template", ".github",
}

_FILE_SUFFIXES = (
    ".md", ".py", ".toml", ".json", ".in", ".txt", ".yml", ".yaml",
    ".js", ".ts", ".tsx", ".lock", ".png", ".svg", ".xsd", ".zip",
)


def looks_like_skill(name: str) -> bool:
    """Entry name that could be a skill dir (vs repo plumbing / files)."""
    if not name or name in NON_SKILL_NAMES or name.startswith("."):
        return False
    return not name.endswith(_FILE_SUFFIXES)


class RemoteError(Exception):
    """Transport-level failure (timeout, DNS, no gh, auth). Not a finding."""


# sentinel: distinguishes "not cached" from "cached as None" (a 404)
MISS = object()


class Github:
    """Minimal GitHub contents-API client.

    Prefers `gh api` (subprocess, authenticated).  Falls back to urllib when
    gh is missing or fails for a non-404 reason.  `base_url` is overridable
    so tests can point at a local mock server.
    """

    def __init__(
        self,
        home: Path,
        base_url: str = DEFAULT_API_BASE,
        fresh: bool = False,
        no_net: bool = False,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.home = home
        self.fresh = fresh
        self.no_net = no_net
        self.cache_path = home / ".cc-switch" / CACHE_FILE
        self.cache: dict[str, dict] = {}
        self._lock = threading.Lock()  # doctor runs repo checks in threads
        self.requests = 0  # test hook: count HTTP-ish calls
        if not no_net and self.cache_path.is_file() and not fresh:
            try:
                self.cache = json.loads(self.cache_path.read_text())
            except Exception:
                self.cache = {}

    # ---- transport ------------------------------------------------------

    def _gh_api(self, api_path: str) -> tuple[int | None, str | None]:
        """Try `gh api <api_path>`; return (http_status, json_text)."""
        if self.no_net:
            raise RemoteError("network disabled (no_net)")
        if os.environ.get("CCSWITCH_DOCTOR_FORCE_URLLIB"):
            return None, None  # tests point base_url at a local mock
        try:
            r = subprocess.run(
                ["gh", "api", api_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        if r.returncode == 0:
            return 200, r.stdout
        m = re.search(r"HTTP (\d+)", r.stderr)
        if m:
            return int(m.group(1)), None
        return None, None

    def _urllib_json(self, api_path: str) -> tuple[int | None, str | None]:
        if self.no_net:
            raise RemoteError("network disabled (no_net)")
        url = f"{self.base}/{api_path}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "cc-switch-adapter-doctor",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, None
        except Exception as e:
            raise RemoteError(f"urllib {url}: {e}") from e

    def _get(self, api_path: str) -> tuple[int, object] | tuple[None, None]:
        """(status, parsed json) or (None, None) if transport failed."""
        status, text = self._gh_api(api_path)
        if status is None and text is None:
            status, text = self._urllib_json(api_path)
        if status is None:
            return None, None
        if text is None:
            return status, None
        try:
            return status, json.loads(text)
        except Exception:
            return status, None

    # ---- cache ----------------------------------------------------------

    def _cached(self, key: str, ttl: int) -> object:
        """Cached payload or MISS.  A cached 404 (None) is still a hit."""
        with self._lock:
            if self.fresh or key not in self.cache:
                return MISS
            ent = self.cache[key]
            if time.time() - ent.get("ts", 0) > ttl:
                return MISS
            return ent.get("data")

    def _store(self, key: str, data: object) -> None:
        with self._lock:
            self.cache[key] = {"ts": time.time(), "data": data}

    def flush_cache(self) -> None:
        if not self.cache:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=1)
            )
        except OSError:
            pass  # cache is a convenience, never a failure mode

    # ---- contents API wrappers ------------------------------------------

    def repo_meta(self, owner: str, name: str) -> dict | None:
        """{archived, pushed_at, default_branch} or None when repo is gone."""
        key = f"repo:{owner}/{name}"
        got = self._cached(key, TTL_REPO)
        if got is not MISS:
            return got
        status, data = self._get(f"repos/{owner}/{name}")
        if status is None:
            raise RemoteError(f"transport failed: {owner}/{name}")
        if status == 404:
            self._store(key, None)
            return None
        if status != 200 or not isinstance(data, dict):
            # 403/500 etc — a transient failure, NOT a "gone" repo
            raise RemoteError(f"repo {owner}/{name} status {status}")
        meta = {
            "archived": bool(data.get("archived", False)),
            "pushed_at": data.get("pushed_at", ""),
            "default_branch": data.get("default_branch", "main"),
        }
        self._store(key, meta)
        return meta

    def list_dir(self, owner: str, name: str, path: str) -> list[str] | None:
        """Directory entry names under path ('' = repo root); None if absent."""
        key = f"list:{owner}/{name}:{path or '/'}"
        got = self._cached(key, TTL_LIST)
        if got is not MISS:
            return got
        api = f"repos/{owner}/{name}/contents"
        if path:
            api += f"/{path}"
        status, data = self._get(api)
        if status is None:
            raise RemoteError(f"transport failed: list {owner}/{name}/{path}")
        if status == 404:
            self._store(key, None)
            return None
        if status != 200:
            # 403/500 etc — transient failure, NOT an absent directory
            raise RemoteError(f"list {owner}/{name}/{path} status {status}")
        if not isinstance(data, list):
            # 200 + file JSON — path is a file (e.g. a probe root that is
            # Dockerfile-like), so it is not a directory
            self._store(key, None)
            return None
        entries = [e.get("name") for e in data if isinstance(e, dict) and e.get("name")]
        self._store(key, entries)
        return entries

    def file_text(self, owner: str, name: str, path: str) -> str | None:
        """UTF-8 text of one file; None when 404.  Files must be < 1 MB (contents API)."""
        key = f"file:{owner}/{name}:{path}"
        got = self._cached(key, TTL_FILE)
        if got is not MISS:
            return got
        api = f"repos/{owner}/{name}/contents/{path}"
        status, data = self._get(api)
        if status is None:
            raise RemoteError(f"transport failed: file {owner}/{name}/{path}")
        if status == 404:
            self._store(key, None)
            return None
        if status != 200:
            # 403/500 etc — transient failure, NOT an absent file
            raise RemoteError(f"file {owner}/{name}/{path} status {status}")
        if not isinstance(data, dict) or "content" not in data:
            # 200 + dir listing — path is a directory, so no such file
            self._store(key, None)
            return None
        try:
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            text = None
        self._store(key, text)
        return text


# ---- path drift / rename detection ---------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _similar(name: str, entries: list[str]) -> list[str]:
    """Entries close to `name` (excluding exact match), for rename detection."""
    return [
        e
        for e in difflib.get_close_matches(name, entries, n=4, cutoff=0.55)
        if e != name
    ]


def skill_name_from_path(path: str) -> str:
    """Last path segment ('skills/a/b' -> 'b'); single-file form -> the file."""
    seg = path.rstrip("/").split("/")[-1]
    return seg if seg else path


def is_single_file(path: str) -> bool:
    return path.rstrip("/").endswith(".md") and "/" not in path.rstrip("/")


def locate(
    gh: Github,
    owner: str,
    name: str,
    orig_path: str,
    branch: str | None = None,
) -> tuple[str, str | None, list[str]]:
    """Where is the skill in the upstream tree now?

    Returns (verdict, target, similar_names):
      - ("same", orig_path, [])        — DB path still valid
      - ("moved", new_path, [])        — exists at a probed root
      - ("renamed", candidate, sims)   — exact name gone, close match exists
      - ("single-root", "SKILL.md", [])— repo root holds a single SKILL.md
      - ("lost", None, [])             — not found anywhere we probe
      - ("single", orig_path, [])      — single-file form (no drift concept)

    Probe roots: fixed DRIFT_ROOTS plus every non-plumbing directory found in
    the repo root (covers repos like academic-writing-skills/ that host skills
    under a bespoke folder).  Rename candidates are matched only against
    filtered entries so project scaffolding does not win the diff.
    """
    p = orig_path.strip("/")
    if is_single_file(p):
        return ("single", p, [])
    # exact check first: {path} is a dir or a single file
    try:
        status_ok = _path_is_dir_or_file(gh, owner, name, p)
    except RemoteError:
        raise
    if status_ok:
        return ("same", p, [])
    leaf = skill_name_from_path(p)
    roots = list(DRIFT_ROOTS)
    try:
        root_entries = gh.list_dir(owner, name, "") or []
        # discover nested skill containers under the generic roots (one level)
        for base in ("skills", ".claude/skills"):
            subs = sorted(
                d
                for d in (gh.list_dir(owner, name, base) or [])
                if looks_like_skill(d)
            )
            roots.extend(f"{base}/{d}" for d in subs[:MAX_SUB_ROOT_PROBES])
    except RemoteError:
        raise
    if "SKILL.md" in root_entries:
        return ("single-root", "SKILL.md", [])
    for d in root_entries:
        if looks_like_skill(d):
            roots.append(d)
    candidates: dict[str, str] = {}  # entry name -> probed root
    for root in roots:
        try:
            entries = gh.list_dir(owner, name, root) or []
        except RemoteError:
            raise
        if leaf in entries:
            return ("moved", f"{root}/{leaf}" if root else leaf, [])
        for e in entries:
            if looks_like_skill(e) and e not in candidates:
                candidates[e] = root
    # rename candidates ranked across ALL probed roots at once, so the true
    # successor (e.g. gitnexus-review) beats repo scaffolding that matched
    # first by probing order
    similar = list(dict.fromkeys(_similar(leaf, list(candidates))))
    if similar:
        root = candidates[similar[0]]
        target = f"{root}/{similar[0]}" if root else similar[0]
        return ("renamed", target, similar[:4])
    # last resort: the exact leaf as a single file at the root
    if leaf.endswith(".md"):
        try:
            if gh.file_text(owner, name, leaf) is not None:
                return ("moved", leaf, [])
        except RemoteError:
            raise
    if similar:
        return ("renamed", similar[0], similar[:4])
    return ("lost", None, [])


def _path_is_dir_or_file(gh: Github, owner: str, name: str, path: str) -> bool:
    """True when contents/{path} resolves (dir) or {path}/SKILL.md exists (skill dir)."""
    try:
        if gh.file_text(owner, name, f"{path}/SKILL.md") is not None:
            return True
    except RemoteError:
        raise
    try:
        entries = gh.list_dir(owner, name, path)
    except RemoteError:
        raise
    return entries is not None


# ---- staleness ------------------------------------------------------------

def remote_skill_md(
    gh: Github, owner: str, name: str, path: str
) -> tuple[str, str] | None:
    """(text, sha256) of the upstream SKILL.md for a located path; None if gone."""
    p = path.strip("/")
    if is_single_file(p):
        text = gh.file_text(owner, name, p)
    else:
        text = gh.file_text(owner, name, f"{p}/SKILL.md")
    if text is None:
        return None
    return text, _sha256(text)
