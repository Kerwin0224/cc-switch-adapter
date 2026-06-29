---
name: cc-switch-adapter
description: >
  cc-switch 的 SSOT 适配层。当用户要安装/卸载/更新/迁移/清理 SKILL 或 MCP，或提到
  "skill"、"mcp"、"插件"、"cc-switch"、"适配"、"三层不一致"、"check_updates 跳过"、
  "reconcile 技能" 时必须使用。把外部操作路由进 cc-switch 的封闭管道，保三层源追踪一致。
---

# cc-switch 适配器

cc-switch 是一个 SSOT 管理器：skill 文件实体只存一处（`~/.agents/skills/`），各 app 通过子级 symlink 指向它，元数据存 SQLite `~/.cc-switch/cc-switch.db`。它的 `install()` 是**封闭管道**——下载到 SSOT → 写 DB → 算 hash → 建 symlink 一气呵成。

问题在于：用户通过 Claude Code 等**外部途径**装 skill 时，文件直接落进 `~/.claude/skills/`，绕过整个管道。后果是 DB 无记录、`check_updates()` 直接 `continue` 跳过、文件散落各处。

本 skill 是外部操作与封闭管道之间的适配层：**拦截每个 skill/MCP 操作，强制路由进 SSOT → DB → 锁文件 → app symlink 的完整管道**，保三层源追踪一致。

## 三层源追踪（核心概念）

cc-switch 用三层一起才能检测更新。任何一层脱节，`check_updates()` 都会误报或漏报——这正是"本地与云端不一致"的根因。

| 层 | 位置 | 作用 | cc-switch 如何消费 |
|----|------|------|-------------------|
| **git 文件** | `~/.agents/skills/<name>/` | skill 内容实体（SSOT） | `compute_dir_hash()` 算 SHA-256 作为"应有值" |
| **DB hash** | `cc-switch.db` 的 `skills.content_hash` | 本地内容指纹 | `check_updates()` **优先信任此值**；为空才实时算并回写（skill.rs:956-972） |
| **锁文件** | `~/.agents/.skill-lock.json` | 源信息（owner/repo/branch） | `parse_agents_lock()` 在导入时消费，**只读 source/sourceType/sourceUrl/skillPath/branch**（skill.rs:300-309） |

**关键陷阱**：`check_updates()` 拿 DB 里的 `content_hash`（哪怕过期）跟远程新 hash 比。`git pull` 更新了 SSOT 文件，但 DB hash 不刷新 → 永远误报"有更新"。锁文件 hash **不被 check_updates 消费**，只服务导入。所以修复不一致必须从 DB hash 入手，不能只改锁文件。

## 致命错误：父级 symlink

**任何 app skills 目录都不能是父级 symlink 指向 SSOT。** 一旦是，cc-switch 的 `remove_path()` 会在 sync 时删除 SSOT 文件。

根因（skill.rs:1656-1671）：`remove_path(path)` 检查的是 **dest 路径自身**的 symlink 元数据。当 `~/.claude/skills` 是父级 symlink 时，子路径 `~/.claude/skills/foo` 经由父级解析后：

- `is_symlink(~/.claude/skills/foo)` → **false**（symlink 在父级，不在自身）
- `path.is_dir()` → **true**（OS 经父级 symlink 解析到 SSOT）
- → 走 `fs::remove_dir_all()` 分支 → **删的是 `~/.agents/skills/foo`（SSOT）**

这发生在勾选/取消 skill、`sync_to_app()` 清理、任何 enable/disable 操作时。

修复：移除父级 symlink，建真实目录 + 每个 skill 子级 symlink。子级 symlink 下 `is_symlink()` 返回 true → 走 `remove_file()` → SSOT 安全。完整流程见 [file-layout.md](file-layout.md)。

## Symlink 安全协议

所有 symlink 操作遵守此协议。违反是最常见故障源。

### 创建子级 symlink 的正确序列

```bash
# 1. 清除目标（区分 symlink 和真实目录）
[ -L "$APP/$name" ] && rm "$APP/$name"
[ -d "$APP/$name" ] && rm -r "$APP/$name"   # 不要 -f，会触发权限拦截

# 2. 确认已清除
[ -e "$APP/$name" ] && echo "FAIL" && return 1

# 3. 创建
ln -s "$SSOT/$name" "$APP/$name"

# 4. 验证
[ -L "$APP/$name" ] || echo "FAIL: not a symlink"
[ "$(readlink "$APP/$name")" = "$SSOT/$name" ] || echo "FAIL: wrong target"
```

### 关键陷阱

| 陷阱 | 症状 | 修复 |
|------|------|------|
| 父级 symlink（app dir → SSOT） | "Skill 不存在于 SSOT"、SSOT 文件消失 | 转为子级 symlink 架构 |
| `cp -r` 到已有 symlink | 跟随 symlink 写入 SSOT，污染源 | 先 `rm` symlink，再 `cp -r` |
| 验证脚本用 `ls -d */` | 跟随 symlink 显示目录内容，误报 "NOT A SYMLINK" | 用 `[ -L "$path" ]`（无尾斜杠）检查 |

禁止抑制错误：所有命令不得用 `2>/dev/null`、`|| true`、`|| echo` 吞错误。

## 动态检测 app

**不要硬编码 app 目录列表。** cc-switch 支持 6 个同步目标（ClaudeDesktop 被 `sync_to_app_dir` 跳过，skill.rs:1587）：

| app | skills 目录（默认） |
|-----|---------------------|
| claude | `~/.claude/skills` |
| codex | `~/.codex/skills` |
| gemini | `~/.gemini/skills` |
| opencode | `~/.config/opencode/skills` |
| openclaw | `~/.openclaw/skills` |
| hermes | `~/.hermes/skills` |

（claude-desktop 存在但 `get_app_skills_dir` 返回后 sync 立即 return，不实际同步。）

每个 skill 在 DB 有独立 `enabled_<app>` 列。操作时**只处理该 skill 启用的 app**：

```bash
# 查某 skill 启用了哪些 app
sqlite3 ~/.cc-switch/cc-switch.db \
  "SELECT enabled_claude,enabled_codex,enabled_gemini,enabled_opencode,enabled_openclaw,enabled_hermes FROM skills WHERE directory='<name>';"
```

预检父级 symlink 时，扫描**实际存在的** app 目录（而非全部 6 个），避免误扫空目录：

```bash
for app_dir in ~/.claude/skills ~/.codex/skills ~/.gemini/skills \
               ~/.config/opencode/skills ~/.openclaw/skills ~/.hermes/skills; do
  [ -e "$app_dir" ] || continue            # 不存在的跳过
  [ -L "$app_dir" ] && echo "FATAL: $app_dir 是父级 symlink，必须修复" && exit 1
done
```

## 操作流程

每个操作以可检查的完成准则结尾。准则不过关，操作不算完成。

### 1. 修复父级 symlink（最优先）

```bash
# 对每个是父级 symlink 的 app dir:
rm ~/.codex/skills                    # 移除父级 symlink
mkdir -p ~/.codex/skills              # 创建真实目录
for d in ~/.agents/skills/*/; do
  name=$(basename "$d")
  [ "$name" = ".system" ] && continue
  ln -s "$d" ~/.codex/skills/"$name"  # 子级 symlink
done
```

**完成准则**：`for d in ~/.codex/skills/*/; do [ -L "${d%/}" ] || echo FAIL; done` 对每个 skill 都为真。

### 2. 安装 SKILL

1. **确定来源** — 解析 GitHub URL 或 ClawHub ref。ClawHub 来源用 `sourceType: "clawhub"`，`repo_owner/repo_name` 设为 NULL（否则 cc-switch 对 ClawHub-only 仓库发 GitHub 下载得 404）
2. **下载到 SSOT** — 文件放 `~/.agents/skills/<name>/`，确保含 SKILL.md
3. **写入数据库** — INSERT 到 skills 表，必填字段见 [db-schema.md](db-schema.md)
4. **更新锁文件** — 注册 source/sourceType/sourceUrl/skillPath/branch
5. **创建子级 symlink** — 按 Symlink 安全协议，仅为启用的 app 建链接
6. **回填 hash** — 见操作 7 第 1 步，保证三层一致

**完成准则**：DB `SELECT id,repo_owner,repo_name FROM skills WHERE directory='<name>'` 返回正确记录；SSOT 是真实目录（`[ -d ] && [ ! -L ]`）；每个启用 app 的 `[ -L ~/.<app>/skills/<name> ]` 为真且 readlink 指向 SSOT。

### 3. 适配已有技能（迁移到 cc-switch 管理）

1. **确认 SSOT 有内容** — 若 `~/.agents/skills/<name>/SKILL.md` 不存在，从当前存在的 app 目录复制到 SSOT
2. **验证来源** — 检查 `.clawhub/origin.json`（ClawHub）、`.git/config`（GitHub），无来源标记 `local:`
3. **写入数据库** — ClawHub 来源 repo_owner/repo_name 设 NULL；GitHub 来源填完整信息
4. **更新锁文件** — 根据可用来源信息写入
5. **替换应用目录** — 按 Symlink 安全协议删除旧副本并建子级 symlink

**完成准则**：同操作 2，外加"DB 有记录且 enabled app 的 symlink 全部重建"。

### 4. 卸载 SKILL

1. 从数据库 DELETE
2. 从所有 app 目录删子级 symlink（`rm`，不用 `-r`）
3. 从 SSOT 删除（可先备份到 `~/.cc-switch/skill-backups/`）
4. 从锁文件移除

**完成准则**：`SELECT count(*) FROM skills WHERE directory='<name>'` = 0；所有 app 目录无该 skill 残留；锁文件无该条目。

### 5. 添加 MCP

1. 解析 MCP 配置 → 写入 `mcp_servers` 表（无源追踪，无 hash）
2. 写入对应 app 的 MCP 配置文件（`.mcp.json` / `mcp_servers.toml` 等）

**完成准则**：`SELECT id,name FROM mcp_servers WHERE id='<id>'` 返回记录；对应 app 配置文件含该 server。

### 6. 检查一致性

- DB 有记录 SSOT 无文件 → 损坏，从 GitHub/锁文件恢复
- SSOT 有文件 DB 无记录 → 未管理，按操作 3 导入
- 锁文件缺条目 → 从 DB 补写 source 信息
- 任何 app dir 是父级 symlink → 按操作 1 修复
- 子级 symlink 指向错误或损坏 → 按 Symlink 安全协议重建
- ClawHub 来源 skill 的 repo_owner 非 NULL → 设为 NULL

**完成准则**：上述每项检查均无异常报告。

### 7. 一致性自愈（reconcile）— 解决"本地与云端不一致"

当 `check_updates()` 误报"有更新"但 SSOT 文件其实已最新时，根因是 DB hash 过期。此操作强制对齐三层：

1. **回填 DB hash**（核心）— 对目标 skill 实时算 hash 并 UPDATE，模拟 `backfill_content_hashes()` 但强制刷新而非只补空值：

```bash
# content_hash = SHA-256 of 非隐藏文件（排除 .git/.gitignore，见 db-schema.md）
# 算法见 skill.rs:830-850：收集所有非点开头文件，排序，对 (相对路径\0 内容\0) 串联哈希
# 最稳妥：直接读 cc-switch 的 DB，让 cc-switch 自己 backfill（重启 cc-switch 即触发）
# 手动应急：
sqlite3 ~/.cc-switch/cc-switch.db "UPDATE skills SET content_hash=NULL, updated_at=0 WHERE directory='<name>';"
# 然后重启 cc-switch，backfill_content_hashes() 会重算（skill.rs:1119-1147）
```

2. **对齐锁文件** — 回填 `skillFolderHash`、更新 `updatedAt`、修复 `sourceUrl` 格式（见 [lock-file.md](lock-file.md)）
3. **验证三层一致** — git 文件内容、DB hash、（可选）锁文件 hash 指向同一状态

**完成准则**（每条必须过）：
- DB `SELECT content_hash FROM skills WHERE directory='<name>'` 非空，且 `compute_dir_hash(SSOT/<name>)` 实时计算结果与 DB 值一致
- 锁文件条目含 source/sourceType/sourceUrl/skillPath/branch 五字段
- 重启 cc-switch 后 `check_updates()` 对该 skill 不再误报更新

## 参考

- [db-schema.md](db-schema.md) — SQLite 表结构、content_hash 算法、INSERT 示例
- [lock-file.md](lock-file.md) — `.skill-lock.json` 格式、cc-switch 消费规则、jq 操作
- [file-layout.md](file-layout.md) — 完整文件系统布局、6 app 路径、修复父级 symlink 流程
