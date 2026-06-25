---
name: cc-switch-adapter
description: >
  cc-switch 集中管理适配器。当用户要求安装/卸载/更新/管理/适配/迁移/清理 SKILL 或 MCP，
  或提到 "skill"、"mcp"、"插件"、"安装技能"、"添加mcp"、"导入"、"cc-switch" 时必须使用。
  确保所有操作通过 ~/.agents/skills/ (SSOT) + cc-switch 数据库完成，
  不直接在 ~/.claude/skills/ 等应用目录中操作。
---

# cc-switch 适配器

所有 SKILL 和 MCP 管理操作必须通过 cc-switch 的集中管理链路执行。

## 核心约束

- **SSOT**: `~/.agents/skills/` — 所有 skill 文件的唯一权威存放处
- **数据库**: `~/.cc-switch/cc-switch.db` — skills 表、mcp_servers 表、skill_repos 表
- **锁文件**: `~/.agents/.skill-lock.json` — 源追踪信息（owner/repo/branch）
- **应用目录只做目标**: `~/.claude/skills/`、`~/.codex/skills/` 等仅从 SSOT 复制/链接，**绝不直接写入**

## 任何操作前必须执行的预检

```bash
# 检测父级 symlink（致命配置，必须修复）
if [ -L ~/.claude/skills ]; then
  echo "FATAL: ~/.claude/skills 是父级 symlink → $(readlink ~/.claude/skills)"
  echo "此配置会导致 cc-switch 的 remove_path() 删除 SSOT 文件"
  echo "必须立即修复为子级 symlink 模式"
  exit 1
fi
```

### 🚨 父级 symlink 是致命错误，必须修复

**`~/.claude/skills → ~/.agents/skills` 会导致 cc-switch 的 `remove_path()` 删除 SSOT 文件。**

根因追踪（cc-switch v3.16.3 源码 `src-tauri/src/services/skill.rs`）：

```rust
fn remove_path(path: &Path) -> Result<()> {
    if Self::is_symlink(path) {          // ← 检查路径本身的 symlink 元数据
        fs::remove_file(path)?;          //     安全：只删链接
    } else if path.is_dir() {           // ← path 通过父级 symlink 解析到 SSOT！
        fs::remove_dir_all(path)?;       // ← 💀 删除 SSOT 真实目录！
    }
}
```

当父级是 symlink 时：
- `is_symlink(~/.claude/skills/foo)` → **false**（symlink 在父级，不在 `foo` 自身）
- `path.is_dir()` → **true**（OS 通过父级 symlink 解析到 `~/.agents/skills/foo`）
- → `remove_dir_all()` 删除的是 SSOT！

cc-switch 在以下场景调用 `remove_path()`：
- 用户在 GUI 取消勾选某 skill 的 Claude → `remove_from_app()` → **SSOT 被删**
- `sync_to_app()` 清理已禁用 skill → **批量删除 SSOT**

**修复：必须使用子级 symlink，绝不能使用父级 symlink。**

```bash
# 错误（致命）:
ln -s ~/.agents/skills ~/.claude/skills       # 父级 symlink → SSOT 会被删

# 正确:
mkdir ~/.claude/skills                          # 真实目录
for d in ~/.agents/skills/*/; do
  name=$(basename "$d")
  [ "$name" = ".system" ] && continue
  ln -s "$d" ~/.claude/skills/"$name"          # 每个 skill 独立 symlink
done
```

子级 symlink 下：`is_symlink(~/.claude/skills/foo)` → **true** → `remove_file()` → 只删链接，SSOT 安全。
- **禁止抑制错误**: 所有管理命令不得使用 `2>/dev/null`、`|| true` 或 `|| echo` 吞错误 — 错误是诊断信号，隐藏它们会导致级联失败

## Symlink 安全协议

所有 symlink 操作必须遵守以下规则，违反是适配过程中最常见的故障源：

### 创建 symlink 的正确序列

```
# 1. 检查目标路径当前状态
if [ -L "$APP_SKILLS/$name" ]; then
    rm "$APP_SKILLS/$name"          # symlink → 直接 rm
elif [ -d "$APP_SKILLS/$name" ]; then
    rm -r "$APP_SKILLS/$name"       # 真实目录 → rm -r（不要用 -f，会触发权限拦截）
fi

# 2. 确认已清除
[ -e "$APP_SKILLS/$name" ] && echo "FAIL: target still exists" && exit 1

# 3. 创建 symlink
ln -s "$SSOT/$name" "$APP_SKILLS/$name"

# 4. 验证 symlink 完整性
[ -L "$APP_SKILLS/$name" ] || echo "FAIL: not a symlink"
[ -e "$APP_SKILLS/$name" ] || echo "FAIL: symlink broken"
[ "$(readlink "$APP_SKILLS/$name")" = "$SSOT/$name" ] || echo "FAIL: wrong target"
```

### 关键陷阱

| 陷阱 | 症状 | 修复 |
|------|------|------|
| `cp -r` 到已有 symlink | cp 跟随 symlink 写入目标而非替换 symlink；SSOT 被污染 | 先 `rm` symlink，再 `cp -r` |
| `rm` 不带 `-r` 删目录 | "is a directory" 错误 | 目录用 `rm -r`，文件/symlink 用 `rm` |
| `rm -rf` | 被安全策略拦截 | 用 `rm -r`（不加 `-f`） |
| 自引用 symlink | "Too many levels of symbolic links" | `rm <path>` 删除 symlink，从备份恢复内容 |
| 批量操作不验证中间态 | 前一步失败，后续操作在错误状态上继续 | 每步后独立验证 |

## 操作流程

### 1. 安装 SKILL

当用户要求安装一个 SKILL（通过名称、GitHub URL、或本地路径），执行：

1. **确定来源** — 解析 GitHub owner/repo/branch/directory，无法确定时询问用户
2. **下载到 SSOT** — 将文件放到 `~/.agents/skills/<name>/`，确保包含 SKILL.md
3. **写入数据库** — 在 `skills` 表中 INSERT 记录，必填字段见 [db-schema.md](db-schema.md)
4. **更新锁文件** — 在 `~/.agents/.skill-lock.json` 中注册 source/sourceType/sourceUrl/branch
5. **同步到应用目录** — 严格遵循 [Symlink 安全协议](#symlink-安全协议) 建立链接
6. **验证** — 按 [完成准则](#完成准则) 逐项确认

### 2. 适配已有技能（迁移到 cc-switch 管理）

当技能已存在于 `~/.claude/skills/` 但未纳入 cc-switch 管理（DB 无记录），执行：

1. **确认 SSOT 已有内容** — 若 `~/.agents/skills/<name>/SKILL.md` 不存在，先从 `~/.claude/skills/<name>/` 复制到 SSOT
2. **验证来源** — 检查 `~/.claude/skills/<name>/.clawhub/origin.json`（ClawHub 来源）或 `.git/config`（GitHub 来源），无来源信息则标记为 `local:`
3. **写入数据库** — 非 GitHub 来源用 `local:<name>` 作为 id，ClawHub 来源保留 `sourceType: "clawhub"`
4. **更新锁文件** — 根据可用来源信息写入，缺失字段留空
5. **替换应用目录** — 先确认 SSOT 是**真实目录**（`[ -d "$path" ] && [ ! -L "$path" ]`），再按 [Symlink 安全协议](#symlink-安全协议) 删除应用目录副本并建立 symlink
6. **删除临时备份** — 若操作过程中产生了备份到 `~/.cc-switch/skill-backups/`，验证通过后清理

### 3. 卸载 SKILL

1. 从数据库 `skills` 表 DELETE
2. 从 `~/.agents/skills/<name>/` 删除（可选：先备份到 `~/.cc-switch/skill-backups/`）
3. 从锁文件移除对应条目
4. 从所有应用目录删除该 skill（symlink 用 `rm`，真实目录用 `rm -r`）

### 4. 添加 MCP

1. 解析 MCP 配置（command/args/env 或 url）
2. 在 `mcp_servers` 表 INSERT，`enabled_claude` 按需设为 1
3. 写入 Claude 的 MCP 配置文件（`~/.claude/.mcp.json` 或 `claude_desktop_config.json`）
4. 验证 MCP 配置可正常加载

### 5. 清理散落文件

当用户要求清理或发现 skill/mcp 文件不在 SSOT 中：

1. 扫描 `~/.claude/skills/`、`~/.codex/skills/` 等应用目录
2. 对比数据库记录：不在数据库中的 → 询问用户是否迁移到 SSOT 或删除
3. 迁移时：先将文件移到 SSOT，再补写数据库和锁文件，最后重建应用目录链接

### 6. 检查一致性

检查 cc-switch 管理的完整性：

- 数据库有记录但 SSOT 无文件 → 标记为损坏，需重新下载
- SSOT 有文件但数据库无记录 → 标记为未管理，需导入
- 锁文件缺少对应条目 → 补写 source 信息
- 应用 symlink 指向错误目标或损坏 → 按 [Symlink 安全协议](#symlink-安全协议) 重建
- SSOT 本身是 symlink 而非真实目录 → **严重故障**，立即修复（见 Symlink 安全协议-关键陷阱）

## 完成准则

每条操作完成后必须确认全部 5 项：

1. **数据库** — `sqlite3 ~/.cc-switch/cc-switch.db "SELECT id, repo_owner, repo_name FROM skills WHERE directory='<name>';"` 返回正确记录
2. **SSOT 真实性** — `[ -d "$HOME/.agents/skills/<name>" ] && [ ! -L "$HOME/.agents/skills/<name>" ]` 为真（SSOT 必须是真实目录，绝不能是 symlink）
3. **SKILL.md 可达** — `head -3 ~/.agents/skills/<name>/SKILL.md` 正常输出 frontmatter（不报 "Too many levels"）
4. **应用 symlink 正确** — `[ -L "$HOME/.claude/skills/<name>" ]` 为真，且 `readlink` 指向正确 SSOT 路径，且内容可访问
5. **锁文件** — `~/.agents/.skill-lock.json` 中包含该 skill 的 source 信息

## 参考

- [db-schema.md](db-schema.md) — SQLite 表结构、字段说明和 INSERT 示例
- [lock-file.md](lock-file.md) — `.skill-lock.json` 格式和必要字段
- [file-layout.md](file-layout.md) — 完整文件系统布局和路径约定
