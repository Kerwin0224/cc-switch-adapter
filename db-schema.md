# cc-switch 数据库 Schema

数据库路径: `~/.cc-switch/cc-switch.db` (SQLite)

## skills 表

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,          -- "owner/repo:directory" 或 "local:directory"
    name TEXT NOT NULL,           -- 显示名称 (来自 SKILL.md frontmatter)
    description TEXT,             -- 描述
    directory TEXT NOT NULL,      -- SSOT 中的子目录名 (安装名)
    repo_owner TEXT,              -- GitHub 用户/组织 (本地 skill 为 NULL)
    repo_name TEXT,               -- 仓库名 (本地 skill 为 NULL)
    repo_branch TEXT DEFAULT 'main',
    readme_url TEXT,              -- GitHub blob URL 指向 SKILL.md
    enabled_claude BOOLEAN NOT NULL DEFAULT 0,
    enabled_codex BOOLEAN NOT NULL DEFAULT 0,
    enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
    enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
    enabled_openclaw BOOLEAN NOT NULL DEFAULT 0,
    enabled_hermes BOOLEAN NOT NULL DEFAULT 0,
    installed_at INTEGER NOT NULL DEFAULT 0,  -- Unix 时间戳
    content_hash TEXT,            -- SHA-256 目录哈希 (用于更新检测)
    updated_at INTEGER NOT NULL DEFAULT 0
);
```

> **6 个 enabled_ 列对应 6 个同步目标**：claude / codex / gemini / opencode / openclaw / hermes。注意没有 `enabled_claude_desktop`——ClaudeDesktop 的 `sync_to_app_dir` 直接 return（skill.rs:1587），不实际同步 skill 文件。

## content_hash 算法（关键）

`compute_dir_hash()`（skill.rs:830-850）计算目录指纹，用于更新检测：

1. 递归收集目录下**所有非隐藏文件**——文件名以 `.` 开头的跳过（skill.rs:860），所以 `.git/`、`.gitignore`、`.DS_Store` 都不计入
2. 文件列表**按路径排序**
3. 对每个文件：`hasher.update(相对路径)` → `hasher.update(\0)` → `hasher.update(文件内容)` → `hasher.update(\0)`
4. 输出 SHA-256 的十六进制字符串

**含义**：只有 skill 的内容文件（SKILL.md 等）变化才会改变 hash。`.git` 目录的变化（如 `git pull` 拉到新 commit 但内容文件未变）**不会**改变 hash——但若内容文件变了而 DB hash 没刷新，`check_updates()` 就会误报。

## check_updates 如何用 content_hash（不一致的根因）

`check_updates()`（skill.rs:877-988）对每个 skill：

1. **早返回**：`repo_owner` 或 `repo_name` 为 None → `continue` 跳过（skill.rs:890）。所以 `local:*` 的 skill 永远不检测更新。
2. **本地 hash 优先信任 DB**（skill.rs:956-972）：
   - DB 有 `content_hash` → 直接用 DB 的值（**哪怕过期**）
   - DB 为空 → 实时 `compute_dir_hash(SSOT)` 并 `update_skill_hash()` 回写
3. 拿本地 hash 跟远程 hash 比，不等则报"有更新"

**这就是"本地与云端不一致"的机械根因**：`git pull` 更新了 SSOT 内容文件，但 DB 的 `content_hash` 还是旧值。`check_updates` 信任旧 DB hash → 跟远程新 hash 不等 → 误报"有更新"。修复方法是 reconcile 操作强制刷新 DB hash（见 SKILL.md 操作 7）。

## backfill_content_hashes（cc-switch 启动时自动补算）

`backfill_content_hashes()`（skill.rs:1119-1147）在 cc-switch 启动时调用，**只为 content_hash 为空的 skill 补算**——已 有 hash 的不刷新。所以单纯重启 cc-switch 不会修复"过期 hash"，必须先把 DB hash 置 NULL 再重启，强制重算。

## update_skill_hash（reconcile 用）

```sql
-- cc-switch 内部: db.update_skill_hash(id, hash, updated_at)
-- 等价 SQL:
UPDATE skills SET content_hash = '<sha256>', updated_at = <unix_ts> WHERE id = '<id>';
```

手动 reconcile 应急时，可把 `content_hash` 置 NULL、`updated_at` 置 0，重启 cc-switch 触发 `backfill_content_hashes()` 重算。

## INSERT 示例

### GitHub 来源 skill

```sql
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, enabled_codex, enabled_opencode, enabled_hermes,
   installed_at, content_hash, updated_at)
VALUES
  ('anthropics/skills:skills/memory', 'Memory Skill', 'Manage persistent memory',
   'memory', 'anthropics', 'skills', 'main',
   'https://github.com/anthropics/skills/blob/main/skills/memory/SKILL.md',
   1, 0, 0, 0,
   CAST(strftime('%s', 'now') AS INTEGER),
   NULL, 0);   -- content_hash 传 NULL，cc-switch 启动时 backfill
```

### 本地 ZIP 导入 skill（无源追踪，无法检测更新）

```sql
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, installed_at, content_hash, updated_at)
VALUES
  ('local:my-custom-skill', 'My Custom Skill', 'A custom skill',
   'my-custom-skill', NULL, NULL, NULL, NULL, 1,
   CAST(strftime('%s', 'now') AS INTEGER), NULL, 0);
```

## 常用查询

```sql
-- 所有已安装 skill
SELECT id, name, directory, repo_owner, repo_name, repo_branch FROM skills ORDER BY name;

-- 无源追踪的（无法检测更新，check_updates 跳过）
SELECT id, name, directory FROM skills WHERE repo_owner IS NULL OR repo_name IS NULL;

-- 某 skill 启用了哪些 app（动态检测用）
SELECT enabled_claude,enabled_codex,enabled_gemini,enabled_opencode,enabled_openclaw,enabled_hermes
FROM skills WHERE directory='<name>';
```

## mcp_servers 表

```sql
CREATE TABLE mcp_servers (
    id TEXT PRIMARY KEY,          -- 用户定义的标识 (如 "filesystem")
    name TEXT NOT NULL,           -- 显示名称
    server_config TEXT NOT NULL,  -- JSON: {"command":"npx","args":[...],"env":{}}
    description TEXT,
    homepage TEXT,
    docs TEXT,
    tags TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    enabled_claude BOOLEAN NOT NULL DEFAULT 0,
    enabled_codex BOOLEAN NOT NULL DEFAULT 0,
    enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
    enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
    enabled_openclaw BOOLEAN NOT NULL DEFAULT 0,
    enabled_hermes BOOLEAN NOT NULL DEFAULT 0
);
```

### INSERT 示例

```sql
INSERT OR REPLACE INTO mcp_servers
  (id, name, server_config, description, enabled_claude, enabled_codex)
VALUES
  ('filesystem', 'Filesystem',
   '{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/Users/kerwinwjyan"]}',
   'Access local filesystem', 1, 1);
```

## skill_repos 表

```sql
CREATE TABLE skill_repos (
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    PRIMARY KEY (owner, name)
);
```

```sql
INSERT OR REPLACE INTO skill_repos (owner, name, branch, enabled)
VALUES ('anthropics', 'skills', 'main', 1);
```

## 关键规则

1. **skill 的 `id` 决定能否更新**：`"owner/repo:dir"` 格式才能过 `check_updates()` 的早返回。`"local:*"` 被跳过。
2. **MCP 没有源追踪**：mcp_servers 表无 repo_owner/repo_name/content_hash，无法检测上游更新。
3. **不可手动赋值 `content_hash`**：cc-switch 启动时 `backfill_content_hashes()` 只补空值。传 NULL 让它自动算。
4. **过期 hash 不会自动刷新**：`backfill` 只补空值，已有值不动。修复过期 hash 必须先置 NULL 再重启（reconcile 操作）。
