#!/usr/bin/env python3
"""cc-switch-adapter doctor — read-only health check against official skill design.

Seam (report contract): stdout report + exit code.
  - exit 1 only on FATAL; design ERROR/WARN/INFO → exit 0
  - finding lines: [LEVEL:category] CODE  msg
  - next: clean iff no FATAL and no design-ERROR; else verb suggestions
  - --root <fake-home> for fixtures; --full to rehash content

stdlib only. Never writes DB/disk/lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# --- category matrix (map: Freeze residual seam decisions) ---
# design | hygiene | policy; minor overrides OK if spirit holds
CODE_CATEGORY: dict[str, str] = {
    "D0.runtime": "design",
    "D1.schema": "design",  # not-unified-row is design; soft notes stay design too
    "D2.settings": "hygiene",
    "D3.parent-link": "design",
    "D4.canonical-id": "design",
    "D4.directory": "design",
    "D5.unified-meta": "hygiene",
    "D6.ssot-db": "design",
    "D7.db-ssot-orphan": "hygiene",
    "D8.hash": "hygiene",
    "D9.live-link": "design",
    "D10.park-leak": "policy",
    "D11.dup-directory": "design",
    "D12.lock": "hygiene",
    "D13.slot-dangling": "design",
    "D14.slot-id": "design",
    "D15.fat-snapshot": "policy",
    "D16.binding": "policy",
}

# next: verbs (not letter branches)
CODE_VERB: dict[str, str] = {
    "D0.runtime": "migrate",
    "D1.schema": "migrate",
    "D3.parent-link": "migrate",
    "D4.canonical-id": "migrate",
    "D4.directory": "migrate",
    "D6.ssot-db": "migrate|register",
    "D9.live-link": "dispatch",
    "D11.dup-directory": "migrate",
    "D13.slot-dangling": "slot",
    "D14.slot-id": "slot",
}

LEVEL_ORDER = {"FATAL": 0, "ERROR": 1, "WARN": 2, "INFO": 3, "OK": 4}

APP_DIRS_REL = {
    "claude": (".claude", "skills"),
    "codex": (".codex", "skills"),
    "gemini": (".gemini", "skills"),
    "grokbuild": (".grok", "skills"),
    "opencode": (".config", "opencode", "skills"),
    "hermes": (".hermes", "skills"),
}
EN_COL = {
    "claude": "enabled_claude",
    "codex": "enabled_codex",
    "gemini": "enabled_gemini",
    "grokbuild": "enabled_grokbuild",
    "opencode": "enabled_opencode",
    "hermes": "enabled_hermes",
}
SLOT_APPS = ("claude", "codex")


def is_canonical(i: str) -> bool:
    """owner/repo:<path> | local:<name>. Illegal: bare; empty / . / .. suffix."""
    if i.startswith("local:"):
        rest = i[6:]
        return bool(rest) and rest not in (".", "..") and not rest.startswith("/")
    if ":" not in i:
        return False
    left, right = i.split(":", 1)
    if left.count("/") < 1:
        return False
    if not right or right in (".", "..") or right.startswith("/"):
        return False
    return True


def dir_hash(root: Path) -> str | None:
    if not root.is_dir():
        return None
    files: list[Path] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".")]
        for fn in fns:
            if fn.startswith("."):
                continue
            files.append(Path(dp) / fn)
    files.sort()
    h = hashlib.sha256()
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        try:
            h.update(fp.read_bytes())
            h.update(b"\0")
        except OSError:
            return None
    return h.hexdigest()


def category_for(code: str) -> str:
    if code in CODE_CATEGORY:
        return CODE_CATEGORY[code]
    # prefix fallback
    for prefix, cat in CODE_CATEGORY.items():
        if code.startswith(prefix.split(".")[0] + "."):
            return cat
    head = code.split(".", 1)[0]
    for k, cat in CODE_CATEGORY.items():
        if k.startswith(head + "."):
            return cat
    return "hygiene"


def verb_for(code: str, msg: str) -> str | None:
    if "→" in msg:
        # prefer explicit verb after arrow if already a known verb token
        tail = msg.split("→")[-1].strip().split()[0]
        if tail in (
            "migrate",
            "dispatch",
            "slot",
            "register",
            "migrate|register",
        ) or "|" in tail:
            return tail
    if code in CODE_VERB:
        return CODE_VERB[code]
    if code.startswith("D3"):
        return "migrate"
    if code.startswith("D4") or code.startswith("D11"):
        return "migrate"
    if code.startswith("D6"):
        return "migrate|register"
    if code.startswith("D9"):
        return "dispatch"
    if code.startswith("D13") or code.startswith("D14"):
        return "slot"
    if code.startswith("D0") or code.startswith("D1"):
        return "migrate"
    return None


class Doctor:
    def __init__(self, home: Path, full_hash: bool = False):
        self.home = home.resolve()
        self.full_hash = full_hash
        self.ccs = self.home / ".cc-switch"
        self.db_path = self.ccs / "cc-switch.db"
        self.settings_path = self.ccs / "settings.json"
        self.lock_path = self.home / ".agents" / ".skill-lock.json"
        self.app_dirs = {
            app: self.home.joinpath(*parts) for app, parts in APP_DIRS_REL.items()
        }
        self.findings: list[tuple[str, str, str, str]] = []  # level, cat, code, msg
        self.ver: int | None = None
        self.ssot: Path | None = None
        self.sync: str | None = None
        self.loc: str | None = None
        self.n_skills = 0
        self._stopped = False

    def add(self, level: str, code: str, msg: str, category: str | None = None):
        cat = category or category_for(code)
        self.findings.append((level, cat, code, msg))

    def run(self) -> int:
        """Run all checks; return process exit code (1 only if FATAL)."""
        self._d0()
        if self._stopped:
            return self._emit()
        assert self.ssot is not None
        self._d1_d2()
        self._d3()
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(skills)")}
            skills = list(con.execute("SELECT * FROM skills"))
            self.n_skills = len(skills)
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self._skills_checks(skills, cols)
            self._d7()
            self._d9_d10(skills, cols)
            self._d12(skills, cols)
            self._d16_d13_d15(con, skills, cols, tables)
        finally:
            con.close()
        return self._emit()

    def _d0(self) -> None:
        if not self.settings_path.is_file():
            self.add("FATAL", "D0.runtime", f"missing {self.settings_path}")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        if not self.db_path.is_file():
            self.add("FATAL", "D0.runtime", f"missing {self.db_path}")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        try:
            cfg = json.loads(self.settings_path.read_text())
        except Exception as e:
            self.add("FATAL", "D0.runtime", f"settings unreadable: {e}")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        self.loc = cfg.get("skillStorageLocation", "cc_switch")
        self.sync = cfg.get("skillSyncMethod", "auto")
        self.ssot = (
            self.home / ".agents" / "skills"
            if self.loc == "unified"
            else self.ccs / "skills"
        )
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            self.ver = con.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "skills" not in tables:
                self.add("FATAL", "D0.runtime", "no skills table")
                self._stopped = True
            con.close()
        except Exception as e:
            self.add("FATAL", "D0.runtime", str(e))
            self._stopped = True
            self.ver = -1

    def _d1_d2(self) -> None:
        assert self.ssot is not None
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(skills)")}
        finally:
            con.close()
        en_cols = [c for c in cols if c.startswith("enabled_")]
        if "id" not in cols or not en_cols:
            self.add(
                "ERROR",
                "D1.schema",
                f"not unified-row: cols={sorted(cols)}",
            )
        else:
            self.add(
                "OK",
                "D1.schema",
                f"user_version={self.ver} enabled_cols={len(en_cols)}",
            )
        # no ERROR/WARN solely because user_version != 16 (map / ticket)
        if not self.ssot.is_dir():
            self.add(
                "WARN",
                "D2.settings",
                f"SSOT missing: {self.ssot} (loc={self.loc})",
            )
        else:
            self.add(
                "OK",
                "D2.settings",
                f"ssot={self.ssot} loc={self.loc} sync={self.sync}",
            )
        if self.sync not in ("auto", "symlink", "copy", None):
            self.add(
                "WARN",
                "D2.settings",
                f"unusual skillSyncMethod={self.sync!r}",
            )

    def _d3(self) -> None:
        for app, path in self.app_dirs.items():
            if path.exists() and path.is_symlink():
                self.add(
                    "FATAL",
                    "D3.parent-link",
                    f"app={app} path={path} -> {os.readlink(path)} → migrate",
                )
            elif path.exists():
                self.add("OK", "D3.parent-link", f"app={app} realdir")

    def _skills_checks(self, skills: list, cols: set[str]) -> None:
        assert self.ssot is not None
        dirs = [r["directory"] for r in skills]
        for d, c in Counter(dirs).items():
            if c > 1:
                self.add(
                    "ERROR",
                    "D11.dup-directory",
                    f"directory={d!r} rows={c} → migrate",
                )
        for r in skills:
            sid, directory = r["id"], r["directory"]
            if not is_canonical(sid):
                self.add(
                    "ERROR",
                    "D4.canonical-id",
                    f"id={sid!r} → migrate",
                )
            if (
                not directory
                or directory in (".", "..")
                or directory.startswith("/")
                or directory.startswith("~")
                or "/" in str(directory)
            ):
                self.add(
                    "ERROR",
                    "D4.directory",
                    f"id={sid!r} directory={directory!r} → migrate",
                )
            if "/" in sid and not sid.startswith("local:"):
                ro = r["repo_owner"] if "repo_owner" in cols else None
                rn = r["repo_name"] if "repo_name" in cols else None
                if not ro or not rn:
                    self.add(
                        "WARN",
                        "D5.unified-meta",
                        f"id={sid} missing repo_owner/name",
                    )
            ssot_p = self.ssot / directory
            if not ssot_p.is_dir():
                self.add(
                    "ERROR",
                    "D6.ssot-db",
                    f"id={sid} missing SSOT dir {ssot_p} → migrate|register",
                )
            elif not (ssot_p / "SKILL.md").exists() and not any(
                ssot_p.glob("**/SKILL.md")
            ):
                self.add(
                    "ERROR",
                    "D6.ssot-db",
                    f"id={sid} no SKILL.md under {ssot_p} → migrate|register",
                )
            ch = r["content_hash"] if "content_hash" in cols else None
            if not ch:
                self.add("WARN", "D8.hash", f"id={sid} content_hash empty → migrate")
            elif self.full_hash:
                got = dir_hash(ssot_p) if ssot_p.is_dir() else None
                if got and got != ch:
                    self.add(
                        "WARN",
                        "D8.hash",
                        f"id={sid} hash drift → migrate",
                    )

    def _d7(self) -> None:
        assert self.ssot is not None
        if not self.ssot.is_dir():
            return
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            db_dirs = {
                r[0] for r in con.execute("SELECT directory FROM skills")
            }
        finally:
            con.close()
        for p in self.ssot.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            if p.name not in db_dirs and (p / "SKILL.md").exists():
                self.add(
                    "WARN",
                    "D7.db-ssot-orphan",
                    f"SSOT/{p.name} has SKILL.md, no DB row → register",
                )

    def _link_ok(self, app_dir: Path, name: str, ssot: Path) -> str:
        if not app_dir.exists():
            return "parent_missing"
        target = app_dir / name
        if not target.exists() and not target.is_symlink():
            return "missing"
        if self.sync == "copy":
            return "ok" if target.is_dir() else "missing"
        if not target.is_symlink():
            return "not_link"
        try:
            dest = Path(os.readlink(target))
            if not dest.is_absolute():
                dest = (app_dir / dest).resolve()
            if dest.resolve() != ssot.resolve():
                return "bad_target"
        except OSError:
            return "missing"
        return "ok"

    def _d9_d10(self, skills: list, cols: set[str]) -> None:
        assert self.ssot is not None
        for r in skills:
            directory = r["directory"]
            ssot_p = self.ssot / directory
            for app, col in EN_COL.items():
                if col not in cols:
                    continue
                en = r[col]
                app_dir = self.app_dirs[app]
                if en:
                    st = self._link_ok(app_dir, directory, ssot_p)
                    # parent_missing for enabled → design ERROR (ticket)
                    if st != "ok":
                        self.add(
                            "ERROR",
                            "D9.live-link",
                            f"id={r['id']} app={app} state={st} → dispatch",
                        )
                else:
                    ent = app_dir / directory
                    if not app_dir.is_dir() or not (ent.exists() or ent.is_symlink()):
                        continue
                    leak = False
                    if ent.is_symlink():
                        try:
                            dest = Path(os.readlink(ent))
                            if not dest.is_absolute():
                                dest = (app_dir / dest).resolve()
                            leak = dest.resolve() == ssot_p.resolve()
                        except OSError:
                            leak = False
                    # copy mode: do not flag bundled real dirs
                    if leak:
                        self.add(
                            "WARN",
                            "D10.park-leak",
                            f"id={r['id']} app={app} disabled SSOT-link → dispatch",
                        )

    def _d12(self, skills: list, cols: set[str]) -> None:
        lock_skills: dict = {}
        if self.lock_path.is_file():
            try:
                lock_skills = json.loads(self.lock_path.read_text()).get("skills") or {}
            except Exception as e:
                self.add("WARN", "D12.lock", f"unreadable lock: {e}")
        dirs = {r["directory"] for r in skills}
        for r in skills:
            has_gh = False
            if "repo_owner" in cols and "repo_name" in cols:
                has_gh = bool(r["repo_owner"] and r["repo_name"])
            if has_gh and r["directory"] not in lock_skills:
                # hygiene / INFO — not design ERROR (map)
                self.add(
                    "INFO",
                    "D12.lock",
                    f"directory={r['directory']} github row, no lock key",
                )
        for k in lock_skills:
            if k not in dirs:
                self.add(
                    "INFO",
                    "D12.lock",
                    f"lock key={k!r} no DB directory",
                )

    def _d16_d13_d15(
        self, con: sqlite3.Connection, skills: list, cols: set[str], tables: set[str]
    ) -> None:
        bound_names: set[str] = set()
        if "settings" in tables:
            for (key,) in con.execute(
                "SELECT key FROM settings WHERE key LIKE 'current_profile_id_%'"
            ):
                val = con.execute(
                    "SELECT value FROM settings WHERE key=?", (key,)
                ).fetchone()[0]
                name = None
                if "profiles" in tables and val:
                    nrow = con.execute(
                        "SELECT name FROM profiles WHERE id=?", (val,)
                    ).fetchone()
                    name = nrow[0] if nrow else None
                    if name:
                        bound_names.add(name)
                self.add(
                    "INFO",
                    "D16.binding",
                    f"{key}={val} name={name!r} (binding only)",
                )

        live_by_app: dict[str, set[str]] = {}
        for app, col in EN_COL.items():
            if col in cols:
                live_by_app[app] = {r["id"] for r in skills if r[col]}

        ids = {r["id"] for r in skills}
        if "profiles" not in tables:
            return
        for row in con.execute("SELECT id, name, payload FROM profiles"):
            try:
                payload = json.loads(row["payload"] or "{}")
            except Exception:
                self.add(
                    "ERROR",
                    "D13.slot-dangling",
                    f"profile={row['name']!r} bad JSON → slot",
                )
                continue
            skills_map = payload.get("skills") or {}
            for app, arr in skills_map.items():
                if arr is None:
                    continue
                if not isinstance(arr, list):
                    self.add(
                        "INFO",
                        "D15.fat-snapshot",
                        f"profile={row['name']!r} skills.{app} not list",
                    )
                    continue
                slot = set(arr)
                for sid in slot:
                    if sid not in ids:
                        self.add(
                            "ERROR",
                            "D13.slot-dangling",
                            f"profile={row['name']!r} app={app} id={sid!r} → slot",
                        )
                    elif not is_canonical(sid):
                        self.add(
                            "ERROR",
                            "D14.slot-id",
                            f"profile={row['name']!r} app={app} id={sid!r} → slot",
                        )
                live = live_by_app.get(app, set())
                fat = slot - live
                missing = live - slot
                is_bound = row["name"] in bound_names
                if fat:
                    lvl = "WARN" if is_bound else "INFO"
                    hint = (
                        "→ slot resnap candidate, not enable"
                        if is_bound
                        else "(unbound target set; do not overwrite with live)"
                    )
                    self.add(
                        lvl,
                        "D15.fat-snapshot",
                        f"profile={row['name']!r} app={app} fat={len(fat)} (slot>live) {hint}",
                    )
                if missing and app in SLOT_APPS:
                    lvl = "WARN" if is_bound else "INFO"
                    hint = (
                        "→ slot resnap candidate"
                        if is_bound
                        else "(unbound; leave-auto-save writes departing profile)"
                    )
                    self.add(
                        lvl,
                        "D15.fat-snapshot",
                        f"profile={row['name']!r} app={app} live_only={len(missing)} {hint}",
                    )

    def _emit(self) -> int:
        findings = sorted(
            self.findings,
            key=lambda x: (LEVEL_ORDER.get(x[0], 9), x[2], x[3]),
        )
        counts = {k: 0 for k in LEVEL_ORDER}
        for lv, _, _, _ in findings:
            counts[lv] = counts.get(lv, 0) + 1

        print(
            f"doctor {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        print(
            f"baseline: user_version={self.ver} ssot={self.ssot} "
            f"sync={self.sync} skills={self.n_skills} loc={self.loc}"
        )
        print(
            f"FATAL {counts['FATAL']}  ERROR {counts['ERROR']}  "
            f"WARN {counts['WARN']}  INFO {counts['INFO']}  OK {counts['OK']}"
        )
        # category tallies for seam clarity
        design_error = 0
        hygiene_warn = 0
        for lv, cat, _, _ in findings:
            if cat == "design" and lv == "ERROR":
                design_error += 1
            if cat == "hygiene" and lv in ("WARN", "INFO"):
                hygiene_warn += 1
        print(
            f"categories: design_ERROR={design_error} "
            f"hygiene_notes={hygiene_warn} "
            f"(FATAL always design-critical)"
        )
        print()
        for lv, cat, code, msg in findings:
            if lv == "OK":
                continue
            print(f"[{lv}:{cat}] {code}  {msg}")

        # next:
        has_fatal = counts["FATAL"] > 0
        has_design_error = any(
            lv == "ERROR" and cat == "design" for lv, cat, _, _ in findings
        )
        verbs: list[str] = []
        for lv, cat, code, msg in findings:
            if lv == "FATAL" or (lv == "ERROR" and cat == "design"):
                v = verb_for(code, msg)
                if v and v not in verbs:
                    verbs.append(v)
        print()
        if has_fatal or has_design_error:
            print("next:", ", ".join(verbs) if verbs else "inspect")
        else:
            extra = ""
            if any(
                cat == "hygiene" and lv in ("WARN", "INFO", "ERROR")
                for lv, cat, _, _ in findings
            ):
                extra = "; hygiene present"
            print("next: clean" + extra)

        return 1 if has_fatal else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="cc-switch-adapter doctor (read-only report seam)"
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="fake home root for fixtures (default: real home)",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="full content_hash rehash (default: empty-hash only)",
    )
    args = p.parse_args(argv)
    home = args.root if args.root is not None else Path.home()
    return Doctor(home=home, full_hash=args.full).run()


if __name__ == "__main__":
    sys.exit(main())
