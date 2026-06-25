# cc-switch 文件系统布局

基于当前配置 (`skillStorageLocation: "unified"`, `skillSyncMethod: "auto"`).

## 🚨 父级 symlink 是致命错误

**`~/.claude/skills → ~/.agents/skills` 会导致 cc-switch 的 `remove_path()` 删除 SSOT 文件。**

根因：cc-switch 的 `remove_path()` 只检查路径**自身**的 symlink 元数据。

当 `~/.claude/skills` 是父级 symlink 时：
- `is_symlink(~/.claude/skills/foo)` → **false**（symlink 在父级）
- `path.is_dir()` → **true**（OS 通过父级 symlink 解析到 SSOT）
- → `fs::remove_dir_all()` → **删除的是 `~/.agents/skills/foo`**

这会发生在：用户勾选/取消 skill 时、`sync_to_app()` 清理时、任何 enable/disable 操作。

**正确架构：子级 symlink**

```
~/.claude/skills/              ← 必须是真实目录
├── foo → ~/.agents/skills/foo/ ← 子级 symlink（is_symlink() = true → 安全）
├── bar → ~/.agents/skills/bar/
```

## 目录结构

```
~/.cc-switch/                    # cc-switch 应用数据
├── cc-switch.db                 # SQLite 数据库 (SSOT for metadata)
├── settings.json                # 应用设置
├── skills/                      # 废弃（切换到 unified 前的遗留，应为空）
├── skill-backups/               # 卸载备份 (保留最近 20 个)
├── backups/                     # 数据库备份
└── logs/                        # 应用日志

~/.agents/                       # 统一 Agent 目录 (当前 SSOT)
├── .skill-lock.json             # Skill 源追踪锁文件
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

## 写入规则 (必须遵守)

| 位置 | 是否可直接写入 | 说明 |
|------|--------------|------|
| `~/.agents/skills/<name>/` | ✅ 是 | SSOT — 所有新 skill 文件放这里 |
| `~/.claude/skills/` 本身 | ❌ 否 | 必须是真实目录，不能是 symlink |
| `~/.claude/skills/<name>/` | ❌ 否 | 必须是子级 symlink → SSOT，不能是真实目录 |
| `~/.cc-switch/cc-switch.db` | ✅ 是 | 元数据 SSOT |
| `~/.agents/.skill-lock.json` | ✅ 是 | 源追踪 |

## 写入示例 (安装 skill "my-skill")

```bash
# Step 1: 下载到 SSOT
git clone --depth 1 https://github.com/owner/repo.git /tmp/skill-temp
cp -r /tmp/skill-temp/skills/my-skill ~/.agents/skills/my-skill
rm -rf /tmp/skill-temp

# Step 2: 写入数据库
sqlite3 ~/.cc-switch/cc-switch.db "
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, installed_at, updated_at)
VALUES
  ('owner/repo:skills/my-skill', 'My Skill', 'Description',
   'my-skill', 'owner', 'repo', 'main',
   'https://github.com/owner/repo/blob/main/skills/my-skill/SKILL.md',
   1, CAST(strftime('%s', 'now') AS INTEGER), 0);
"

# Step 3: 更新锁文件 (见 lock-file.md)

# Step 4: 创建子级 symlink
SSOT=~/.agents/skills
rm -rf ~/.claude/skills/my-skill       # rm -rf 会触发权限拦截
# 安全做法:
[ -L ~/.claude/skills/my-skill ] && rm ~/.claude/skills/my-skill
[ -d ~/.claude/skills/my-skill ] && rm -r ~/.claude/skills/my-skill
ln -s "$SSOT/my-skill" ~/.claude/skills/my-skill
```

## 修复父级 symlink

```bash
# 如果 ~/.claude/skills 是 symlink:
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
