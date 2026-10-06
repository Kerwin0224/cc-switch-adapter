# cc-switch-adapter

Agent 侧 **closed-pipe**：**park**（未点名 app）或 **install-enable**（点名 app）；**live** = 现在开了什么；**fat snapshot** → slot 卫生，不自动 enable。

**runtime-first**：本机 DB/settings/磁盘。**主力 pair**（skill）：claude-code / codex
默认同开同关；`gemini` / `grokbuild` / `opencode` 默认关。Hermes 由用户直接管理、
没有 profile 概念，只按明确指令 dispatch；profile = 场景，只装该场景要用的 skill。
**MCP**：MCP 逐 app 治理；Codex 由 native 配置自管，其他 app 保留其已验证快照。
新增、恢复或变更 MCP 时见 `mcp-governance.md`。

**查→盘→判→治→查**：`doctor` 只读基线 → `inventory` 全量盘点（开/关 + 场景槽位）
→ 判「应该开/关」→ `remedy`/`pipe` 按清单修复 → `doctor` + `inventory` 复验。

```bash
python3 doctor.py                         # 体检
python3 inventory.py --profile 开发        # 盘点：skill × app live + 场景差分
python3 remedy.py --apply                 # 治疗闭环（默认 dry-run）
python3 pipe.py register --id local:x --directory x --source ./x
python3 pipe.py dispatch --id local:x --app claude --enable
python3 pipe.py slot list|scrub|resnap|add|remove   # slot 治理（dry-run 默认）
python3 pipe.py uninstall --id local:x --apply      # 卸载 ∪ 孤儿清理
python3 content_hash.py ~/.agents/skills/x
python3 -m unittest discover -s tests -v
```

见 [SKILL.md](SKILL.md)。参考：`pipe.py` · `doctor.py` · `remedy.py` · `content_hash.py` · `experience.md` · `project-slot.md` · `db-schema.md` · `file-layout.md` · `lock-file.md`。

## 开发（直接在 agent 目录）

**改动直接落在 agent 目录**：`~/.agents/skills/cc-switch-adapter/`。它同时是 SSOT 和开发处——
`skillStorageLocation=unified` 下 SSOT 就是 `~/.agents/skills`，各 app 目录只是它的符号链接
（同一 inode），改一处即到处生效。

1. 在 agent 目录里改；
2. 自测：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`；
3. `doctor.py` + `inventory.py` 复验。

GitHub（`Kerwin0224/cc-switch-adapter`）是**发布出口，不是改动入口**——不需要 clone 再
rsync 回 SSOT 那一圈。`doctor.py --remote` 的 R3 只用来发现**上游别人的** skill 过时，
不约束本 adapter 自己的开发。

MIT。cc-switch 版权归其作者。
