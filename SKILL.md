---
name: cc-switch-adapter
description: >
  closed-pipe adapter for registering, migrating, dispatching, diagnosing, and
  explicitly governing skills through cc-switch. Use for skill installation,
  scenario-profile design (建立/维护/完善 a profile: which skills should be live),
  provider/profile changes, canonical IDs, SSOT projections, or parent-link
  failures.
---

# cc-switch adapter

`closed-pipe` means every mutation has one explicit route: cc-switch's unified
SSOT, one canonical DB row, per-app enable columns, and child projections.
Runtime state is authoritative: read `settings.json`, the DB schema, and the
filesystem before using repository documentation.

## 规矩（先对齐，再动手）

- **三件套**：主力工具 claude-code / codex / opencode 默认同时启用；其余 app
  （gemini / grokbuild / hermes / claude-desktop / openclaw）默认关闭。
- **场景 = profile**：每个 profile 是一个场景（开发 / 求职 / 办公 / 视频 /
  运维 / GSW…），只装该场景要用的 skill；通用核心（本 adapter、
  writing-for-agents）随每个场景。
- 任何「该开 / 不该开」先对齐以上两条；偏离要列明理由并等用户确认，
  绝不自行扩大或收缩 live。

## 场景 profile 工作流（查→盘→判→治→查）

把「现状」带到「应该」的 closed-pipe 闭环：先读后动，每步有完成准则。

### 1 查 baseline（只读）

```bash
python3 "$SKILL_DIR/doctor.py"           # runtime-first 基线：finding + next:
python3 "$SKILL_DIR/doctor.py" --remote  # 可选：云端新鲜度 R1-R4
```

`SKILL_DIR` 是本 skill 安装目录；`--root` 只用于隔离的假 home。app `skills`
父目录是 symlink = 致命 parent-link 条件，先 `migrate` 再动任何东西。
`--remote` 是报告专用 seam：R1 仓库存在/归档、R2 路径漂移、R3 过时、
R4 上游未装；不产生 FATAL、不改 `next:`，离线降级为单条 WARN。

完成准则：拿到 baseline——SSOT 路径、sync 方式、live 行数、全部 finding 与
`next:`。FATAL / design ERROR 先记入清单，本步不修。

### 2 盘 inventory（只读，扫全部 skill）

```bash
python3 "$SKILL_DIR/inventory.py"                 # 全表：skill × app live + 场景槽位
python3 "$SKILL_DIR/inventory.py" --profile 开发   # 加：该场景槽位 vs live 差分
```

完成准则：得到两份答案——① 目前哪些开了、哪些没开（逐 app）；② 目标场景
槽位里哪些 live、哪些只有槽位、哪些悬空。本步零写入。

### 3 判 verdict（只读，得出「应该」）

对照全表逐条给出「应该开 / 应该关」：

- **三件套**：非三件套 app 上的 live 默认该关；claude / codex / opencode
  默认同开同关，不一致（trio drift）是待对齐项。
- **场景**：按目标 profile 的场景挑 skill——场景要用的该开、已开但场景不
  需要的该关、场景需要但未装的先 `register`。
- 每条写明依据（policy / 场景 / 依赖），组成待办清单。

完成准则：清单覆盖全表所有差异，每条有依据，没有「感觉」项。

### 4 治 act（用户点名的 closed-pipe 动词）

```bash
python3 "$SKILL_DIR/pipe.py" dispatch --id ID --app claude --enable|--disable
python3 "$SKILL_DIR/pipe.py" slot add|remove|resnap|scrub --profile 开发 ...
python3 "$SKILL_DIR/pipe.py" register|migrate|uninstall ...
python3 "$SKILL_DIR/remedy.py" [--apply]          # doctor finding 的闭环修复
```

- profile 槽位只改 profiles JSON，永不直接改 live；live 只经 `dispatch`
  或用户明确 apply。
- **三件套同步**：profile 槽位覆盖 claude / codex，opencode 用 `dispatch`
  对齐同一集合——opencode 不写进 profile 数组。
- 完成准则：清单每一项落一个动词；未确认的偏离保持原状并报告。

### 5 复验（只读）

```bash
python3 "$SKILL_DIR/doctor.py"
python3 "$SKILL_DIR/inventory.py" --profile 开发
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
2. 复验 `inventory.py --profile <目标>`：差分与用户确认一致；三件套无
   未确认 drift，无非三件套 live。
3. `content_hash.py` 与 DB / GitHub 锁条目一致。
4. 未手删 / 手改 SSOT、投影来修 finding——一律走 `migrate` / `register` /
   `dispatch` / 显式 `slot` 操作。

见 `experience.md`、`profiles.md`、`project-slot.md`、`doctor.md`、
`file-layout.md`、`db-schema.md`、`lock-file.md`。
