# cc-switch-adapter

> Claude Code skill that routes ALL skill and MCP operations through [cc-switch](https://github.com/farion1231/cc-switch)'s centralized SSOT — no scattered files, no broken source tracking, no orphaned updates, no stale hashes.

## The Problem

cc-switch is a desktop app that manages AI tool skills and MCPs across 7 tools (Claude, ClaudeDesktop, Codex, Gemini, OpenCode, OpenClaw, Hermes). It uses an SSOT (Single Source of Truth) architecture:

```
~/.agents/skills/          ← SSOT: all skill files live here
       ↓ sync (child symlink / copy)
~/.claude/skills/          ← app target (NEVER write directly)
~/.codex/skills/           ← app target
~/.gemini/skills/          ← app target
~/.config/opencode/skills/ ← app target
~/.openclaw/skills/        ← app target
~/.hermes/skills/          ← app target
```

(ClaudeDesktop is listed but `sync_to_app_dir` skips it — no skill files written there.)

When you install skills through external tools — or tell Claude Code to "install skill X" — those skills land directly in `~/.claude/skills/`, bypassing cc-switch's database, lock file, and source tracking. Result:

- ❌ **No source tracking** — skill gets `id: "local:xxx"`, `repo_owner/repo_name = NULL`
- ❌ **No update detection** — cc-switch's `check_updates()` skips skills without source info (early `continue`)
- ❌ **File scattering** — skills spread across app directories with no central authority
- ❌ **Orphaned syncs** — cc-switch sync wipes out changes it didn't originate

And even for skills **with** source tracking, a second failure mode exists:

- ❌ **Stale DB hash** — `check_updates()` trusts the DB `content_hash` even when it's outdated. After `git pull` updates SSOT files, the DB hash isn't refreshed → `check_updates` forever misreports "update available". The lock file hash is **not** consulted by `check_updates` at all.

## The Solution

`cc-switch-adapter` intercepts EVERY skill/MCP operation and routes it through cc-switch's centralized pipeline, keeping the **three layers of source tracking** in sync:

| Layer | Location | Role |
|-------|----------|------|
| git files | `~/.agents/skills/<name>/` | content entity (SSOT) |
| DB hash | `cc-switch.db` `skills.content_hash` | content fingerprint; `check_updates` trusts this **first** |
| lock file | `~/.agents/.skill-lock.json` | source info (owner/repo/branch); consumed only on import |

| Operation | Without adapter | With adapter |
|-----------|----------------|--------------|
| Install skill | → `~/.claude/skills/` (broken) | → SSOT → DB → lock file → app dirs |
| Migrate existing | Stays orphaned | → SSOT copy → DB insert → app symlink |
| Uninstall skill | → rm from app dir (orphans in DB) | → DB delete → SSOT delete → lock file → app dirs |
| Add MCP | → app config file directly | → DB → sync to app config files |
| Clean up | Manual hunt-and-delete | → Audit → migrate to SSOT → rebuild links |
| **Reconcile** (new) | Stale DB hash → forever "update available" | → refresh DB hash → align lock file → verify three layers |

### Parent symlink is fatal

Many users symlink `~/.claude/skills` → `~/.agents/skills` so Claude Code reads directly from SSOT. This is **fatal**: cc-switch's `remove_path()` checks the dest path's own symlink metadata, and under a parent symlink the dest resolves to `is_symlink=false` + `is_dir=true` → `remove_dir_all` **deletes the SSOT file**.

The adapter detects parent-level symlinks (operation 1) and converts them to the safe child-symlink architecture: real `~/.claude/skills/` dir, each skill a child symlink → SSOT.

```
WRONG (fatal):  ~/.claude/skills ──(parent symlink)──▶ ~/.agents/skills/
RIGHT (safe):   ~/.claude/skills/  (real dir)
                  └── foo ──(child symlink)──▶ ~/.agents/skills/foo
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
│  ...4 more apps      │     └──────────────────────┘
└─────────────────────┘
```

### Three layers of source tracking

1. **git files** (`~/.agents/skills/`): file-level SSOT, symlinked to app dirs
2. **DB hash** (`~/.cc-switch/cc-switch.db`): `skills.content_hash` — SHA-256 of non-hidden files; `check_updates()` trusts this **first**, only recomputing if NULL
3. **lock file** (`~/.agents/.skill-lock.json`): community-standard metadata; cc-switch's `parse_agents_lock()` reads only `source/sourceType/sourceUrl/skillPath/branch` during import

Without all three, cc-switch cannot correctly detect updates. The adapter ensures all three stay in sync — including refreshing a stale DB hash via the reconcile operation.

## File Structure

```
cc-switch-adapter/
├── SKILL.md           # Main skill — 7 operations, symlink safety protocol, dynamic app detection
├── db-schema.md       # Reference: SQLite schemas, content_hash algorithm, check_updates behavior
├── lock-file.md       # Reference: .skill-lock.json format, which fields cc-switch actually reads
├── file-layout.md     # Reference: full filesystem layout, 6 app paths, parent symlink fix
├── README.md          # This file
└── .gitignore
```

## Installation

### Prerequisites

- [cc-switch](https://github.com/farion1231/cc-switch) v3.16.3+ installed and configured
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

# Register in cc-switch database (content_hash = NULL → cc-switch backfills on startup)
sqlite3 ~/.cc-switch/cc-switch.db "
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, enabled_codex, enabled_opencode, enabled_hermes,
   installed_at, content_hash, updated_at)
VALUES
  ('Kerwin0224/cc-switch-adapter:.', 'cc-switch-adapter',
   'cc-switch centralized management adapter for skills and MCPs',
   'cc-switch-adapter', 'Kerwin0224', 'cc-switch-adapter', 'main',
   'https://github.com/Kerwin0224/cc-switch-adapter/blob/main/SKILL.md',
   1, 1, 1, 1, CAST(strftime('%s', 'now') AS INTEGER), NULL, 0);
"

# Update lock file (sourceUrl uses .git URL — recommended)
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

# Sync to Claude Code app directory (child symlink)
[ -L ~/.claude/skills/cc-switch-adapter ] && rm ~/.claude/skills/cc-switch-adapter
[ -d ~/.claude/skills/cc-switch-adapter ] && rm -r ~/.claude/skills/cc-switch-adapter
ln -s ~/.agents/skills/cc-switch-adapter ~/.claude/skills/cc-switch-adapter
```

## Usage

Just use Claude Code normally. The skill intercepts any skill or MCP management request:

```
You: "install the memory skill from anthropics/skills"
     → Adapter: downloads to SSOT, writes DB, updates lock file, syncs app dirs, backfills hash

You: "adapt my existing skills to cc-switch"
     → Adapter: discovers orphaned skills, copies to SSOT, recovers source info, replaces app copies with symlinks

You: "add an MCP server for filesystem access"
     → Adapter: inserts into mcp_servers table, writes app config files

You: "clean up my scattered skills"
     → Adapter: audits app dirs, migrates orphans to SSOT, restores source tracking where possible

You: "cc-switch keeps saying my skills have updates even after git pull"
     → Adapter: reconcile — refreshes stale DB content_hash, aligns lock file, verifies three layers
```

## How It Works (Technical Deep-Dive)

This skill is based on reverse-engineering of [cc-switch v3.16.3](https://github.com/farion1231/cc-switch)'s Rust source (`src-tauri/src/services/skill.rs`). Key findings:

### Skill Management

cc-switch's `SkillService`:

- **`install()`**: Downloads from GitHub as ZIP → extracts to SSOT → inserts `InstalledSkill` into SQLite → syncs to app dirs
- **`check_updates()`** (skill.rs:877): Groups skills by `(repo_owner, repo_name, repo_branch)`, downloads remote, computes SHA-256 hash, compares with local. Two critical behaviors:
  - Early `continue` for skills with `repo_owner == None` (skill.rs:890) — local/ZIP skills skipped
  - Local hash **trusts DB `content_hash` first** (skill.rs:956-972); only recomputes from SSOT if DB is NULL. A stale DB hash → false "update available"
- **`import_from_apps()`** (skill.rs:1447): Scans app directories for orphaned skills, reads `~/.agents/.skill-lock.json` via `parse_agents_lock()` to recover source info
- **`sync_to_app_dir()`** (skill.rs:1586): Creates symlink (or copies) from SSOT to app dir. Auto mode: if dest is a real dir → copy; if symlink → replace; tries symlink first, falls back to copy. **ClaudeDesktop is skipped** (skill.rs:1587)
- **`backfill_content_hashes()`** (skill.rs:1119): On startup, computes hash only for skills whose `content_hash` is NULL — does NOT refresh existing (stale) hashes

### MCP Management

MCP servers are configuration-based (not file-based):

- Stored as JSON in `mcp_servers.server_config` column
- Synced to app config files (`.mcp.json`, `mcp_servers.toml`, etc.)
- **No source tracking**: no `repo_owner`, `repo_name`, or `content_hash` fields
- **No update detection** for MCP servers

### The Lock File Bridge

`~/.agents/.skill-lock.json` is the community standard. cc-switch's `parse_agents_lock()` (skill.rs:383) reads it during import/migration to recover `repo_owner`/`repo_name` from:

```json
{
  "source": "anthropics/skills",
  "sourceType": "github",
  "sourceUrl": "https://github.com/anthropics/skills.git",
  "branch": "main",
  "skillPath": "skills/memory/SKILL.md"
}
```

It reads **only** `source`, `sourceType`, `sourceUrl`, `skillPath`, `branch`. `skillFolderHash` and timestamps are not consumed. **`check_updates()` does not read this file** — update detection relies solely on DB `content_hash`.

## License

MIT — see [cc-switch](https://github.com/farion1231/cc-switch) for the upstream project's license.

## Credits

Based on reverse-engineering of [cc-switch](https://github.com/farion1231/cc-switch) by [Jason Young](https://github.com/farion1231), v3.16.3. The `cc-switch-adapter` skill bridges external skill management with cc-switch's SSOT architecture to ensure source tracking, update detection, and clean file management.
