---
name: cc-switch-adapter
description: >
  cc-switch 集中管理适配器。当用户要求安装/卸载/更新/管理/适配/迁移/清理 SKILL 或 MCP，
  或提到 "skill"、"mcp"、"插件"、"安装技能"、"添加mcp"、"导入"、"cc-switch" 时必须使用。
---

# cc-switch 适配器

## 致命错误：父级 symlink

**所有 app skills 目录必须是真实目录。** 任何一个目录是父级 symlink → SSOT，cc-switch 都会在 sync 时删除 SSOT 文件。

根因：`remove_path()` 只检查路径自身的 symlink 元数据。父级 symlink 下 `is_symlink()` 返回 false，`is_dir()` 返回 true，走上 `remove_dir_all()` 分支。

```bash
# 操作前必须全量检查（5个目录）
for app_dir in ~/.claude/skills ~/.codex/skills ~/.gemini/skills \
               ~/.config/opencode/skills ~/.hermes/skills; do
  [ -L "$app_dir" ] && echo "FATAL: $app_dir 是父级 symlink，必须修复" && exit 1
done
```

修复：移除父级 symlink，创建真实目录 + 每个 skill 子级 symlink。
子级 symlink 下 `is_symlink()` 返回 true → `remove_file()` → SSOT 安全。

详见 [file-layout.md](file-layout.md)。

## 核心约束

- **SSOT**: `~/.agents/skills/` — 所有 skill 文件的唯一权威存放处，必须是真实目录
- **数据库**: `~/.cc-switch/cc-switch.db` → skills 表、mcp_servers 表、skill_repos 表
- **锁文件**: `~/.agents/.skill-lock.json` — 源追踪信息
- **应用目录**: 真实目录，内含子级 symlink → SSOT。绝不直接写入文件

## Symlink 安全协议

所有 symlink 操作遵守以下规则。违反是适配过程中最常见的故障源。

### 创建子级 symlink 的正确序列

```
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
| 父级 symlink（app dir → SSOT） | "Skill 不存在于 SSOT"、文件消失 | 转为子级 symlink 架构 |
| 自引用 symlink（SSOT dir → 自身）| "Too many levels of symbolic links" | `rm <path>` 删除 symlink |
| `cp -r` 到已有 symlink | 跟随 symlink 写入目标目录，污染 SSOT | 先 `rm` symlink，再 `cp -r` |
| 验证脚本用 `ls -d */` | 跟随 symlink 显示目录内容，误报 "NOT A SYMLINK" | 用 `[ -L "$path" ]`（无尾斜杠）检查 |

禁止抑制错误：所有命令不得使用 `2>/dev/null`、`|| true` 或 `|| echo` 吞错误。

## 操作流程

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

### 2. 安装 SKILL

1. **确定来源** — 解析 GitHub URL 或 ClawHub ref。ClawHub 来源用 `sourceType: "clawhub"`，`repo_owner/repo_name` 设为 NULL（避免 cc-switch 对 ClawHub-only 仓库发起 GitHub 下载得到 404）
2. **下载到 SSOT** — 文件放到 `~/.agents/skills/<name>/`，确保包含 SKILL.md
3. **写入数据库** — INSERT 到 skills 表，必填字段见 [db-schema.md](db-schema.md)
4. **更新锁文件** — 注册 source/sourceType/sourceUrl/branch
5. **创建子级 symlink** — 按 Symlink 安全协议为每个启用的 app 建立链接
6. **验证** — 按完成准则逐项确认

### 3. 适配已有技能（迁移到 cc-switch 管理）

1. **确认 SSOT 已有内容** — 若 `~/.agents/skills/<name>/SKILL.md` 不存在，从当前存在的 app 目录复制到 SSOT
2. **验证来源** — 检查 `.clawhub/origin.json`（ClawHub）、`.git/config`（GitHub），无来源则标记 `local:`
3. **写入数据库** — ClawHub 来源 repo_owner/repo_name 设为 NULL；GitHub 来源填入完整信息
4. **更新锁文件** — 根据可用来源信息写入
5. **替换应用目录** — SSOT 必须是真实目录（`[ -d "$path" ] && [ ! -L "$path" ]`），按 Symlink 安全协议删除旧副本并建立子级 symlink

### 4. 卸载 SKILL

1. 从数据库 DELETE
2. 从所有应用目录删除子级 symlink（`rm`，不用 `-r`）
3. 从 SSOT 删除（可选先备份到 `~/.cc-switch/skill-backups/`）
4. 从锁文件移除

### 5. 添加 MCP

1. 解析 MCP 配置 → 写入 `mcp_servers` 表
2. 写入对应应用的 MCP 配置文件

### 6. 检查一致性

- 数据库有记录 SSOT 无文件 → 损坏，尝试从 GitHub/lock-file 恢复
- SSOT 有文件数据库无记录 → 未管理，按操作 3 导入
- 锁文件缺少条目 → 从 DB 补写 source 信息
- 任何 app dir 是父级 symlink → 按操作 1 修复
- 子级 symlink 指向错误目标或损坏 → 按 Symlink 安全协议重建
- ClawHub 来源 skill 的 repo_owner 非 NULL → 设为 NULL（避免 GitHub 404）

## 完成准则

每条操作完成后必须确认全部：

1. **预检通过** — 5 个 app dir 无一为父级 symlink
2. **数据库** — `SELECT id, repo_owner, repo_name FROM skills WHERE directory='<name>';` 返回正确记录
3. **SSOT** — `[ -d ~/.agents/skills/<name> ] && [ ! -L ~/.agents/skills/<name> ]` 为真
4. **所有启用的 app 子级 symlink** — 对每个 `enabled_<app> = 1` 的应用，`[ -L ~/.<app>/skills/<name> ]` 为真且 `readlink` 指向正确 SSOT 路径
5. **锁文件** — `~/.agents/.skill-lock.json` 包含该 skill 的 source 信息

## 参考

- [db-schema.md](db-schema.md) — SQLite 表结构和 INSERT 示例
- [lock-file.md](lock-file.md) — `.skill-lock.json` 格式和 jq 操作
- [file-layout.md](file-layout.md) — 完整文件系统布局和修复父级 symlink 流程
