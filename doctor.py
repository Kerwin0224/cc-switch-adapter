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
import json
import os
import sqlite3
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

# single hash SSOT (shared with pipe/reconcile)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_hash import dir_hash  # noqa: E402
from adapter_contract import (
    APP_DIRS_REL,
    app_skill_dirs,
    is_canonical_id,
    is_safe_directory,
)  # noqa: E402
import cc_remote  # noqa: E402
from cc_remote import (  # noqa: E402
    Github,
    RemoteError,
    locate,
    remote_skill_md,
    skill_name_from_path,
)

# --- category matrix (map: Freeze residual seam decisions) ---
# design | hygiene | policy | remote; minor overrides OK if spirit holds
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
    "D13.slot-dangling": "policy",
    "D14.slot-id": "design",
    "D15.fat-snapshot": "policy",
    "D16.binding": "policy",
    # --remote checks; never FATAL, never design (report-only seam)
    "R1.repo": "remote",
    "R2.path": "remote",
    "R3.stale": "remote",
    "R3.self": "remote",
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

EN_COL = {
    "claude": "enabled_claude",
    "codex": "enabled_codex",
    "gemini": "enabled_gemini",
    "grokbuild": "enabled_grokbuild",
    "opencode": "enabled_opencode",
    "hermes": "enabled_hermes",
}
SLOT_APPS = ("claude", "codex")


is_canonical = is_canonical_id


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
    def __init__(
        self,
        home: Path,
        full_hash: bool = False,
        remote: bool = False,
        fresh: bool = False,
        remote_base: str | None = None,
        no_net: bool = False,
    ):
        self.home = home.resolve()
        self.full_hash = full_hash
        self.remote = remote
        self.fresh = fresh
        self.self_directory = Path(__file__).resolve().parent.name
        self.remote_base = remote_base
        self.no_net = no_net
        self._lock = threading.Lock()  # remote repo checks run in threads
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
        self.bound_names: set[str] = set()
        self.binding_notes: list[str] = []
        self.r_stats: dict[str, int] = {"checked": 0, "ok": 0, "warn": 0, "err": 0}
        self._stopped = False

    def add(self, level: str, code: str, msg: str, category: str | None = None):
        cat = category or category_for(code)
        with self._lock:
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
            if self.remote:
                self._r_checks(skills, cols)
        finally:
            con.close()
        return self._emit()

    def _d0(self) -> None:
        if not self.settings_path.is_file():
            self.add("FATAL", "D0.runtime", f"缺少运行时文件 {self.settings_path}（cc-switch 可能未初始化）")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        if not self.db_path.is_file():
            self.add("FATAL", "D0.runtime", f"缺少数据库文件 {self.db_path}（cc-switch 可能未初始化）")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        try:
            cfg = json.loads(self.settings_path.read_text())
        except Exception as e:
            self.add("FATAL", "D0.runtime", f"settings.json 无法读取：{e}")
            self._stopped = True
            self.ver = -1
            self.ssot = self.home / ".agents" / "skills"
            self.sync = "?"
            self.loc = "?"
            return
        self.loc = cfg.get("skillStorageLocation", "cc_switch")
        self.sync = cfg.get("skillSyncMethod", "auto")
        self.app_dirs = app_skill_dirs(self.home, cfg)
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
                self.add("FATAL", "D0.runtime", "数据库里没有 skills 表")
                self._stopped = True
            con.close()
        except Exception as e:
            self.add("FATAL", "D0.runtime", f"运行时读取失败：{e}")
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
                f"skills 表不是统一行结构（缺 enabled_* 列），实际列 {sorted(cols)} → migrate 修复",
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
                f"SSOT 目录不存在：{self.ssot}（storageLocation={self.loc}）",
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
                f"同步方式 {self.sync!r} 不是常见的 symlink/copy",
            )

    def _d3(self) -> None:
        for app, path in self.app_dirs.items():
            if path.exists() and path.is_symlink():
                self.add(
                    "FATAL",
                    "D3.parent-link",
                    f"app={app} 的 skills 父目录整棵是符号链接 {path}（指向 {os.readlink(path)}）→ migrate 修复",
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
                    f"目录 {d!r} 被 {c} 行共用，应唯一 → migrate 分开",
                )
        for r in skills:
            sid, directory = r["id"], r["directory"]
            if not is_canonical(sid):
                self.add(
                    "ERROR",
                    "D4.canonical-id",
                    f"id={sid!r} 写法不合法，应为 local:名 或 owner/repo:路径 → migrate 修正",
                )
            if not is_safe_directory(str(directory)):
                self.add(
                    "ERROR",
                    "D4.directory",
                    f"id={sid!r} 的目录名 {directory!r} 不合法，应为单个非隐藏路径段 → migrate 修正",
                )
            if "/" in sid and not sid.startswith("local:"):
                ro = r["repo_owner"] if "repo_owner" in cols else None
                rn = r["repo_name"] if "repo_name" in cols else None
                if not ro or not rn:
                    self.add(
                        "WARN",
                        "D5.unified-meta",
                        f"id={sid} 缺 repo_owner/name 字段 → migrate 补齐",
                    )
            ssot_p = self.ssot / directory
            if not ssot_p.is_dir():
                self.add(
                    "ERROR",
                    "D6.ssot-db",
                    f"id={sid} 数据库有记录但 SSOT 缺目录 {ssot_p} → migrate|register 处理",
                )
            elif not (ssot_p / "SKILL.md").exists() and not any(
                ssot_p.glob("**/SKILL.md")
            ):
                self.add(
                    "ERROR",
                    "D6.ssot-db",
                    f"id={sid} 目录 {ssot_p} 下没有 SKILL.md → migrate|register 处理",
                )
            ch = r["content_hash"] if "content_hash" in cols else None
            if not ch:
                self.add("WARN", "D8.hash", f"id={sid} 没有内容指纹记录（hash 为空）→ migrate 补记")
            elif self.full_hash:
                got = dir_hash(ssot_p) if ssot_p.is_dir() else None
                if got and got != ch:
                    self.add(
                        "WARN",
                        "D8.hash",
                        f"id={sid} 本地内容与记录的指纹不一致（改过后没更新）→ migrate 更新",
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
                    f"SSOT/{p.name} 有 SKILL.md 但数据库没有登记 → register 补登记",
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
                            f"id={r['id']} app={app} state={st} 已启用但投影不可用 → dispatch 修复",
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
                            f"id={r['id']} app={app} 已停用但 SSOT 投影仍残留 → dispatch 清除",
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
                    f"directory={r['directory']} 是 GitHub 来源但 lock 无对应条目",
                )
        for k in lock_skills:
            if k not in dirs:
                self.add(
                    "INFO",
                    "D12.lock",
                    f"lock 条目 {k!r} 在数据库无对应 directory",
                )

    def _d16_d13_d15(
        self, con: sqlite3.Connection, skills: list, cols: set[str], tables: set[str]
    ) -> None:
        # D16: binding is status, not a finding — fold into baseline only.
        self.bound_names: set[str] = set()
        self.binding_notes: list[str] = []
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
                        self.bound_names.add(name)
                scope = key.removeprefix("current_profile_id_") or key
                label = name if name else (val or "—")
                self.binding_notes.append(f"{scope}={label!r}")

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
                    f"profile={row['name']!r} 快照 JSON 损坏 → slot 修复",
                )
                continue
            skills_map = payload.get("skills") or {}
            for app, arr in skills_map.items():
                if arr is None:
                    continue
                if not isinstance(arr, list):
                    # malformed JSON shape — always report
                    self.add(
                        "ERROR",
                        "D14.slot-id",
                        f"profile={row['name']!r} skills.{app} 不是列表，快照格式损坏 → slot 修复",
                    )
                    continue
                slot = set(arr)
                for sid in slot:
                    if sid not in ids:
                        self.add(
                            "WARN",
                            "D13.slot-dangling",
                            f"profile={row['name']!r} app={app} id={sid!r} 快照引用了已删除的技能 → slot 清理",
                        )
                    elif not is_canonical(sid):
                        self.add(
                            "ERROR",
                            "D14.slot-id",
                            f"profile={row['name']!r} app={app} id={sid!r} 快照里的 id 写法不合法 → slot 修正",
                        )
                # Different unbound profiles *should* differ from current live.
                # Only the bound profile's slot vs live is actionable noise/hygiene.
                is_bound = row["name"] in self.bound_names
                if not is_bound:
                    continue
                live = live_by_app.get(app, set())
                fat = slot - live
                missing = live - slot
                if fat:
                    self.add(
                        "WARN",
                        "D15.fat-snapshot",
                        f"profile={row['name']!r} app={app} 快照比实际多 {len(fat)} 个"
                        f"（记着但已没开）→ slot resnap 对齐快照，不会自动开启",
                    )
                if missing and app in SLOT_APPS:
                    self.add(
                        "WARN",
                        "D15.fat-snapshot",
                        f"profile={row['name']!r} app={app} 实开着 {len(missing)} 个"
                        f"但没存进快照 → slot resnap 收进快照，不会自动开启",
                    )

    # ---- remote checks (--remote) ---------------------------------------
    # Report-only seam: findings are category=remote, never FATAL, never
    # design-ERROR, so `next:`/exit code semantics are unchanged offline.

    def _r_add(self, level: str, code: str, msg: str) -> None:
        self.add(level, code, msg, category="remote")
        if level == "OK":
            self.r_stats["ok"] += 1
        elif level in ("WARN", "INFO"):
            self.r_stats["warn"] += 1
        elif level == "ERROR":
            self.r_stats["err"] += 1
        self.r_stats["checked"] += 1

    def _r_checks(self, skills: list, cols: set[str]) -> None:
        assert self.ssot is not None
        if "repo_owner" not in cols or "repo_name" not in cols:
            self.add("INFO", "R1.repo", "没有 repo 字段，跳过云端检查",
                     category="remote")
            return
        gh = Github(
            home=self.home,
            base_url=self.remote_base or cc_remote.DEFAULT_API_BASE,
            fresh=self.fresh,
            no_net=self.no_net,
        )
        remote_rows = [
            r
            for r in skills
            if r["repo_owner"] and r["repo_name"] and "/" in (r["id"] or "")
            and not (r["id"] or "").startswith("local:")
        ]
        if not remote_rows:
            self.add("OK", "R1.repo", "没有 GitHub 来源的 skill 需要检查",
                     category="remote")
            return
        # repo key -> set of skill indices
        repos: dict[tuple[str, str], list[int]] = {}
        for i, r in enumerate(remote_rows):
            repos.setdefault((r["repo_owner"], r["repo_name"]), []).append(i)
        errs: list[str] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {
                ex.submit(
                    self._r_repo, gh, owner, name,
                    [remote_rows[i] for i in idxs],
                ): (owner, name)
                for (owner, name), idxs in sorted(repos.items())
            }
            for fut in futs:
                try:
                    fut.result()
                except RemoteError as e:
                    errs.append(str(e))
        gh.flush_cache()
        if errs:
            # transport failure: one WARN, no per-skill noise
            self.add("WARN", "R1.repo",
                     f"云端部分检查未完成：{errs[0]}；稍后重试"
                     f"（缓存命中的不受影响）",
                     category="remote")

    def _r_repo(self, gh, owner: str, name: str, rows: list) -> None:
        meta = gh.repo_meta(owner, name)
        if meta is None:
            for r in rows:
                self._r_add("ERROR", "R1.repo",
                            f"仓库 {owner}/{name} 404，已删除或转私有")
            return
        pushed = (meta.get("pushed_at") or "")[:10]
        if meta.get("archived"):
            self._r_add("WARN", "R1.repo",
                        f"仓库 {owner}/{name} 已归档（最后推送 {pushed}），"
                        f"已停止维护，考虑替代")
        else:
            self._r_add("OK", "R1.repo",
                        f"仓库 {owner}/{name} 正常（最后推送 {pushed}）")
        for r in rows:
            sid = r["id"]
            path = sid.split(":", 1)[1] if ":" in sid else ""
            verdict, target, similar = locate(gh, owner, name, path)
            if verdict == "lost":
                self._r_add("ERROR", "R2.path",
                            f"id={sid} 上游找不到（探测 {len(cc_remote.DRIFT_ROOTS)}"
                            f"+ 个候选根），已从上游移除")
                continue
            if verdict in ("moved", "single-root"):
                detail = "单文件形式" if verdict == "single-root" else "路径漂移"
                self._r_add("WARN", "R2.path",
                            f"id={sid} 上游位置变了（{detail}），现在在 {target}"
                            f"（数据库路径需更新）")
            elif verdict == "renamed":
                self._r_add("WARN", "R2.path",
                            f"id={sid} 原名在上游已消失，疑似被 {target} 取代"
                            f"（相近：{', '.join(similar)}）")
                continue  # a successor is a different skill; no stale compare
            # staleness vs the resolved location
            got = remote_skill_md(gh, owner, name, target) if target else None
            local_md = self.ssot / r["directory"] / "SKILL.md"
            if r["directory"] == self.self_directory:
                self._r_add("INFO", "R3.self",
                            f"id={sid} 有未推送的本地改动（正常：adapter 在 "
                            f"agent 目录开发，GitHub 只是发布出口）")
                continue
            if got is None:
                if verdict != "same":
                    self._r_add("ERROR", "R3.stale",
                                f"id={sid} 新位置 {target} 没有 SKILL.md")
                continue
            remote_text, remote_hash = got
            if not local_md.is_file():
                # D6 already covers the missing SSOT; note only when remote ok
                self._r_add("WARN", "R3.stale",
                            f"id={sid} 本地缺 SKILL.md 但上游存在（见 D6）")
                continue
            local_text = local_md.read_text(encoding="utf-8", errors="replace")
            # universal newlines already turned CRLF into LF on read; match
            # the normalized remote side (see remote_skill_md)
            if cc_remote._sha256(local_text.replace("\r\n", "\n")) == remote_hash:
                self._r_add("OK", "R3.stale", f"id={sid} 与上游一致")
            else:
                self._r_add("WARN", "R3.stale",
                            f"id={sid} 本地与上游不一致"
                            f"（本地 {cc_remote._sha256(local_text)[:8]} vs "
                            f"上游 {remote_hash[:8]}）→ 按 experience.md 的 "
                            f"R3 流程刷新，先备份")

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
        bind = f"  bind={','.join(self.binding_notes)}" if self.binding_notes else ""
        remote_tag = f" remote={'on' if self.remote else 'off'}"
        print(
            f"baseline: user_version={self.ver} ssot={self.ssot} "
            f"sync={self.sync} skills={self.n_skills} loc={self.loc}{bind}{remote_tag}"
        )
        print(
            f"FATAL {counts['FATAL']}  ERROR {counts['ERROR']}  "
            f"WARN {counts['WARN']}  INFO {counts['INFO']}  OK {counts['OK']}"
        )
        if self.remote:
            print(
                f"remote: checked={self.r_stats['checked']} "
                f"ok={self.r_stats['ok']} warn={self.r_stats['warn']} "
                f"err={self.r_stats['err']}"
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
    p.add_argument(
        "--remote",
        action="store_true",
        help="check upstream GitHub repos: drift, staleness (R1-R3)",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="with --remote: bypass the remote cache",
    )
    p.add_argument(
        "--remote-base-url",
        type=str,
        default=None,
        help="with --remote: GitHub API base (tests use a local mock)",
    )
    p.add_argument(
        "--no-net",
        action="store_true",
        help="with --remote: force transport failure (test/offline path)",
    )
    args = p.parse_args(argv)
    home = args.root if args.root is not None else Path.home()
    return Doctor(
        home=home,
        full_hash=args.full,
        remote=args.remote,
        fresh=args.fresh,
        remote_base=args.remote_base_url,
        no_net=args.no_net,
    ).run()


if __name__ == "__main__":
    sys.exit(main())
