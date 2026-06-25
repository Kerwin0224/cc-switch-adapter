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

## 必要字段

| 字段 | 类型 | 说明 | 缺失后果 |
|------|------|------|---------|
| `source` | string | `"owner/repo"` 格式 | cc-switch 导入时无法恢复源信息 → 标记为 `local:*` |
| `sourceType` | string | 固定 `"github"` | 导入时跳过该条目 |
| `sourceUrl` | string | Git 仓库 URL (含 `.git`) | 导入时无法解析分支 |
| `skillPath` | string | 仓库中 SKILL.md 的路径 | 导入时使用默认路径猜测 |
| `branch` | string | Git 分支名 | 默认 `"HEAD"`，后续回退到 main/master |
| `skillFolderHash` | string | SHA-256 | 用于去重/完整性校验 |

## 添加条目 (jq)

```bash
jq --arg name "my-skill" \
   --arg source "owner/repo" \
   --arg url "https://github.com/owner/repo.git" \
   --arg path "skills/my-skill/SKILL.md" \
   --arg branch "main" \
   --arg hash "$(echo -n 'installed' | shasum -a 256 | cut -d' ' -f1)" \
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

## 删除条目 (jq)

```bash
jq 'del(.skills["my-skill"])' ~/.agents/.skill-lock.json > /tmp/skill-lock.json && \
mv /tmp/skill-lock.json ~/.agents/.skill-lock.json
```

## cc-switch 如何消费此文件

cc-switch 的 `parse_agents_lock()` 函数在以下场景读取此文件：

1. **`import_from_apps()`** — 从应用目录导入未管理的 skill 时，查找 lock 文件恢复源信息
2. **`migrate_skills_to_ssot()`** — 首次启动迁移时，重建数据库中的 repo_owner/repo_name

## 关键约束

- **source 必须是 `owner/repo` 格式**，不能含 `.com` 等域名（cc-switch 会过滤）
- **sourceType 必须是 `"github"`**，其他类型被跳过
- **skillPath 以仓库根为基准**，指向 SKILL.md 位置
- 此文件是 `~/.agents/` 社区规范的一部分，不仅 cc-switch 使用
