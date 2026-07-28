# `.skill-lock.json`

路径固定：`~/.agents/.skill-lock.json`（不随 SSOT 移动）。

## 结构

```json
{
  "version": 3,
  "skills": {
    "<directory-or-short-name>": {
      "source": "owner/repo",
      "sourceType": "github",
      "sourceUrl": "https://github.com/owner/repo.git",
      "skillPath": "path/to/SKILL.md",
      "branch": "main",
      "skillFolderHash": "",
      "installedAt": "2026-06-09T08:38:52.000Z",
      "updatedAt": "2026-06-09T08:38:52.000Z"
    }
  },
  "dismissed": {}
}
```

## cc-switch 读取

仅导入/SSOT 迁移读锁；**check_updates 不读**。

| 字段 | 要 |
|------|-----|
| `source` | `owner/repo`，无域名 |
| `sourceType` | 必须 `github` 否则跳过 |
| `sourceUrl` / `branch` / `skillPath` | 要；branch 优先于 URL 解析 |

key 是目录短名，不是 DB **canonical-id**。分支 M 用 `source` 生成 `owner/repo:directory`。

## jq 添加

```bash
jq --arg name "my-skill" --arg source "owner/repo" \
   --arg url "https://github.com/owner/repo.git" \
   --arg path "skills/my-skill/SKILL.md" --arg branch "main" \
   --arg now "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" \
   '.skills[$name] = {source:$source, sourceType:"github", sourceUrl:$url,
     skillPath:$path, branch:$branch, skillFolderHash:"", installedAt:$now, updatedAt:$now}' \
   ~/.agents/.skill-lock.json > /tmp/skill-lock.json \
&& mv /tmp/skill-lock.json ~/.agents/.skill-lock.json
```

无文件时先建 `{"version":3,"skills":{},"dismissed":{}}`。删除：`jq 'del(.skills["name"])'`。

## 要点

- 写锁 ≠ enable；**park** 也写锁  
- 修误报改 DB `content_hash`，不改 `skillFolderHash`  
- 非 GitHub 不写假 `sourceType: github` → DB `local:`  
