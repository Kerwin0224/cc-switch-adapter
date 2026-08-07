#!/usr/bin/env python3
"""cc-switch-adapter closed-pipe mutators — register + dispatch (stdlib only).

Mirrors official SkillService order for live changes:
  parent-link precheck → filesystem projection → DB enabled_* (toggle_app style).

register:
  park (default): SSOT + canonical row, all enables 0, no projection, no slot write
  named app: park steps + install-enable that app (enable + projection)

dispatch:
  enable/disable one app; SSOT kept on disable; profiles untouched

Never bulk-enables fat slots. Never writes project-slot unless a future slot subcommand.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

# local import: same package root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_hash import dir_hash  # noqa: E402
from adapter_contract import (  # noqa: E402
    APP_DIRS_REL,
    MigrationRequest,
    PROFILE_SKILL_APPS,
    app_skills_dir as resolve_app_skills_dir,
    parse_skill_metadata,
    is_canonical_id,
    is_safe_directory,
)

EN_COL = {
    "claude": "enabled_claude",
    "codex": "enabled_codex",
    "gemini": "enabled_gemini",
    "grokbuild": "enabled_grokbuild",
    "opencode": "enabled_opencode",
    "hermes": "enabled_hermes",
}
ENABLE_COLS = list(EN_COL.values())


class PipeError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def load_settings(home: Path) -> dict:
    p = home / ".cc-switch" / "settings.json"
    if not p.is_file():
        raise PipeError(f"missing settings: {p}")
    return json.loads(p.read_text())


def ssot_path(home: Path, settings: dict) -> Path:
    loc = settings.get("skillStorageLocation", "cc_switch")
    if loc == "unified":
        return home / ".agents" / "skills"
    return home / ".cc-switch" / "skills"


def sync_method(settings: dict) -> str:
    m = (settings.get("skillSyncMethod") or "auto").lower()
    if m not in ("auto", "symlink", "copy"):
        return "auto"
    return m


def app_skills_dir(home: Path, app: str) -> Path:
    try:
        return resolve_app_skills_dir(home, load_settings(home), app)
    except KeyError as exc:
        raise PipeError(str(exc)) from exc


def db_path(home: Path) -> Path:
    return home / ".cc-switch" / "cc-switch.db"


def lock_path(home: Path) -> Path:
    return home / ".agents" / ".skill-lock.json"


is_canonical = is_canonical_id


def assert_parent_not_link(app_dir: Path) -> None:
    if app_dir.exists() and app_dir.is_symlink():
        raise PipeError(f"FATAL parent-link: {app_dir} is symlink → migrate first", 1)


def precheck_all_apps(home: Path) -> None:
    for app in APP_DIRS_REL:
        d = app_skills_dir(home, app)
        if d.exists() or d.is_symlink():
            assert_parent_not_link(d)


def is_our_projection(dest: Path, ssot_leaf: Path, method: str) -> bool:
    """True if dest is safe to replace: our symlink or a directory we treat as projection."""
    if dest.is_symlink():
        try:
            target = Path(os.readlink(dest))
            if not target.is_absolute():
                target = (dest.parent / target).resolve()
            return target.resolve() == ssot_leaf.resolve()
        except OSError:
            return False
    if not dest.exists():
        return True
    if dest.is_dir() and method in ("copy", "auto"):
        # only remove if it looks like a skill dir (has SKILL.md) — never opaque trees
        return (dest / "SKILL.md").is_file()
    return False


def remove_projection(dest: Path, ssot_leaf: Path, method: str) -> None:
    if not dest.exists() and not dest.is_symlink():
        return
    if not is_our_projection(dest, ssot_leaf, method):
        raise PipeError(
            f"refusing to remove opaque path (not our projection): {dest}",
            1,
        )
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)


def sync_projection(
    ssot_leaf: Path, app_dir: Path, directory: str, method: str
) -> None:
    if not ssot_leaf.is_dir() or not (ssot_leaf / "SKILL.md").is_file():
        raise PipeError(f"SSOT missing SKILL.md: {ssot_leaf}")
    app_dir.mkdir(parents=True, exist_ok=True)
    assert_parent_not_link(app_dir)
    dest = app_dir / directory
    if method == "copy":
        remove_projection(dest, ssot_leaf, method)
        tmp = app_dir / f".tmp-{directory}-{os.getpid()}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(ssot_leaf, tmp)
        tmp.rename(dest)
        return
    # symlink or auto → prefer symlink
    if dest.exists() or dest.is_symlink():
        remove_projection(dest, ssot_leaf, method)
    try:
        dest.symlink_to(ssot_leaf)
    except OSError:
        if method == "symlink":
            raise
        # auto fallback copy
        remove_projection(dest, ssot_leaf, "copy")
        tmp = app_dir / f".tmp-{directory}-{os.getpid()}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(ssot_leaf, tmp)
        tmp.rename(dest)


def open_db(home: Path) -> sqlite3.Connection:
    p = db_path(home)
    if not p.is_file():
        raise PipeError(f"missing db: {p}")
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    return con


def skill_columns(con: sqlite3.Connection) -> set[str]:
    return {r[1] for r in con.execute("PRAGMA table_info(skills)")}


def get_skill(con: sqlite3.Connection, skill_id: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()


def write_lock_github(
    home: Path,
    directory: str,
    owner: str,
    repo: str,
    skill_path: str = "",
    branch: str = "main",
    folder_hash: str = "",
) -> None:
    lp = lock_path(home)
    lp.parent.mkdir(parents=True, exist_ok=True)
    if lp.is_file():
        data = json.loads(lp.read_text())
    else:
        data = {"version": 3, "skills": {}, "dismissed": {}}
    data.setdefault("skills", {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    previous = data["skills"].get(directory) or {}
    data["skills"][directory] = {
        "source": f"{owner}/{repo}",
        "sourceType": "github",
        "sourceUrl": f"https://github.com/{owner}/{repo}.git",
        "skillPath": skill_path or f"{directory}/SKILL.md",
        "branch": branch,
        "skillFolderHash": folder_hash,
        "installedAt": previous.get("installedAt", now),
        "updatedAt": now,
    }
    lp.write_text(json.dumps(data, indent=2) + "\n")


def refresh_lock_local(home: Path, directory: str, folder_hash: str) -> None:
    lp = lock_path(home)
    if not lp.is_file():
        return
    data = json.loads(lp.read_text())
    entry = (data.get("skills") or {}).get(directory)
    if not isinstance(entry, dict) or entry.get("sourceType") != "local":
        return
    entry["skillFolderHash"] = folder_hash or ""
    entry["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    lp.write_text(json.dumps(data, indent=2) + "\n")


def ensure_ssot_leaf(
    ssot: Path, directory: str, source_dir: Path | None, name: str
) -> Path:
    leaf = ssot / directory
    if source_dir is not None:
        source_dir = source_dir.resolve()
        if not (source_dir / "SKILL.md").is_file():
            raise PipeError(f"source missing SKILL.md: {source_dir}")
        if leaf.exists() and leaf.resolve() != source_dir.resolve():
            # copy contents into leaf
            leaf.mkdir(parents=True, exist_ok=True)
            for item in source_dir.iterdir():
                dest = leaf / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
        elif not leaf.exists():
            shutil.copytree(source_dir, leaf)
    else:
        leaf.mkdir(parents=True, exist_ok=True)
        skill_md = leaf / "SKILL.md"
        if not skill_md.is_file():
            skill_md.write_text(f"# {name}\n")
    if not (leaf / "SKILL.md").is_file():
        raise PipeError(f"SSOT leaf missing SKILL.md: {leaf}")
    return leaf


def register(
    home: Path,
    *,
    skill_id: str,
    directory: str,
    name: str | None = None,
    source_dir: Path | None = None,
    app: str | None = None,
    repo_owner: str | None = None,
    repo_name: str | None = None,
    repo_branch: str = "main",
    skill_path: str = "",
) -> None:
    if not is_canonical(skill_id):
        raise PipeError(f"non-canonical id: {skill_id!r}")
    if ":" in skill_id and not skill_id.startswith("local:"):
        expected_owner, expected_repo = skill_id.split(":", 1)[0].split("/", 1)
        if repo_owner and repo_owner != expected_owner:
            raise PipeError("repo owner does not match canonical id")
        if repo_name and repo_name != expected_repo:
            raise PipeError("repo name does not match canonical id")
    if not is_safe_directory(directory):
        raise PipeError(f"directory must be single path segment: {directory!r}")
    precheck_all_apps(home)
    settings = load_settings(home)
    ssot = ssot_path(home, settings)
    ssot.mkdir(parents=True, exist_ok=True)
    method = sync_method(settings)
    con = open_db(home)
    cols = skill_columns(con)
    existing = get_skill(con, skill_id)
    directory_owner = con.execute(
        "SELECT id FROM skills WHERE directory=? AND id<>?",
        (directory, skill_id),
    ).fetchone()
    if directory_owner:
        con.close()
        raise PipeError(
            f"directory already belongs to another skill: {directory!r}; use migrate"
        )
    if existing and "directory" in cols and existing["directory"] != directory:
        con.close()
        raise PipeError(
            "register cannot rename an existing skill; use migrate to preserve projections"
        )
    leaf = ensure_ssot_leaf(ssot, directory, source_dir, name or directory)
    metadata = parse_skill_metadata(leaf / "SKILL.md", directory)
    display = name or metadata.name
    description = metadata.description
    h = dir_hash(leaf)
    now = int(time.time())
    if existing:
        # preserve enables; update metadata only
        sets = ["name=?", "updated_at=?"]
        vals: list = [display, now]
        if "description" in cols:
            sets.append("description=?")
            vals.append(description)
        if repo_owner and "repo_owner" in cols:
            sets.append("repo_owner=?")
            vals.append(repo_owner)
        if repo_name and "repo_name" in cols:
            sets.append("repo_name=?")
            vals.append(repo_name)
        if h and "content_hash" in cols:
            sets.append("content_hash=?")
            vals.append(h)
        vals.append(skill_id)
        con.execute(f"UPDATE skills SET {', '.join(sets)} WHERE id=?", vals)
        con.commit()
    else:
        # park insert
        fields = ["id", "name", "directory"]
        values: list = [skill_id, display, directory]
        if "description" in cols:
            fields.append("description")
            values.append(description)
        if "repo_owner" in cols:
            fields.append("repo_owner")
            values.append(repo_owner)
        if "repo_name" in cols:
            fields.append("repo_name")
            values.append(repo_name)
        if "repo_branch" in cols:
            fields.append("repo_branch")
            values.append(repo_branch)
        for c in ENABLE_COLS:
            if c in cols:
                fields.append(c)
                values.append(0)
        if "installed_at" in cols:
            fields.append("installed_at")
            values.append(now)
        if "content_hash" in cols:
            fields.append("content_hash")
            values.append(h)
        if "updated_at" in cols:
            fields.append("updated_at")
            values.append(now)
        ph = ",".join("?" for _ in fields)
        con.execute(
            f"INSERT INTO skills ({','.join(fields)}) VALUES ({ph})",
            values,
        )
        con.commit()
    con.close()

    if repo_owner and repo_name:
        try:
            write_lock_github(
                home,
                directory,
                repo_owner,
                repo_name,
                skill_path,
                repo_branch,
                h or "",
            )
        except OSError as e:
            print(f"warn: lock write failed: {e}", file=sys.stderr)
    else:
        try:
            refresh_lock_local(home, directory, h or "")
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"warn: local lock refresh failed: {e}", file=sys.stderr)

    # never touch project-slot on register
    if app:
        dispatch(home, skill_id=skill_id, app=app, enabled=True)


def dispatch(home: Path, *, skill_id: str, app: str, enabled: bool) -> None:
    if app not in EN_COL:
        raise PipeError(f"unknown app: {app}")
    precheck_all_apps(home)
    settings = load_settings(home)
    ssot = ssot_path(home, settings)
    method = sync_method(settings)
    con = open_db(home)
    cols = skill_columns(con)
    col = EN_COL[app]
    if col not in cols:
        con.close()
        raise PipeError(f"DB missing column {col}")
    row = get_skill(con, skill_id)
    if row is None:
        con.close()
        raise PipeError(f"skill not found: {skill_id}")
    directory = row["directory"]
    leaf = ssot / directory
    app_dir = app_skills_dir(home, app)
    dest = app_dir / directory

    # official order: filesystem then DB
    if enabled:
        sync_projection(leaf, app_dir, directory, method)
    else:
        if dest.exists() or dest.is_symlink():
            remove_projection(dest, leaf, method)

    con.execute(
        f"UPDATE skills SET {col}=?, updated_at=? WHERE id=?",
        (1 if enabled else 0, int(time.time()), skill_id),
    )
    con.commit()
    con.close()
    # profiles intentionally untouched


# ---------- profiles / project-slot ----------

def load_profiles(con: sqlite3.Connection) -> list[dict]:
    """All profiles as {id, name, payload|None}; bad JSON → payload None."""
    try:
        rows = con.execute("SELECT id, name, payload FROM profiles").fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except Exception:
            payload = None
        out.append({"id": r["id"], "name": r["name"], "payload": payload})
    return out


def get_profile(con: sqlite3.Connection, name: str) -> dict | None:
    for p in load_profiles(con):
        if p["name"] == name:
            return p
    return None


def save_profile_payload(con: sqlite3.Connection, name: str, payload: dict) -> None:
    con.execute(
        "UPDATE profiles SET payload=?, updated_at=? WHERE name=?",
        (json.dumps(payload, ensure_ascii=False), int(time.time()), name),
    )
    con.commit()


def profile_skills(payload, app: str) -> list | None:
    """skills.<app> array, or None when unset / null / malformed."""
    if not isinstance(payload, dict):
        return None
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        return None
    arr = skills.get(app)
    return arr if isinstance(arr, list) else None


def slot_list(
    home: Path, *, profile: str | None = None, app: str | None = None
) -> None:
    con = open_db(home)
    ids = {r["id"] for r in con.execute("SELECT id FROM skills")}
    for p in load_profiles(con):
        if profile and p["name"] != profile:
            continue
        print(f"profile={p['name']!r}")
        if p["payload"] is None:
            print("  (bad JSON)")
            continue
        for a in sorted((p["payload"].get("skills") or {}).keys()):
            if app and a != app:
                continue
            arr = profile_skills(p["payload"], a)
            if arr is None:
                print(f"  {a}: (unset)")
                continue
            for sid in arr:
                flag = "" if sid in ids else "  # dangling"
                print(f"  {a}: {sid}{flag}")
    con.close()


def slot_scrub(
    home: Path, *, profile: str, app: str | None = None, apply: bool = False
) -> None:
    """Drop refs to ids that no DB row exists for (D13 remedy). JSON only."""
    if app is not None and app not in PROFILE_SKILL_APPS:
        raise PipeError(f"app has no cc-switch profile skill scope: {app}")
    con = open_db(home)
    ids = {r["id"] for r in con.execute("SELECT id FROM skills")}
    p = get_profile(con, profile)
    if p is None:
        con.close()
        raise PipeError(f"profile not found: {profile}")
    payload = p["payload"]
    if not isinstance(payload, dict):
        con.close()
        raise PipeError(f"profile {profile!r} bad JSON")
    skills = payload.setdefault("skills", {})
    apps = [app] if app else [a for a in PROFILE_SKILL_APPS if isinstance(skills.get(a), list)]
    removed = 0
    for a in apps:
        arr = skills.get(a)
        if not isinstance(arr, list):
            continue
        drop = [s for s in arr if s not in ids]
        if drop:
            for s in drop:
                print(f"  - {a}: {s}  # dangling")
            skills[a] = [s for s in arr if s not in drop]
            removed += len(drop)
    con.close()
    if not removed:
        print(f"profile={profile!r}: nothing to scrub")
        return
    if not apply:
        print(
            f"[dry-run] would scrub {removed} dangling ref(s) from "
            f"profile={profile!r} (--apply to write)"
        )
        return
    con = open_db(home)
    save_profile_payload(con, profile, payload)
    con.close()
    print(f"scrubbed {removed} dangling ref(s) from profile={profile!r}")


def slot_resnap(
    home: Path, *, profile: str, app: str, apply: bool = False
) -> None:
    """slot.<app> = live ids (enabled_*=1). JSON only; live untouched."""
    if app not in PROFILE_SKILL_APPS:
        raise PipeError(f"app has no cc-switch profile skill scope: {app}")
    con = open_db(home)
    col = EN_COL[app]
    live = sorted(
        r["id"]
        for r in con.execute(f"SELECT id FROM skills WHERE {col}=1")
    )
    p = get_profile(con, profile)
    if p is None:
        con.close()
        raise PipeError(f"profile not found: {profile}")
    payload = p["payload"]
    if not isinstance(payload, dict):
        con.close()
        raise PipeError(f"profile {profile!r} bad JSON")
    old = profile_skills(payload, app) or []
    added = [s for s in live if s not in old]
    dropped = [s for s in old if s not in live]
    if not added and not dropped:
        con.close()
        print(f"profile={profile!r} app={app}: already aligned ({len(old)})")
        return
    if not apply:
        for s in added:
            print(f"  + {app}: {s}")
        for s in dropped:
            print(f"  - {app}: {s}")
        print(
            f"[dry-run] would resnap profile={profile!r} app={app} "
            f"{len(old)}→{len(live)} (--apply to write)"
        )
        con.close()
        return
    skills = payload.setdefault("skills", {})
    skills[app] = live
    save_profile_payload(con, profile, payload)
    con.close()
    print(f"resnapped profile={profile!r} app={app}: {len(old)}→{len(live)}")


def _slot_touch(
    home: Path,
    *,
    profile: str,
    app: str,
    skill_id: str,
    add: bool,
    apply: bool,
) -> None:
    if not is_canonical(skill_id):
        raise PipeError(f"non-canonical id: {skill_id!r}")
    if app not in PROFILE_SKILL_APPS:
        raise PipeError(f"app has no cc-switch profile skill scope: {app}")
    con = open_db(home)
    known = get_skill(con, skill_id) is not None
    p = get_profile(con, profile)
    if p is None:
        con.close()
        raise PipeError(f"profile not found: {profile}")
    payload = p["payload"]
    if not isinstance(payload, dict):
        con.close()
        raise PipeError(f"profile {profile!r} bad JSON")
    skills = payload.setdefault("skills", {})
    arr = skills.get(app)
    if arr is None:
        arr = []
        skills[app] = arr
    if not isinstance(arr, list):
        con.close()
        raise PipeError(f"profile={profile!r} skills.{app} not list")
    if add:
        if skill_id in arr:
            con.close()
            print(f"already present: {skill_id}")
            return
        if not known:
            print(f"warn: {skill_id} has no DB row yet (register later)")
        if not apply:
            print(f"[dry-run] would add {app}: {skill_id} (--apply to write)")
            con.close()
            return
        arr.append(skill_id)
    else:
        if skill_id not in arr:
            con.close()
            print(f"not present: {skill_id}")
            return
        if not apply:
            print(f"[dry-run] would remove {app}: {skill_id} (--apply to write)")
            con.close()
            return
        arr.remove(skill_id)
    save_profile_payload(con, profile, payload)
    con.close()
    verb = "added" if add else "removed"
    print(f"{verb} {app}: {skill_id} on profile={profile!r}")


# ---------- uninstall / orphan cleanup ----------

def uninstall(
    home: Path, *, skill_id: str, keep_ssot: bool = False, apply: bool = False
) -> None:
    """Full uninstall; falls back to orphan cleanup when SSOT already gone.

    Plan: projections → lock key → SSOT dir → DB row. Profile snapshots remain intact.
    """
    precheck_all_apps(home)
    settings = load_settings(home)
    ssot = ssot_path(home, settings)
    method = sync_method(settings)
    con = open_db(home)
    row = get_skill(con, skill_id)
    if row is None:
        con.close()
        raise PipeError(f"skill not found: {skill_id} (nothing to uninstall)")
    directory = row["directory"]
    leaf = ssot / directory
    plan: list[str] = []
    lock_hit = False
    lock_data: dict = {}
    lp = lock_path(home)
    if lp.is_file():
        try:
            lock_data = json.loads(lp.read_text())
            lock_hit = directory in (lock_data.get("skills") or {})
        except Exception:
            pass
    for app in EN_COL:
        dest = app_skills_dir(home, app) / directory
        if dest.exists() or dest.is_symlink():
            plan.append(f"remove projection {dest}")
    if lock_hit:
        plan.append(f"remove lock key {directory!r}")
    orphan = not leaf.exists()
    if leaf.exists():
        plan.append(f"remove SSOT {leaf}" if not keep_ssot else f"keep SSOT {leaf}")
    else:
        plan.append(f"SSOT {leaf} already missing — orphan path (row/projections/slot only)")
    if not apply:
        print("[dry-run] uninstall plan:")
        for l in plan:
            print("  " + l)
        con.close()
        return
    if orphan:
        print(
            f"SSOT {leaf} already missing — orphan path "
            f"(row/projections/slot only)"
        )
    for app in EN_COL:
        dest = app_skills_dir(home, app) / directory
        if dest.exists() or dest.is_symlink():
            remove_projection(dest, leaf, method)
    if lock_hit:
        lock_data.get("skills", {}).pop(directory, None)
        lp.write_text(json.dumps(lock_data, indent=2) + "\n")
    if leaf.exists() and not keep_ssot:
        shutil.rmtree(leaf)
    con.execute("DELETE FROM skills WHERE id=?", (skill_id,))
    con.commit()
    con.close()
    print(f"uninstalled {skill_id} (directory={directory})")


def migrate(home: Path, request: MigrationRequest) -> None:
    if not is_canonical(request.target_id):
        raise PipeError(f"non-canonical target id: {request.target_id!r}")
    if not is_safe_directory(request.directory):
        raise PipeError(f"directory must be single path segment: {request.directory!r}")
    precheck_all_apps(home)
    settings = load_settings(home)
    ssot = ssot_path(home, settings)
    method = sync_method(settings)
    con = open_db(home)
    row = get_skill(con, request.source_id)
    if row is None:
        con.close()
        raise PipeError(f"skill not found: {request.source_id}")
    conflict = get_skill(con, request.target_id)
    if conflict is not None and request.target_id != request.source_id:
        con.close()
        raise PipeError(f"target id already exists: {request.target_id}")
    directory_conflict = con.execute(
        "SELECT id FROM skills WHERE directory=? AND id<>?",
        (request.directory, request.source_id),
    ).fetchone()
    if directory_conflict:
        con.close()
        raise PipeError(f"target directory already belongs to another skill: {request.directory!r}")

    source_directory = row["directory"]
    source_leaf = ssot / source_directory
    target_leaf = ssot / request.directory
    if source_directory != request.directory:
        if source_leaf.exists() and target_leaf.exists():
            con.close()
            raise PipeError(f"both source and target SSOT directories exist: {source_leaf}, {target_leaf}")
        if not source_leaf.exists() and not target_leaf.exists():
            con.close()
            raise PipeError(f"neither source nor target SSOT directory exists: {source_leaf}, {target_leaf}")
    elif not source_leaf.exists():
        con.close()
        raise PipeError(f"SSOT directory missing: {source_leaf}")

    projection_moves: list[tuple[str, Path]] = []
    for app in EN_COL:
        source_projection = app_skills_dir(home, app) / source_directory
        if source_projection.exists() or source_projection.is_symlink():
            if not is_our_projection(source_projection, source_leaf, method):
                con.close()
                raise PipeError(f"refusing to migrate opaque projection: {source_projection}")
            projection_moves.append((app, source_projection))

    profile_updates = 0
    for profile in load_profiles(con):
        payload = profile["payload"]
        if not isinstance(payload, dict):
            continue
        skills = payload.get("skills")
        if not isinstance(skills, dict):
            continue
        if any(isinstance(ids, list) and request.source_id in ids for ids in skills.values()):
            profile_updates += 1

    print("[dry-run] migrate plan:" if not request.apply else "migrate plan:")
    print(f"  id {request.source_id} -> {request.target_id}")
    print(f"  directory {source_directory} -> {request.directory}")
    print(f"  preserve enable flags; rewrite {profile_updates} profile snapshot(s)")
    if not request.apply:
        con.close()
        return

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = db_path(home).with_name(f"cc-switch.db.pre-skill-migrate-{stamp}")
    shutil.copy2(db_path(home), backup)
    renamed_leaf = False
    if source_directory != request.directory and source_leaf.exists():
        source_leaf.rename(target_leaf)
        renamed_leaf = True
    active_leaf = target_leaf if source_directory != request.directory else source_leaf
    content_hash = dir_hash(active_leaf)
    try:
        for app, column in EN_COL.items():
            if column in row.keys() and row[column]:
                sync_projection(active_leaf, app_skills_dir(home, app), request.directory, method)
        con.execute("BEGIN IMMEDIATE")
        updates = ["id=?", "name=?", "directory=?", "content_hash=?", "updated_at=?"]
        values: list[object] = [
            request.target_id,
            request.name or row["name"],
            request.directory,
            content_hash,
            int(time.time()),
        ]
        if ":" in request.target_id and not request.target_id.startswith("local:"):
            owner, repo = request.target_id.split(":", 1)[0].split("/", 1)
            if "repo_owner" in row.keys():
                updates.append("repo_owner=?")
                values.append(owner)
            if "repo_name" in row.keys():
                updates.append("repo_name=?")
                values.append(repo)
        values.append(request.source_id)
        con.execute(
            f"UPDATE skills SET {', '.join(updates)} WHERE id=?",
            values,
        )
        for profile in load_profiles(con):
            payload = profile["payload"]
            if not isinstance(payload, dict):
                continue
            skills = payload.get("skills")
            if not isinstance(skills, dict):
                continue
            changed = False
            for app, ids in skills.items():
                if app not in PROFILE_SKILL_APPS:
                    continue
                if isinstance(ids, list) and request.source_id in ids:
                    skills[app] = [request.target_id if sid == request.source_id else sid for sid in ids]
                    changed = True
            if changed:
                con.execute(
                    "UPDATE profiles SET payload=?, updated_at=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), int(time.time()), profile["id"]),
                )
        con.commit()
    except (OSError, sqlite3.Error):
        con.rollback()
        if renamed_leaf and target_leaf.exists() and not source_leaf.exists():
            target_leaf.rename(source_leaf)
        con.close()
        raise
    con.close()

    archive_root = home / ".cc-switch" / "skill-backups" / f"adapter-migrate-{stamp}"
    for app, source_projection in projection_moves:
        if source_directory == request.directory or not (
            source_projection.exists() or source_projection.is_symlink()
        ):
            continue
        archive_root.mkdir(parents=True, exist_ok=True)
        source_projection.rename(archive_root / f"{app}-{source_directory}")

    lp = lock_path(home)
    if lp.is_file() and source_directory != request.directory:
        lock_data = json.loads(lp.read_text())
        lock_skills = lock_data.setdefault("skills", {})
        if source_directory in lock_skills and request.directory not in lock_skills:
            lock_skills[request.directory] = lock_skills.pop(source_directory)
        if request.directory in lock_skills:
            lock_skills[request.directory]["skillFolderHash"] = content_hash or ""
            lock_skills[request.directory]["updatedAt"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()
            )
        lp.write_text(json.dumps(lock_data, indent=2) + "\n")
    print(f"migrated {request.source_id} -> {request.target_id}; backup={backup}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipe.py", description="closed-pipe register/dispatch")
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="fake home root (default: real home)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("register", help="SSOT + DB park or install-enable")
    pr.add_argument("--id", required=True, help="canonical-id")
    pr.add_argument("--directory", required=True, help="SSOT leaf name (one segment)")
    pr.add_argument("--name", default=None)
    pr.add_argument("--source", type=Path, default=None, help="copy from this dir into SSOT")
    pr.add_argument("--app", default=None, help="if set: install-enable this app")
    pr.add_argument("--repo-owner", default=None)
    pr.add_argument("--repo-name", default=None)
    pr.add_argument("--repo-branch", default="main")
    pr.add_argument("--skill-path", default="")

    pd = sub.add_parser("dispatch", help="toggle one app live on/off")
    pd.add_argument("--id", required=True)
    pd.add_argument("--app", required=True)
    g = pd.add_mutually_exclusive_group(required=True)
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")

    ps = sub.add_parser("slot", help="project-slot JSON ops (profiles only, never live)")
    ssub = ps.add_subparsers(dest="slot_cmd", required=True)
    psl = ssub.add_parser("list", help="show profile skill refs, mark dangling")
    psl.add_argument("--profile", default=None)
    psl.add_argument("--app", default=None)
    psc = ssub.add_parser("scrub", help="drop refs with no DB row (D13)")
    psc.add_argument("--profile", required=True)
    psc.add_argument("--app", default=None)
    psc.add_argument("--apply", action="store_true")
    psr = ssub.add_parser("resnap", help="slot = live (enabled_*=1), JSON only")
    psr.add_argument("--profile", required=True)
    psr.add_argument("--app", required=True)
    psr.add_argument("--apply", action="store_true")
    psa = ssub.add_parser("add", help="append a canonical ref")
    psa.add_argument("--profile", required=True)
    psa.add_argument("--app", required=True)
    psa.add_argument("--id", required=True)
    psa.add_argument("--apply", action="store_true")
    psd = ssub.add_parser("remove", help="remove a ref")
    psd.add_argument("--profile", required=True)
    psd.add_argument("--app", required=True)
    psd.add_argument("--id", required=True)
    psd.add_argument("--apply", action="store_true")

    pu = sub.add_parser("uninstall", help="remove skill + projections + lock + slot refs")
    pu.add_argument("--id", required=True)
    pu.add_argument("--keep-ssot", action="store_true")
    pu.add_argument("--apply", action="store_true")

    pm = sub.add_parser("migrate", help="rename canonical id/directory without losing live or slots")
    pm.add_argument("--from-id", required=True)
    pm.add_argument("--to-id", required=True)
    pm.add_argument("--directory", required=True)
    pm.add_argument("--name", default=None)
    pm.add_argument("--apply", action="store_true")

    args = p.parse_args(argv)
    home = (args.root or Path.home()).expanduser().resolve()
    try:
        if args.cmd == "register":
            register(
                home,
                skill_id=args.id,
                directory=args.directory,
                name=args.name,
                source_dir=args.source,
                app=args.app,
                repo_owner=args.repo_owner,
                repo_name=args.repo_name,
                repo_branch=args.repo_branch,
                skill_path=args.skill_path,
            )
            mode = f"install-enable app={args.app}" if args.app else "park"
            print(f"register ok id={args.id} directory={args.directory} mode={mode}")
        elif args.cmd == "dispatch":
            dispatch(
                home,
                skill_id=args.id,
                app=args.app,
                enabled=bool(args.enable),
            )
            print(
                f"dispatch ok id={args.id} app={args.app} "
                f"enabled={bool(args.enable)}"
            )
        elif args.cmd == "slot":
            if args.slot_cmd == "list":
                slot_list(home, profile=args.profile, app=args.app)
            elif args.slot_cmd == "scrub":
                slot_scrub(
                    home,
                    profile=args.profile,
                    app=args.app,
                    apply=args.apply,
                )
            elif args.slot_cmd == "resnap":
                slot_resnap(
                    home, profile=args.profile, app=args.app, apply=args.apply
                )
            elif args.slot_cmd == "add":
                _slot_touch(
                    home,
                    profile=args.profile,
                    app=args.app,
                    skill_id=args.id,
                    add=True,
                    apply=args.apply,
                )
            elif args.slot_cmd == "remove":
                _slot_touch(
                    home,
                    profile=args.profile,
                    app=args.app,
                    skill_id=args.id,
                    add=False,
                    apply=args.apply,
                )
        elif args.cmd == "uninstall":
            uninstall(
                home,
                skill_id=args.id,
                keep_ssot=args.keep_ssot,
                apply=args.apply,
            )
            return 0
        elif args.cmd == "migrate":
            migrate(
                home,
                MigrationRequest(
                    source_id=args.from_id,
                    target_id=args.to_id,
                    directory=args.directory,
                    name=args.name,
                    apply=args.apply,
                ),
            )
            return 0
    except PipeError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
