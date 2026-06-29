# .skill-lock.json 格式

路径: `~/.agents/.skill-lock.json`

## 完整结构

```json
{
  "version": 3,
  "skills": {
    "<skill-name>": {
      "source": "<owner>/<repo>",
      "sourceType": "github",
      "sourceUrl": "https://github.com/<owner>/<repo>.git",
      "skillPath": "<path/to/SKILL.md>",
      "skillFolderHash": "<sha256>",
      "branch": "<branch>",
      "installedAt": "2026-06-09T08:38:52.314Z",
      "updatedAt": "2026-06-09T08:38:52.314Z"
    }
  },
  "dismissed": {}
}
```

## cc-switch 实际消费的字段（关键修正）

cc-switch 的 `parse_agents_lock()`（skill.rs:383-437）**只读 5 个字段**，其余忽略。这是社区规范文件，不止 cc-switch 用，但就 cc-switch 而言：

| 字段 | cc-switch 是否消费 | 作用 | 缺失后果 |
|------|------------------|------|---------|
| `source` | ✅ 是 | `"owner/repo"` 格式，split 出 owner/repo | 无法恢复源信息 → 标记 `local:*` |
| `sourceType` | ✅ 是 | 必须 == `"github"`，否则整条跳过（skill.rs:414） | 该条目被跳过 |
| `sourceUrl` | ✅ 是 | 仅用于**提取 branch**（见下） | branch 回退到默认 |
| `skillPath` | ✅ 是 | 仓库内 SKILL.md 路径 | 用默认路径猜测 |
| `branch` | ✅ 是 | Git 分支，优先级最高 | 回退到 source_branch，再回退到 sourceUrl 提取 |
| `skillFolderHash` | ❌ **不读** | cc-switch 不消费 | 无后果（仅社区规范） |
| `installedAt` / `updatedAt` | ❌ **不读** | cc-switch 不消费 | 无后果 |

### sourceUrl 的真实用途（放宽要求）

`parse_branch_from_source_url()`（skill.rs:330-368）从 sourceUrl 提取 branch，支持三种格式：

- `.../tree/<branch>/...`（GitHub tree URL）
- `...git#<branch>`（fragment）
- `...?branch=<branch>` 或 `...?ref=<branch>`（query）

**cc-switch 不要求 sourceUrl 含 `.git`**，也不用 sourceUrl 解析 owner/repo（owner/repo 来自 `source` 字段）。所以：

- `https://github.com/owner/repo.git` ✅
- `https://github.com/owner/repo/blob/main/SKILL.md` ✅（cc-switch 不解析 blob URL 提取 branch，会回退到 `branch` 字段）
- `https://github.com/owner/repo.git#main` ✅（可从 fragment 提 branch）

**最稳妥**：`source` 用 `owner/repo`，`sourceUrl` 用 `.git` URL，`branch` 显式写明。三者都给，cc-switch 一定能正确恢复。

## branch 解析优先级

cc-switch 取 branch 的顺序（skill.rs:418-420）：

1. `branch` 字段（normalize 后非空）
2. `source_branch` 字段（normalize 后非空）
3. 从 `sourceUrl` 提取

三个都失败 → branch 为 None → 后续回退到 `"HEAD"`，再回退 main/master。

## 必填字段（就 cc-switch 而言）

| 字段 | 类型 | 说明 | 缺失后果 |
|------|------|------|---------|
| `source` | string | `"owner/repo"` 格式 | cc-switch 导入时无法恢复源信息 → 标记为 `local:*` |
| `sourceType` | string | 必须 `"github"` | 导入时跳过该条目 |
| `sourceUrl` | string | 能提取 branch 的 URL（推荐 `.git`） | branch 回退到默认 |
| `skillPath` | string | 仓库中 SKILL.md 的路径 | 导入时用默认路径猜测 |
| `branch` | string | Git 分支名 | 回退到 sourceUrl 提取，再回退默认 |

`skillFolderHash` / `installedAt` / `updatedAt` 是社区规范字段，cc-switch 不读，但保留有助于其他工具。**不要把 skillFolderHash 当成 cc-switch 更新检测的依据**——更新检测用的是 DB 的 `content_hash`（见 [db-schema.md](db-schema.md)）。

## cc-switch 何时消费此文件

`parse_agents_lock()` 在以下场景被调用：

1. **`import_from_apps()`**（skill.rs:1447-1548）— 从应用目录导入未管理 skill 时，查 lock 文件恢复 repo_owner/repo_name
2. **`migrate_skills_to_ssot()`**（skill.rs:2943）— 首次启动迁移时，重建数据库中的源信息

**注意**：`check_updates()` **不读**此文件。更新检测只看 DB 的 `content_hash`。

## 添加条目 (jq)

```bash
jq --arg name "my-skill" \
   --arg source "owner/repo" \
   --arg url "https://github.com/owner/repo.git" \
   --arg path "skills/my-skill/SKILL.md" \
   --arg branch "main" \
   --arg hash "$(echo -n 'placeholder' | shasum -a 256 | cut -d' ' -f1)" \
   --arg now "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" \
   '.skills[$name] = {
      source: $source,
      sourceType: "github",
      sourceUrl: $url,
      skillPath: $path,
      branch: $branch,
      skillFolderHash: $hash,
      installedAt: $now,
      updatedAt: $now
    }' ~/.agents/.skill-lock.json > /tmp/skill-lock.json && \
mv /tmp/skill-lock.json ~/.agents/.skill-lock.json
```

> `skillFolderHash` 这里填占位值即可——cc-switch 不读它。若要让其他工具能用，可算真实目录哈希，但 cc-switch 的更新检测不依赖此值。

## 删除条目 (jq)

```bash
jq 'del(.skills["my-skill"])' ~/.agents/.skill-lock.json > /tmp/skill-lock.json && \
mv /tmp/skill-lock.json ~/.agents/.skill-lock.json
```

## 关键约束

- **source 必须是 `owner/repo` 格式**，不能含 `github.com` 等域名（`split_once('/')` 只切第一刀，skill.rs:417）
- **sourceType 必须 == `"github"`**，其他类型整条跳过
- **skillPath 以仓库根为基准**，指向 SKILL.md 位置
- **更新检测不靠此文件**：`check_updates()` 只用 DB `content_hash`。修"不一致"要改 DB，不是改锁文件
- 此文件是 `~/.agents/` 社区规范的一部分，不仅 cc-switch 使用
