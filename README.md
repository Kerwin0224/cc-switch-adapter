# cc-switch-adapter

Agent 侧 **closed-pipe**：**park**（未点名 app）或 **install-enable**（点名 app）；**live** = 现在开了什么；**fat snapshot** → slot 卫生，不自动 enable。

**runtime-first**：本机 DB/settings/磁盘。**主力 pair**（skill）：claude-code / codex
默认同开同关；其余 app（含 opencode，已解耦）默认关；profile = 场景，只装该场景要用的 skill。
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

## 维护者工作流（仓库 → SSOT）

本仓库是 adapter 唯一的改动入口；SSOT（cc-switch `skillStorageLocation` 下的
adapter 目录）永远只是下游，任何人都不直接编辑 SSOT 内容。

1. clone 本仓库到任意位置，在 clone 里改动；
2. 自测：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`；
3. push；
4. 把这次改动当一次普通 R3 更新刷进 SSOT：`doctor --remote` 对本仓库报
   R3 differs → 走 `experience.md`「R3.stale 的更新流程」（rsync 覆盖 +
   刷 content_hash）；canonical id 以 DB 行（repo_owner/repo_name）为准；
5. `doctor` + `inventory` 复验。

用户（非维护者）视角更简单：从不改 SSOT，R3 differs 即真落后，按流程刷新——
experience.md 第 0 步的方向判定只对「SSOT 被违规手改」的罕见情况停手。

MIT。cc-switch 版权归其作者。
