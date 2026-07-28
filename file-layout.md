# 布局与 child-link

**runtime-first**：只读本机 `settings.json`，不读本机 cc-switch 开发树。

| `skillStorageLocation` | SSOT |
|------------------------|------|
| `cc_switch` | `~/.cc-switch/skills` |
| `unified` | `~/.agents/skills` |

`skillSyncMethod`：`auto`|`symlink`|`copy`。仅 **per-app enable** 后分发；**park** 无 app 条目。

## app 表

| app | 常见 skills 目录 | DB 列 | project scope |
|-----|------------------|-------|----------------|
| claude | `~/.claude/skills` | `enabled_claude` | claude |
| codex | `~/.codex/skills` | `enabled_codex` | codex |
| gemini | `~/.gemini/skills` | `enabled_gemini` | — |
| grokbuild | `~/.grok/skills` | `enabled_grokbuild` | — |
| opencode | `~/.config/opencode/skills` | `enabled_opencode` | — |
| hermes | `~/.hermes/skills` | `enabled_hermes` | — |

override 与 `.schema` 缺列时以本机为准。claude-desktop / openclaw：无 skill 分发。

## child-link 全文

```bash
# $APP=app skills 真目录；$name=directory；$SSOT 已解析
[ -d "$APP" ] || mkdir -p "$APP"
[ -L "$APP" ] && echo "FATAL parent-link" && exit 1
[ -L "$APP/$name" ] && rm "$APP/$name"
[ -d "$APP/$name" ] && rm -r "$APP/$name"
[ -e "$APP/$name" ] && echo "FAIL exists" && exit 1
ln -s "$SSOT/$name" "$APP/$name"
[ -L "$APP/$name" ] || exit 1
[ "$(readlink "$APP/$name")" = "$SSOT/$name" ] || exit 1
```

`copy`：目录复制替代 `ln -s`（临时目录 + rename）。失败不吞。

**parent-link**：`app/skills` → SSOT 时，删除子项可能删掉 SSOT。修复：`rm` 父链接 → `mkdir` → 对 enable=1 建 child-link。

## 状态对照

| | SSOT | DB | app |
|--|------|-----|-----|
| park | 有 | 行在，enable 0 | 无 |
| enable | 有 | 列 1 | child-link/copy |
| 旧散落 | 缺 | bare/无 | 实体副本 → C/M |
