# cc-switch-adapter

> Claude Code skill that routes ALL skill and MCP operations through [cc-switch](https://github.com/farion1231/cc-switch)'s centralized SSOT — no scattered files, no broken source tracking, no orphaned updates.

## The Problem

cc-switch is a desktop app that manages Claude Code skills and MCPs across 7 AI tools (Claude, Codex, Gemini, OpenCode, OpenClaw, Hermes). It uses a carefully designed SSOT (Single Source of Truth) architecture:

```
~/.agents/skills/          ← SSOT: all skill files live here
       ↓ sync (symlink/copy)
~/.claude/skills/          ← app target (NEVER write directly)
~/.codex/skills/           ← app target
~/.gemini/skills/          ← app target
...
```

But when you install skills through external tools — or tell Claude Code to "install skill X" — those skills land directly in `~/.claude/skills/`, bypassing cc-switch's database, lock file, and source tracking. Result:

- ❌ **No source tracking** — skill gets `id: "local:xxx"`, repo_owner/repo_name = NULL
- ❌ **No update detection** — cc-switch's `check_updates()` skips skills without source info
- ❌ **File scattering** — skills spread across app directories with no central authority
- ❌ **Orphaned syncs** — cc-switch sync wipes out changes it didn't originate

## The Solution

`cc-switch-adapter` intercepts EVERY skill/MCP operation and routes it through cc-switch's centralized pipeline:

| Operation | Without adapter | With adapter |
|-----------|----------------|--------------|
| Install skill | → `~/.claude/skills/` (broken) | → SSOT → DB → lock file → app dirs |
| Migrate existing | Stays orphaned | → SSOT copy → DB insert → app symlink |
| Uninstall skill | → rm from app dir (orphans in DB) | → DB delete → SSOT delete → lock file → app dirs |
| Add MCP | → app config file directly | → DB → sync to app config files |
| Clean up | Manual hunt-and-delete | → Audit → migrate to SSOT → rebuild links |

### Parent symlink detection (critical)

Many users symlink `~/.claude/skills` → `~/.agents/skills` so Claude Code reads directly from the SSOT. In this mode, creating a child symlink like `~/.claude/skills/foo` → `~/.agents/skills/foo` creates a **self-referencing symlink** that triggers `Too many levels of symbolic links (os error 62)`. The adapter detects parent-level symlinks and skips child symlink creation.

```
~/.claude/skills  ──(symlink)──▶  ~/.agents/skills/
                                         │
    DO NOT create: ~/.claude/skills/foo → ~/.agents/skills/foo
         (that's ~/.agents/skills/foo → ~/.agents/skills/foo 😵)
```

## Architecture

```
┌─────────────────────┐
│   User says:         │
│  "install skill X"   │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  cc-switch-adapter   │  ← This skill
│  intercepts request  │
└────────┬────────────┘
         ▼
┌─────────────────────┐     ┌──────────────────────┐
│  ~/.agents/skills/   │────▶│  ~/.cc-switch/        │
│  (file SSOT)         │     │  cc-switch.db (SQLite) │
└────────┬────────────┘     │  skills + mcp_servers  │
         │                   └──────────────────────┘
         │ sync                      ▲
         ▼                   ┌───────┴──────────────┐
┌─────────────────────┐     │  ~/.agents/            │
│  ~/.claude/skills/   │     │  .skill-lock.json      │
│  ~/.codex/skills/    │     │  (source tracking)     │
│  ~/.gemini/skills/   │     └──────────────────────┘
└─────────────────────┘
```

### 3 pillars of source tracking

1. **Database** (`~/.cc-switch/cc-switch.db`): `skills` table stores `repo_owner`, `repo_name`, `repo_branch`, `content_hash`
2. **Lock file** (`~/.agents/.skill-lock.json`): community-standard metadata for cross-tool interoperability
3. **File system** (`~/.agents/skills/`): file-level SSOT, symlinked/copied to app dirs by cc-switch

Without all three, cc-switch cannot detect updates. The adapter ensures all three are always in sync.

## File Structure

```
cc-switch-adapter/
├── SKILL.md           # Main skill — 6 operations, symlink safety protocol, 5-point completion criteria
├── db-schema.md       # Reference: SQLite table schemas + INSERT examples
├── lock-file.md       # Reference: .skill-lock.json format + jq operations
├── file-layout.md     # Reference: full filesystem layout, parent symlink mode, write rules
├── README.md          # This file
└── .gitignore
```

## Installation

### Prerequisites

- [cc-switch](https://github.com/farion1231/cc-switch) installed and configured
- [Claude Code](https://claude.ai/code) with skills support
- `sqlite3` and `jq` available in PATH

### Install via cc-switch

1. Open cc-switch → Skills panel
2. Add this repo as a skill source: `Kerwin0224/cc-switch-adapter`
3. Install `cc-switch-adapter` from the discovered skills list

### Install manually

```bash
# Clone to SSOT
git clone https://github.com/Kerwin0224/cc-switch-adapter.git \
  ~/.agents/skills/cc-switch-adapter

# Register in cc-switch database
sqlite3 ~/.cc-switch/cc-switch.db "
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, enabled_codex, enabled_opencode, enabled_hermes,
   installed_at, updated_at)
VALUES
  ('Kerwin0224/cc-switch-adapter:.', 'cc-switch-adapter',
   'cc-switch centralized management adapter for skills and MCPs',
   'cc-switch-adapter', 'Kerwin0224', 'cc-switch-adapter', 'main',
   'https://github.com/Kerwin0224/cc-switch-adapter/blob/main/SKILL.md',
   1, 1, 1, 1, CAST(strftime('%s', 'now') AS INTEGER), 0);
"

# Update lock file
jq --arg name "cc-switch-adapter" \
   --arg source "Kerwin0224/cc-switch-adapter" \
   --arg url "https://github.com/Kerwin0224/cc-switch-adapter.git" \
   --arg path "SKILL.md" \
   --arg branch "main" \
   '.skills[$name] = {
      source: $source, sourceType: "github", sourceUrl: $url,
      skillPath: $path, branch: $branch,
      skillFolderHash: "", installedAt: "", updatedAt: ""
    }' ~/.agents/.skill-lock.json > /tmp/skill-lock.json && \
  mv /tmp/skill-lock.json ~/.agents/.skill-lock.json

# Sync to Claude Code app directory
rm -rf ~/.claude/skills/cc-switch-adapter
ln -s ~/.agents/skills/cc-switch-adapter ~/.claude/skills/cc-switch-adapter
```

## Usage

Just use Claude Code normally. The skill intercepts any skill or MCP management request:

```
You: "install the memory skill from anthropics/skills"
     → Adapter: downloads to SSOT, writes DB, updates lock file, syncs app dirs

You: "adapt my existing skills to cc-switch"
     → Adapter: discovers orphaned skills, copies to SSOT, recovers source info, replaces app copies with symlinks

You: "add an MCP server for filesystem access"
     → Adapter: inserts into mcp_servers table, writes app config files

You: "clean up my scattered skills"
     → Adapter: audits app dirs, migrates orphans to SSOT, restores source tracking where possible

You: "check if my skills have updates"
     → Adapter: queries DB for skills with source tracking, fetches remote, compares hashes
```

## How It Works (Technical Deep-Dive)

This skill is based on a full reverse-engineering of [cc-switch v3.16.3](https://github.com/farion1231/cc-switch)'s Rust source code. Key findings:

### Skill Management

cc-switch's `SkillService` (in `src-tauri/src/services/skill.rs`):

- **`install()`**: Downloads from GitHub as ZIP → extracts to SSOT → inserts `InstalledSkill` into SQLite → syncs to app dirs
- **`check_updates()`**: Groups skills by `(repo_owner, repo_name, repo_branch)`, downloads remote, computes SHA-256 hash, compares with local `content_hash`
- **`import_from_apps()`**: Scans app directories for orphaned skills, reads `~/.agents/.skill-lock.json` to recover source info
- **`sync_to_app_dir()`**: Creates symlink (or copies) from SSOT to app dir. Auto mode: tries symlink first, falls back to copy

**Critical**: `check_updates()` has an early-return for skills with `repo_owner == None`:

```rust
let (owner, name, branch) = match (&skill.repo_owner, &skill.repo_name, &skill.repo_branch) {
    (Some(o), Some(n), Some(b)) => (o.clone(), n.clone(), b.clone()),
    _ => continue,  // ← local/ZIP skills skipped!
};
```

### MCP Management

MCP servers are configuration-based (not file-based):

- Stored as JSON in `mcp_servers.server_config` column
- Synced to app config files (`.mcp.json`, `mcp_servers.toml`, etc.)
- **No source tracking**: no `repo_owner`, `repo_name`, or `content_hash` fields
- **No update detection** for MCP servers

### The Lock File Bridge

`~/.agents/.skill-lock.json` is the community standard that bridges external tools and cc-switch. cc-switch's `parse_agents_lock()` reads it during import and migration to recover `repo_owner`/`repo_name` from entries like:

```json
{
  "source": "anthropics/skills",
  "sourceType": "github",
  "sourceUrl": "https://github.com/anthropics/skills.git",
  "branch": "main",
  "skillPath": "skills/memory/SKILL.md"
}
```

## License

MIT — see [cc-switch](https://github.com/farion1231/cc-switch) for the upstream project's license.

## Credits

Based on reverse-engineering of [cc-switch](https://github.com/farion1231/cc-switch) by [Jason Young](https://github.com/farion1231), v3.16.3. The `cc-switch-adapter` skill bridges Claude Code's skill management with cc-switch's SSOT architecture to ensure source tracking, update detection, and clean file management.
