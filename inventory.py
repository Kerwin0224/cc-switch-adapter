#!/usr/bin/env python3
"""cc-switch-adapter inventory - read-only scan: every skill x every app + profile slots.

Output:
  - table: one row per skill, live state per app, SSOT directory
  - policy seams: non-trio live (default off) and trio drift
    (claude/codex/opencode differ - default should be on all three or none)
  - profiles: slot counts; with --profile NAME, per-ref diff
    (live / slot-only / dangling)

Never writes DB, lock, SSOT, or projections. Exit 0 unless runtime is unreadable.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

EN_COL = {
    "claude": "enabled_claude",
    "codex": "enabled_codex",
    "gemini": "enabled_gemini",
    "grokbuild": "enabled_grokbuild",
    "opencode": "enabled_opencode",
    "hermes": "enabled_hermes",
}
APPS = list(EN_COL)
TRIO = ("claude", "codex", "opencode")
NON_TRIO = [app for app in APPS if app not in TRIO]
SLOT_APPS = ("claude", "codex")


def load_settings(home: Path) -> dict:
    p = home / ".cc-switch" / "settings.json"
    if not p.is_file():
        raise SystemExit("error: missing settings: " + str(p))
    return json.loads(p.read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="inventory.py", description="read-only skill inventory (never writes)"
    )
    ap.add_argument("--root", type=Path, default=None,
                    help="fake home root (default: real home)")
    ap.add_argument("--profile", action="append", default=[], metavar="NAME",
                    help="diff this profile claude/codex slots vs live (repeatable)")
    args = ap.parse_args(argv)
    home = (args.root or Path.home()).expanduser().resolve()

    settings = load_settings(home)
    loc = settings.get("skillStorageLocation", "cc_switch")
    ssot = home / (".agents" if loc == "unified" else ".cc-switch") / "skills"
    db = home / ".cc-switch" / "cc-switch.db"
    if not db.is_file():
        raise SystemExit("error: missing db: " + str(db))

    try:
        con = sqlite3.connect(db)
        skill_rows = list(con.execute(
            "SELECT id, name, directory, enabled_claude, enabled_codex, "
            "enabled_gemini, enabled_grokbuild, enabled_opencode, enabled_hermes "
            "FROM skills ORDER BY directory, id"
        ))
        profile_rows = list(con.execute(
            "SELECT id, name, payload FROM profiles ORDER BY name"
        ))
    except sqlite3.Error as exc:
        raise SystemExit("error: " + str(exc)) from exc
    finally:
        con.close()

    rows = []
    for rid, _name, directory, *flags in skill_rows:
        en = dict(zip(APPS, (bool(f) for f in flags)))
        rows.append({"id": rid, "directory": directory, "en": en})

    live = {app: {r["id"] for r in rows if r["en"][app]} for app in APPS}
    all_ids = {r["id"] for r in rows}

    profiles = []
    for _pid, name, raw in profile_rows:
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        slots = payload.get("skills") or {}
        profiles.append({
            "name": name,
            "claude": slots.get("claude") if isinstance(slots.get("claude"), list) else None,
            "codex": slots.get("codex") if isinstance(slots.get("codex"), list) else None,
        })

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("inventory " + stamp)
    sync = settings.get("skillSyncMethod", "auto")
    print("baseline: ssot=" + str(ssot) + " sync=" + str(sync) + " skills=" + str(len(rows))
          + " profiles=" + str(len(profiles)) + " apps=" + ",".join(APPS))
    print()

    print("{:<60} {:>3} {:>3} {:>3} {:>3} {:>3} {:>3}  DIRECTORY".format(
        "ID", "CL", "CX", "GE", "GB", "OP", "HE"))
    for r in rows:
        marks = "".join((" on" if r["en"][app] else "  .") for app in APPS)
        print("{:<60} {}  {}".format(r["id"], marks, r["directory"]))
    print()

    non_trio = [r for r in rows if any(r["en"][app] for app in NON_TRIO)]
    print("policy: non-trio live (default off)  " + str(len(non_trio)))
    for r in non_trio:
        on = [app for app in NON_TRIO if r["en"][app]]
        print("  on " + ",".join(a.upper() for a in on) + "  " + r["id"])

    drift = []
    for r in rows:
        on = [app for app in TRIO if r["en"][app]]
        if on and len(on) < len(TRIO):
            drift.append((r, on))
    print("policy: trio drift (claude/codex/opencode differ)  " + str(len(drift)))
    for r, on in drift:
        print("  on " + ",".join(a.upper() for a in on) + "  " + r["id"])
    print()

    wanted = set(args.profile)
    selected = [p for p in profiles if not wanted or p["name"] in wanted]
    for p in selected:
        cl = p["claude"]
        cx = p["codex"]
        print("profile: " + p["name"] + "  claude=" + str(len(cl) if cl is not None else "null")
              + "  codex=" + str(len(cx) if cx is not None else "null"))
        for app in SLOT_APPS:
            refs = p[app]
            if refs is None:
                print("  " + app + ": never captured (null)")
                continue
            print("  " + app + ": " + str(len(refs)) + " refs")
            for ref in refs:
                if ref not in all_ids:
                    print("    [dangling]   " + ref)
                elif ref in live[app]:
                    print("    [live]       " + ref)
                else:
                    print("    [slot-only]  " + ref)
        print()

    counts = "  ".join(app + " " + str(len(live[app])) for app in APPS)
    print("summary: skills=" + str(len(rows)) + "  profiles=" + str(len(profiles))
          + "  live: " + counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
