# cc-switch 文件系统布局

基于当前配置 (`skillStorageLocation: "unified"`, `skillSyncMethod: "auto"`)。

## 🚨 父级 symlink 是致命错误

**`~/.claude/skills → ~/.agents/skills` 会导致 cc-switch 的 `remove_path()` 删除 SSOT 文件。**

根因（skill.rs:1656-1671）：`remove_path(path)` 检查 **dest 路径自身**的 symlink 元数据。

当 `~/.claude/skills` 是父级 symlink 时，子路径 `~/.claude/skills/foo` 经父级解析：
- `is_symlink(~/.claude/skills/foo)` → **false**（symlink 在父级，不在 dest 自身）
- `path.is_dir()` → **true**（OS 经父级 symlink 解析到 SSOT）
- → `fs::remove_dir_all()` → **删除的是 `~/.agents/skills/foo`（SSOT）**

发生在：用户勾选/取消 skill 时、`sync_to_app()` 清理时、任何 enable/disable 操作。

**正确架构：子级 symlink**

```
~/.claude/skills/              ← 必须是真实目录
├── foo → ~/.agents/skills/foo/ ← 子级 symlink（is_symlink() = true → 安全）
├── bar → ~/.agents/skills/bar/
```

## 6 个同步目标（精确路径）

cc-switch 的 `get_app_skills_dir()`（skill.rs:505-557）和 `sync_to_app_dir()`（skill.rs:1586）定义了 6 个实际同步的 app。**ClaudeDesktop 被跳过**（`sync_to_app_dir` 第 1587 行直接 `return Ok(())`）。

| app | 默认 skills 目录 | 备注 |
|-----|-----------------|------|
| claude | `~/.claude/skills` | |
| codex | `~/.codex/skills` | |
| gemini | `~/.gemini/skills` | |
| opencode | `~/.config/opencode/skills` | 注意在 `.config` 下 |
| openclaw | `~/.openclaw/skills` | |
| hermes | `~/.hermes/skills` | 实际由 `get_hermes_dir()` 决定，默认 `~/.hermes` |
| ~~claude-desktop~~ | `~/.claude-desktop/skills` | **跳过**，sync 不写 skill 文件 |

> 每个路径都可能被 `settings.json` 的 override 目录覆盖（`get_<app>_override_dir()`）。操作时优先用 DB 的 `enabled_<app>` 判断该 skill 启用了哪些 app，再处理对应目录。

## 目录结构

```
~/.cc-switch/                    # cc-switch 应用数据
├── cc-switch.db                 # SQLite 数据库 (元数据 SSOT)
├── settings.json                # 应用设置
├── skills/                      # 废弃（切换到 unified 前的遗留，应为空）
├── skill-backups/               # 卸载备份 (保留最近 20 个)
├── backups/                     # 数据库备份
└── logs/                        # 应用日志

~/.agents/                       # 统一 Agent 目录 (当前 SSOT)
├── .skill-lock.json             # Skill 源追踪锁文件 (社区规范)
├── skills/                      # ★ SSOT — 所有 skill 文件的唯一权威存放处
│   ├── <skill-1>/
│   │   └── SKILL.md
│   └── <skill-2>/
│       └── SKILL.md

~/.claude/                       # Claude Code 应用目录
├── skills/                      # ★ 真实目录，内含子级 symlink → SSOT
│   ├── <skill-1> → ~/.agents/skills/<skill-1>/
│   └── <skill-2> → ~/.agents/skills/<skill-2>/
└── .mcp.json                    # MCP 配置 (从数据库 sync 而来)
```

其余 5 个 app 同理：各自 `skills/` 是真实目录，内含子级 symlink 指向 SSOT。

## 写入规则（必须遵守）

| 位置 | 是否可直接写入 | 说明 |
|------|--------------|------|
| `~/.agents/skills/<name>/` | ✅ 是 | SSOT — 所有新 skill 文件放这里 |
| `~/.<app>/skills/` 本身 | ❌ 否 | 必须是真实目录，不能是 symlink |
| `~/.<app>/skills/<name>/` | ❌ 否 | 必须是子级 symlink → SSOT，不能是真实目录 |
| `~/.cc-switch/cc-switch.db` | ✅ 是 | 元数据 SSOT |
| `~/.agents/.skill-lock.json` | ✅ 是 | 源追踪（社区规范） |

## 动态检测原则

**不要硬编码"全部 6 个 app 都处理"。** 每个 skill 在 DB 有独立的 `enabled_<app>` 列：

```bash
# 查某 skill 启用了哪些 app
sqlite3 ~/.cc-switch/cc-switch.db \
  "SELECT enabled_claude,enabled_codex,enabled_gemini,enabled_opencode,enabled_openclaw,enabled_hermes FROM skills WHERE directory='<name>';"
```

- **安装/建 symlink**：只为 `enabled_<app> = 1` 的 app 创建
- **预检父级 symlink**：扫描**实际存在**的 app 目录，不存在的跳过（避免误扫空目录）
- **卸载/删 symlink**：同样只处理启用的 app

## 写入示例（安装 skill "my-skill"）

```bash
# Step 1: 下载到 SSOT
git clone --depth 1 https://github.com/owner/repo.git /tmp/skill-temp
cp -r /tmp/skill-temp/skills/my-skill ~/.agents/skills/my-skill
rm -rf /tmp/skill-temp

# Step 2: 写入数据库 (见 db-schema.md)

# Step 3: 更新锁文件 (见 lock-file.md)

# Step 4: 创建子级 symlink (仅为启用的 app)
SSOT=~/.agents/skills
# 安全清除 + 建链 (区分 symlink 和真实目录)
[ -L ~/.claude/skills/my-skill ] && rm ~/.claude/skills/my-skill
[ -d ~/.claude/skills/my-skill ] && rm -r ~/.claude/skills/my-skill
ln -s "$SSOT/my-skill" ~/.claude/skills/my-skill
```

## 修复父级 symlink

```bash
# 如果 ~/.claude/skills 是 symlink (父级 symlink，致命):
[ -L ~/.claude/skills ] && rm ~/.claude/skills

# 创建真实目录
mkdir -p ~/.claude/skills

# 为每个 SSOT skill 创建子级 symlink
for d in ~/.agents/skills/*/; do
  name=$(basename "$d")
  [ "$name" = ".system" ] && continue
  ln -s "$d" ~/.claude/skills/"$name"
done
```

对每个是父级 symlink 的 app 目录（codex/gemini/opencode/openclaw/hermes）重复同样流程。

## 验证布局正确

```bash
# 1. SSOT 是真实目录 (不是 symlink)
[ -d ~/.agents/skills/<name> ] && [ ! -L ~/.agents/skills/<name> ] && echo "SSOT OK"

# 2. 每个 app 目录是真实目录 (不是父级 symlink)
for app_dir in ~/.claude/skills ~/.codex/skills ~/.gemini/skills \
               ~/.config/opencode/skills ~/.openclaw/skills ~/.hermes/skills; do
  [ -e "$app_dir" ] || continue
  [ -L "$app_dir" ] && echo "FATAL: $app_dir 是父级 symlink" || echo "$app_dir OK"
done

# 3. 每个 skill 子级 symlink 指向 SSOT
[ -L ~/.claude/skills/<name> ] && \
  [ "$(readlink ~/.claude/skills/<name>)" = "/Users/$USER/.agents/skills/<name>" ] && echo "symlink OK"
```
