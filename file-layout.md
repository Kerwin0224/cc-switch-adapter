# cc-switch 文件系统布局

基于当前配置 (`skillStorageLocation: "unified"`, `skillSyncMethod: "auto"`).

## 目录结构

```
~/.cc-switch/                    # cc-switch 应用数据
├── cc-switch.db                 # SQLite 数据库 (SSOT for metadata)
├── settings.json                # 应用设置
├── skills/                      # 遗留 symlink (非当前 SSOT)
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
├── commands/                    # Claude Code commands
└── sources/                     # Git 仓库缓存

~/.claude/                       # Claude Code 应用目录 (★ 目标，不直接写)
├── skills/                      # 从 SSOT sync 而来
│   ├── <skill-1>/               # symlink → ~/.agents/skills/<skill-1>/
│   └── <skill-2>/               # 或 copy 自 SSOT
└── .mcp.json                    # MCP 配置 (从数据库 sync 而来)

~/.codex/                        # Codex 应用目录 (★ 目标，不直接写)
└── skills/                      # 从 SSOT sync 而来

~/.gemini/                       # Gemini CLI 目录 (★ 目标，不直接写)
└── skills/                      # 从 SSOT sync 而来
```

## 同步方向

```
SSOT (~/.agents/skills/)  ──sync──>  ~/.claude/skills/
                          ──sync──>  ~/.codex/skills/
                          ──sync──>  ~/.gemini/skills/
                          ──sync──>  ~/.config/opencode/skills/
                          ──sync──>  ~/.hermes/skills/
```

**单向流动**: SSOT → 应用目录。反向修改会被覆盖。

## 写入规则 (必须遵守)

| 位置 | 是否可直接写入 | 说明 |
|------|--------------|------|
| `~/.agents/skills/<name>/` | ✅ 是 | SSOT — 所有新 skill 文件放这里 |
| `~/.claude/skills/<name>/` | ❌ 否 | 目标目录，会被 sync 覆盖 |
| `~/.codex/skills/<name>/` | ❌ 否 | 同上 |
| `~/.gemini/skills/<name>/` | ❌ 否 | 同上 |
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

# Step 3: 更新锁文件
# (使用 jq 操作 lock-file，见 lock-file.md)

# Step 4: 同步到应用目录 (symlink, autosync 模式)
APP_SKILLS=~/.claude/skills
SSOT=~/.agents/skills
rm -rf "$APP_SKILLS/my-skill"
ln -s "$SSOT/my-skill" "$APP_SKILLS/my-skill" 2>/dev/null || \
  cp -r "$SSOT/my-skill" "$APP_SKILLS/my-skill"
```

## 清理散落文件

```bash
# 查找不在 SSOT 中的 skill
diff <(ls ~/.agents/skills/ | sort) <(ls ~/.claude/skills/ | sort)

# 安全删除仅在 app 目录中的 (必须确认: 不是 symlink 且不在数据库中)
# cc-switch sync 时也会自动清理指向 SSOT 的孤立 symlink
```
