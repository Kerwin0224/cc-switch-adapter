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
    enabled_hermes BOOLEAN NOT NULL DEFAULT 0,
    installed_at INTEGER NOT NULL DEFAULT 0,  -- Unix 时间戳
    content_hash TEXT,            -- SHA-256 目录哈希 (用于更新检测)
    updated_at INTEGER NOT NULL DEFAULT 0
);
```

### INSERT 示例 (GitHub 来源 skill)

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
   NULL, 0);
```

### INSERT 示例 (本地 ZIP 导入 skill — 无源追踪)

```sql
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, installed_at, content_hash, updated_at)
VALUES
  ('local:my-custom-skill', 'My Custom Skill', 'A custom skill',
   'my-custom-skill', NULL, NULL, NULL, NULL, 1,
   CAST(strftime('%s', 'now') AS INTEGER), NULL, 0);
```

### 查询已安装

```sql
SELECT id, name, directory, repo_owner, repo_name, repo_branch
FROM skills ORDER BY name ASC;
```

### 查询无源追踪的 (无法更新)

```sql
SELECT id, name, directory FROM skills
WHERE repo_owner IS NULL OR repo_name IS NULL;
```

## mcp_servers 表

```sql
CREATE TABLE mcp_servers (
    id TEXT PRIMARY KEY,          -- 用户定义的标识 (如 "filesystem", "github")
    name TEXT NOT NULL,           -- 显示名称
    server_config TEXT NOT NULL,  -- JSON: {"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/path"],"env":{}}
    description TEXT,
    homepage TEXT,
    docs TEXT,
    tags TEXT NOT NULL DEFAULT '[]', -- JSON 数组
    enabled_claude BOOLEAN NOT NULL DEFAULT 0,
    enabled_codex BOOLEAN NOT NULL DEFAULT 0,
    enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
    enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
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

### 查询已安装

```sql
SELECT id, name, server_config FROM mcp_servers;
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

### 添加仓库

```sql
INSERT OR REPLACE INTO skill_repos (owner, name, branch, enabled)
VALUES ('anthropics', 'skills', 'main', 1);
```

## 关键规则

1. **skill 的 `id` 决定了能否更新**: `"owner/repo:dir"` 格式才能走 `check_updates()` 流程。`"local:*"` 格式的 skill 更新检查时被跳过
2. **MCP 没有源追踪**: mcp_servers 表没有 repo_owner/repo_name/content_hash，无法自动检测 MCP 服务器配置的上游更新
3. **不可手动赋值 `content_hash`**: cc-switch 启动时会 `backfill_content_hashes()` 自动计算。传 NULL 即可
