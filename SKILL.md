---
name: cc-switch-adapter
description: >
  closed-pipe adapter for registering, migrating, dispatching, diagnosing, and
  explicitly governing skills and MCP servers through cc-switch. Use for skill
  installation, scenario-profile design (建立/维护/完善 a profile: which skills
  should be live), MCP per-app enablement, harness compatibility, profile
  changes, canonical IDs, SSOT projections, or parent-link failures.
---

# cc-switch adapter

`closed-pipe` means every mutation has one explicit route: cc-switch's unified
SSOT, one canonical DB row, per-app enable columns, and child projections.
Runtime state is authoritative: read `settings.json`, the DB schema, and the
filesystem before using repository documentation.

**MCP branch**: Before registering, enabling, disabling, recovering, or
onboarding an MCP through cc-switch, read `mcp-governance.md`. Its MCP-specific
per-app policy takes priority over the skill-only claude/codex pair rule; it defines the
Codex native Overlay, naming contract, recovery evidence, and new-harness path.

## 规矩（先对齐，再动手）

- **主力 pair**：claude-code / codex 默认同开同关；其余受管 app
  （opencode / gemini / grokbuild）默认关闭。opencode 已从 skill 治理解耦
  （2026-08-25），与普通受管 app 同待遇。
- **Hermes 用户自管**：Hermes 没有 profile / 项目场景，不套用默认开关或
  slot 对齐；仅按用户明确指令 `dispatch`。doctor 仍检查 SSOT、DB 与投影完整性。
- **场景 = profile**：每个 profile 是一个场景（开发 / 求职 / 办公 / 视频 /
  运维 / GSW…），只装该场景要用的 skill；通用核心（本 adapter、
  writing-for-agents）随每个场景。
- 任何「该开 / 不该开」先对齐以上规则；偏离要列明理由并等用户确认，
  绝不自行扩大或收缩 live。
- **报告说人话**：向用户汇报 doctor / inventory 结果时，每条 finding 用一句中文
  讲清「什么问题、影响、下一步」；D15 / D8 这类编号只作与 doctor.md 对照的附注，
  不单独裸报。命令动词（migrate / dispatch / slot …）保持原样。

## 场景 profile 工作流（查→盘→判→治→查）

把「现状」带到「应该」的 closed-pipe 闭环：先读后动，每步有完成准则。

### 1 查 baseline（只读）

```bash
python3 "$SKILL_DIR/doctor.py"           # runtime-first 基线：finding + next:
python3 "$SKILL_DIR/doctor.py" --remote  # 可选：云端新鲜度 R1-R3
```

`SKILL_DIR` 是本 skill 安装目录；`--root` 只用于隔离的假 home。app `skills`
父目录是 symlink = 致命 parent-link 条件，先 `migrate` 再动任何东西。
`--remote` 是报告专用 seam：R1 仓库存在/归档、R2 路径漂移、R3 过时、
R3.self adapter 自身领先；不产生 FATAL、不改 `next:`，离线降级为单条 WARN。

完成准则：拿到 baseline——SSOT 路径、sync 方式、live 行数、全部 finding 与
`next:`。FATAL / design ERROR 先记入清单，本步不修。

### 2 盘 inventory（只读，扫全部 skill）

```bash
python3 "$SKILL_DIR/inventory.py"                 # 全表：skill × app live + 场景槽位
python3 "$SKILL_DIR/inventory.py" --profile <场景>   # 加：该场景槽位 vs live 差分
```

完成准则：得到两份答案——① 目前哪些开了、哪些没开（逐 app）；② 目标场景
槽位里哪些 live、哪些只有槽位、哪些悬空。本步零写入。

### 3 判 verdict（只读，得出「应该」）

对照全表逐条给出「应该开 / 应该关」：

- **主力 pair**：受管 non-pair app（opencode / gemini / grokbuild）上的 live
  默认该关；claude 与 codex 默认同开同关，不一致（pair drift）是待对齐项。
- **Hermes**：保持用户当前选择，不纳入 profile verdict 或 pair 对齐。
- **场景**：按目标 profile 的场景挑 skill——场景要用的该开、已开但场景不
  需要的该关、场景需要但未装的先 `register`。
- 每条写明依据（policy / 场景 / 依赖），组成待办清单。

完成准则：清单覆盖全表所有差异，每条有依据，没有「感觉」项。

### 4 治 act（用户点名的 closed-pipe 动词）

```bash
python3 "$SKILL_DIR/pipe.py" dispatch --id ID --app claude --enable|--disable
python3 "$SKILL_DIR/pipe.py" slot add|remove|resnap|scrub --profile <场景> ...
python3 "$SKILL_DIR/pipe.py" register|migrate|uninstall ...
python3 "$SKILL_DIR/remedy.py" [--apply]          # doctor finding 的闭环修复
```

- profile 槽位只改 profiles JSON，永不直接改 live；live 只经 `dispatch`
  或用户明确 apply。
- **pair 同步**：live 集合以 profile 槽位（claude / codex）为准；opencode
  不参与 skill 对齐并保持默认关；Hermes 无 profile，仅按用户明确指令 dispatch。
- **R3.stale（云端过时）** 只针对**上游别人的** skill：按 experience.md「R3.stale
  的更新流程」刷新（rsync 覆盖 + 刷 hash，禁 uninstall+register 刷版本）。
  **本 adapter 自身的开发直接改 agent 目录**——SSOT 就是开发处，没有
  clone → push → 刷新这一圈。
- 完成准则：清单每一项落一个动词；未确认的偏离保持原状并报告。

### 5 复验（只读）

```bash
python3 "$SKILL_DIR/doctor.py"
python3 "$SKILL_DIR/inventory.py" --profile <场景>
```

完成准则：FATAL 0、design ERROR 0；目标场景槽位与 live 的差分收敛到
「用户确认过的差异」。

## Invariants

- SSOT is `skillStorageLocation` (`~/.agents/skills` for `unified`, otherwise
  `~/.cc-switch/skills`). App directories are projections, never credential or
  skill ownership records.
- A skill ID is `local:<single-name>` or `owner/repo:<safe/path>`. Its install
  `directory` is one safe, non-hidden path segment and is unique in `skills`.
- `park` creates the row with every `enabled_*` false and no projection.
  `install-enable` is the named-app form: projection first, then its DB flag.
- `live` is DB enable plus projection. A profile slot is a user snapshot and
  may be stale or dangling; it never proves that a skill is live.
- Official app profile scopes are Claude and Codex. Other apps use dispatch;
  they must not be written into profile skill arrays.
- Uninstall removes the skill row, SSOT/projections, and lock entry, but leaves
  profile snapshots untouched. `doctor` reports the resulting dangling ID;
  `slot scrub` is a separate, explicit user decision.

## Commands

| Intent | Command | Mutation |
| --- | --- | --- |
| 盘点全部 skill | `inventory.py [--profile NAME]` | 无（只读） |
| 只读诊断 | `doctor.py [--full] [--remote]` | 无 |
| 注册 / 恢复 SSOT skill | `pipe.py register --id ID --directory DIR --source PATH [--app APP]` | SSOT、行、可选 app 投影 |
| 开 / 关一个 app | `pipe.py dispatch --id ID --app APP --enable\|--disable` | 一个投影 + enable flag |
| 查看 / 显式编辑快照 | `pipe.py slot list\|add\|remove\|resnap\|scrub` | 仅 profile JSON，`--apply` 才写 |
| 删除 skill | `pipe.py uninstall --id ID [--keep-ssot] [--apply]` | 行、SSOT/投影、锁；不碰 profile |
| 改身份 / 目录 | `pipe.py migrate --from-id OLD --to-id NEW --directory DIR [--apply]` | 保留 enable、投影、锁、profile 引用 |

除 `register` / `dispatch` 外的变更命令默认 dry-run，`--apply` 才落笔；
`register` 不重命名已有 id、目录冲突即拒——改身份走 `migrate`。

## Profile and fat-snapshot policy

`null` = 从未快照；`[]` = 快照为空；id 列表 = 快照，不是 live。绑定 profile
含非 live id 时 `doctor` 报 policy warning 并指向 `slot resnap` / `slot
scrub`；**永不自动 enable**。身份迁移是唯一的自动 profile 编辑，只改写精确
的旧 canonical id。

## Completion checks

1. 复验 `doctor.py`：FATAL 0、design ERROR 0；hygiene / policy 项已理解，
   未隐藏。
2. **Skill 验收**：复验 `inventory.py --profile <目标>`：差分与用户确认一致；
   主力 pair 无未确认 drift；受管 default-off app 无未确认 live；Hermes live
   与用户明确选择一致。MCP 不由此项判定，必须按 `mcp-governance.md` 的逐列矩阵验收。
3. `content_hash.py` 与 DB / GitHub 锁条目一致。
4. 未手删 / 手改 SSOT、投影来修 finding——一律走 `migrate` / `register` /
   `dispatch` / 显式 `slot` 操作。

见 `mcp-governance.md`、`experience.md`、`profiles.md`、`project-slot.md`、
`doctor.md`、`file-layout.md`、`db-schema.md`、`lock-file.md`。
