# cc-switch-adapter

Agent 侧 **closed-pipe**：**park**（未点名 app）或 **install-enable**（点名 app）；**live** = 现在开了什么；**fat snapshot** → slot 卫生，不自动 enable。

**runtime-first**：本机 DB/settings/磁盘。

**查→治→查**：`doctor` 只读诊断 → `remedy` 按 findings 分发修复 → `doctor` 复验。

```bash
python3 doctor.py                         # 体检
python3 remedy.py --apply                 # 治疗闭环（默认 dry-run）
python3 pipe.py register --id local:x --directory x --source ./x
python3 pipe.py dispatch --id local:x --app claude --enable
python3 pipe.py slot list|scrub|resnap|add|remove   # slot 治理（dry-run 默认）
python3 pipe.py uninstall --id local:x --apply      # 卸载 ∪ 孤儿清理
python3 content_hash.py ~/.agents/skills/x
python3 -m unittest discover -s tests -v
```

见 [SKILL.md](SKILL.md)。参考：`pipe.py` · `doctor.py` · `remedy.py` · `content_hash.py` · `experience.md` · `project-slot.md` · `db-schema.md` · `file-layout.md` · `lock-file.md`。

MIT。cc-switch 版权归其作者。
