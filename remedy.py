#!/usr/bin/env python3
"""cc-switch-adapter remedy — doctor findings → treatment (查→治→查闭环).

doctor 只读（查）；remedy 按 findings 分发修复（治）：

  auto-fix（安全、可逆、语义明确）:
    D9.live-link      → dispatch --enable    （enable 但投影缺失）
    D10.park-leak     → dispatch --disable   （disable 但 SSOT-link 残留）
    D13.slot-dangling → slot scrub           （slot 引用无 DB 行）

  suggest（用户决策 / 有歧义，只打印命令）:
    D6.ssot-db      → uninstall（清残留） 或 register（重建）
    D7.db-ssot-orphan → register
    D14.slot-id     → slot remove（非 canonical 引用）
    D4/D11/D3/D0/D1 → migrate
    D15.fat-snapshot → slot resnap（需用户点名项目）

默认 --dry-run：只打印计划；--apply：执行 auto-fix。
完成后重跑 doctor 验证（查→治→查）。

stdlib only。执行路径复用 pipe.py（单一真相）。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor as doclib  # noqa: E402
import pipe as pipe  # noqa: E402

RE_DISPATCH = re.compile(r"id=(\S+) app=(\S+)")
# doctor msg: profile='X' app=Y id='Z' — only profile/id get !r quotes
RE_SLOT = re.compile(r"profile='(.*?)' app=(\S+) id='(.*?)'")

SUGGEST_VERB = {
    "D3.parent-link": "migrate",
    "D4.canonical-id": "migrate",
    "D4.directory": "migrate",
    "D11.dup-directory": "migrate",
    "D0.runtime": "migrate",
    "D1.schema": "migrate",
}


def _cmd_uninstall(sid: str) -> str:
    return f"python3 {Path(pipe.__file__).name} uninstall --id {sid!r} --apply"


def _cmd_register(name: str, ssot: Path) -> str:
    leaf = ssot / name
    return (
        f"python3 {Path(pipe.__file__).name} register "
        f"--id 'local:{name}' --directory {name} --source {leaf} "
        f"[--app claude]"
    )


def plan_findings(findings: list, ssot: Path) -> list[dict]:
    """Map doctor findings to actions: kind ∈ auto | cmd | skip."""
    plan: list[dict] = []
    for lv, cat, code, msg in findings:
        if lv == "OK":
            continue  # OK rows land in doctor findings too — never actionable
        if code.startswith("D9.live-link"):
            m = RE_DISPATCH.search(msg)
            if m:
                plan.append(
                    {
                        "kind": "auto",
                        "code": code,
                        "msg": msg,
                        "fn": lambda sid=m.group(1), app=m.group(2): pipe.dispatch(
                            home=_HOME, skill_id=sid, app=app, enabled=True
                        ),
                        "desc": f"dispatch enable id={m.group(1)} app={m.group(2)}",
                    }
                )
            continue
        if code.startswith("D10.park-leak"):
            m = RE_DISPATCH.search(msg)
            if m:
                plan.append(
                    {
                        "kind": "auto",
                        "code": code,
                        "msg": msg,
                        "fn": lambda sid=m.group(1), app=m.group(2): pipe.dispatch(
                            home=_HOME, skill_id=sid, app=app, enabled=False
                        ),
                        "desc": f"dispatch disable id={m.group(1)} app={m.group(2)}",
                    }
                )
            continue
        if code.startswith("D13.slot-dangling"):
            m = RE_SLOT.search(msg)
            if m:
                plan.append(
                    {
                        "kind": "auto",
                        "code": code,
                        "msg": msg,
                        "fn": lambda prof=m.group(1): pipe.slot_scrub(
                            home=_HOME, profile=prof, apply=True
                        ),
                        "desc": f"slot scrub profile={m.group(1)!r} "
                        f"app={m.group(2)!r} id={m.group(3)!r}",
                    }
                )
            continue
        if code.startswith("D6.ssot-db"):
            m = re.search(r"id=(\S+)", msg)
            sid = m.group(1) if m else None
            plan.append(
                {
                    "kind": "cmd",
                    "code": code,
                    "msg": msg,
                    "cmd": _cmd_uninstall(sid) if sid else "inspect",
                    "alt": _cmd_register(sid.removeprefix("local:"), ssot)
                    if sid and sid.startswith("local:")
                    else None,
                }
            )
            continue
        if code.startswith("D7.db-ssot-orphan"):
            name = msg.split("SSOT/", 1)[-1].split(" ")[0]
            plan.append(
                {
                    "kind": "cmd",
                    "code": code,
                    "msg": msg,
                    "cmd": _cmd_register(name, ssot),
                }
            )
            continue
        if code.startswith("D14.slot-id"):
            m = RE_SLOT.search(msg)
            if m:
                plan.append(
                    {
                        "kind": "cmd",
                        "code": code,
                        "msg": msg,
                        "cmd": (
                            f"python3 {Path(pipe.__file__).name} slot remove "
                            f"--profile {m.group(1)!r} --app {m.group(2)} "
                            f"--id {m.group(3)!r} --apply"
                        ),
                    }
                )
            continue
        if code.startswith("D15.fat-snapshot"):
            plan.append(
                {
                    "kind": "skip",
                    "code": code,
                    "msg": msg,
                    "why": "policy — user-named project resnap only",
                }
            )
            continue
        verb = SUGGEST_VERB.get(code)
        if verb:
            plan.append(
                {"kind": "cmd", "code": code, "msg": msg, "cmd": f"migrate ({verb})"}
            )
            continue
        plan.append(
            {"kind": "skip", "code": code, "msg": msg, "why": "hygiene/info"}
        )
    return plan


_HOME: Path | None = None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="cc-switch-adapter remedy (doctor findings → treatment)"
    )
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--apply", action="store_true", help="execute auto-fix items")
    p.add_argument("--full", action="store_true", help="doctor --full hash check")
    args = p.parse_args(argv)
    global _HOME
    _HOME = (args.root or Path.home()).expanduser().resolve()

    # 查
    d = doclib.Doctor(home=_HOME, full_hash=args.full)
    d.run()
    if not d.findings:
        print("\nremedy: no findings")
        return 0
    plan = plan_findings(d.findings, d.ssot)
    autos = [it for it in plan if it["kind"] == "auto"]
    cmds = [it for it in plan if it["kind"] == "cmd"]
    skips = [it for it in plan if it["kind"] == "skip"]

    print(f"\nremedy {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    for it in autos:
        print(f"[AUTO] {it['code']}  {it['desc']}")
    for it in cmds:
        print(f"[CMD ] {it['code']}  {it['cmd']}")
        if it.get("alt"):
            print(f"       alt: {it['alt']}")
    for it in skips:
        print(f"[SKIP] {it['code']}  {it['why']}")

    if not autos:
        print("\nremedy: no auto-fix items — run suggested commands, then doctor")
        return 0
    if not args.apply:
        print(
            f"\n[dry-run] {len(autos)} auto-fix item(s) pending "
            f"(--apply to execute)"
        )
        return 0

    print()
    for it in autos:
        try:
            it["fn"]()
            print(f"[FIXED] {it['code']}  {it['desc']}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL ] {it['code']}  {it['desc']}: {e}")

    # 复验（查→治→查）
    print("\ndoctor recheck:")
    d2 = doclib.Doctor(home=_HOME, full_hash=False)
    d2.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
