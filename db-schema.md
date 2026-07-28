# DB 参考（本机 `.schema` 优先）

`~/.cc-switch/cc-switch.db`。先跑 `.schema skills`；下列为常见现行列。

## skills

**canonical-id**：`owner/repo:<path>` | `local:<name>`（无长期 bare；`<path>` 可为短名或仓库内相对路径；**禁止** `owner/repo:.`）。  
**unified-row**：一行 + 多列 **per-app enable**。  
**park**（adapter-policy）：所有 `enabled_*=0`。点名 app 时用 **install-enable**，不是「官方安装=全关」。

```sql
-- 以本机 .schema 为准；缺列勿写
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    directory TEXT NOT NULL,
    repo_owner TEXT,
    repo_name TEXT,
    repo_branch TEXT DEFAULT 'main',
    readme_url TEXT,
    enabled_claude BOOLEAN NOT NULL DEFAULT 0,
    enabled_codex BOOLEAN NOT NULL DEFAULT 0,
    enabled_gemini BOOLEAN NOT NULL DEFAULT 0,
    enabled_grokbuild BOOLEAN NOT NULL DEFAULT 0,
    enabled_opencode BOOLEAN NOT NULL DEFAULT 0,
    enabled_hermes BOOLEAN NOT NULL DEFAULT 0,
    installed_at INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    updated_at INTEGER NOT NULL DEFAULT 0
);
```

```sql
SELECT id, directory, repo_owner, repo_name FROM skills
WHERE id NOT LIKE '%/%' AND id NOT LIKE 'local:%';  -- bare → 分支 M
```

### park INSERT（GitHub）

```sql
INSERT INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, enabled_codex, enabled_gemini, enabled_grokbuild,
   enabled_opencode, enabled_hermes, installed_at, content_hash, updated_at)
VALUES
  ('owner/repo:dirname', 'Name', 'desc', 'dirname', 'owner', 'repo', 'main',
   'https://github.com/owner/repo/blob/main/…/SKILL.md',
   0, 0, 0, 0, 0, 0,
   CAST(strftime('%s','now') AS INTEGER), NULL, 0);
```

已存在同行：用 `UPDATE` 元数据，保留 `enabled_*`。`INSERT OR REPLACE` 会冲掉 enable。

### content_hash

非隐藏文件、相对路径排序、对每个文件 `path\0content\0`，SHA-256 hex：

```bash
python3 - <<'PY'
import hashlib, os, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
files = []
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if not d.startswith('.')]
    for fn in fns:
        if fn.startswith('.'): continue
        files.append(Path(dp) / fn)
files.sort()
h = hashlib.sha256()
for fp in files:
    rel = fp.relative_to(root).as_posix()
    h.update(rel.encode()); h.update(b'\0')
    h.update(fp.read_bytes()); h.update(b'\0')
print(h.hexdigest())
PY
"$SSOT/<directory>"
```

`check_updates` 信 DB 非空 hash；backfill 只补 NULL → 过期非空必须 `UPDATE`。

### M：id 升级（保留 enable）

id 为 PK 时：读出旧行 → `INSERT` 新 id（enable 原样）→ `DELETE` 旧 id。  
目标 id 已存在：各 `enabled_*` 按位或后删旧。

## profiles（project-slot）

**live** = `skills.enabled_*=1`（用户此刻启用）。  
**project-slot** = `payload.skills.<app>` 数组 = 某次拍照/离开 auto-save 的副本，可脏。  
**fat snapshot**（`set(slot)−set(live)`）→ 见 SKILL 顶部**唯一正向规则**（resnap/scrub JSON；live 只经 dispatch 或确认后的 apply）。

```sql
SELECT id, name, payload FROM profiles;
SELECT value FROM settings WHERE key = 'current_profile_id_claude';  -- 绑定名，≠ live 已 apply
SELECT id FROM skills WHERE enabled_claude = 1;  -- live 真相
```

`payload.skills.<app>`：`null` 未快照｜`[]` 空集｜`[canonical-id,…]` 目标。引用 **id** 不是 directory。  
卸载/M 后扫数组删悬空 id。

### resnap：用 live 覆盖某项目 slot（不改 enable）

`<profile-name>` / `<app_key>` / `<en_col>` 由用户点名或本机 `profiles` + app 表解析，**不写死**。

```bash
python3 - <<'PY'
import json, sqlite3, sys
from pathlib import Path
# argv: profile-name app_key en_col   e.g. MyProject claude enabled_claude
name, app_key, en_col = sys.argv[1], sys.argv[2], sys.argv[3]
con = sqlite3.connect(Path.home()/".cc-switch"/"cc-switch.db")
live = [r[0] for r in con.execute(
    f"SELECT id FROM skills WHERE {en_col}=1 ORDER BY directory"
)]
row = con.execute("SELECT id, payload FROM profiles WHERE name=?", (name,)).fetchone()
if not row:
    raise SystemExit(f"unknown profile: {name!r}; list: "
                     + str([r[0] for r in con.execute("SELECT name FROM profiles")]))
pid, raw = row
payload = json.loads(raw)
payload.setdefault("skills", {})[app_key] = live
con.execute(
    "UPDATE profiles SET payload=?, updated_at=CAST(strftime('%s','now') AS INTEGER) WHERE id=?",
    (json.dumps(payload, ensure_ascii=False), pid),
)
con.commit()
print(name, app_key, "→", len(live), "ids (live only)")
PY
# python3 resnap.py "<profile-name>" claude enabled_claude
```

### add id 到 slot（点名项目；默认不 apply）

```bash
python3 - <<'PY'
import json, sqlite3, sys
from pathlib import Path
# argv: profile-name skill-id app_key
name, skill_id, app_key = sys.argv[1], sys.argv[2], sys.argv[3]
con = sqlite3.connect(Path.home()/".cc-switch"/"cc-switch.db")
row = con.execute("SELECT id, payload FROM profiles WHERE name=?", (name,)).fetchone()
if not row:
    raise SystemExit(f"unknown profile: {name!r}")
pid, raw = row
payload = json.loads(raw)
cur = payload.setdefault("skills", {}).get(app_key)
if cur is None:
    cur = []
    payload["skills"][app_key] = cur
if skill_id not in cur:
    cur.append(skill_id)
con.execute(
    "UPDATE profiles SET payload=?, updated_at=CAST(strftime('%s','now') AS INTEGER) WHERE id=?",
    (json.dumps(payload, ensure_ascii=False), pid),
)
con.commit()
PY
# python3 add-slot.py "<profile-name>" "owner/repo:dir" claude
```

## mcp_servers / skill_repos

以 `.schema` 为准。MCP 默认 park；无 content_hash 管道。
