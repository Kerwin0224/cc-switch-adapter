# 布局与 child-link

**runtime-first**：只读本机 `settings.json`。

| `skillStorageLocation` | SSOT |
|------------------------|------|
| `cc_switch` | `~/.cc-switch/skills` |
| `unified` | `~/.agents/skills` |

`skillSyncMethod`：`auto`|`symlink`|`copy`。仅 **enable** 后分发；**park** 无 app 条目。

可变实现优先 [pipe.py](pipe.py)（已处理 parent-link、symlink/copy、安全删除）。

## app 表

| app | 常见 skills 目录 | DB 列 | project scope |
|-----|------------------|-------|----------------|
| claude | `~/.claude/skills` | `enabled_claude` | claude |
| codex | `~/.codex/skills` | `enabled_codex` | codex |
| gemini | `~/.gemini/skills` | `enabled_gemini` | — |
| grokbuild | `~/.grok/skills` | `enabled_grokbuild` | — |
| opencode | `~/.config/opencode/skills` | `enabled_opencode` | — |
| hermes | `~/.hermes/skills` | `enabled_hermes` | — |

override 与缺列以本机为准。claude-desktop / openclaw：无 skill 分发。

## child-link（安全）

**可替换的投影**仅限：

- 指向本 skill SSOT 叶的 **symlink**，或  
- **含 `SKILL.md` 的目录**（copy 投影）

**禁止**对不透明目录执行 `rm -r`（无 `SKILL.md`、非我们的链接）。遇不透明路径 → 失败并报告，由用户决定。

```bash
# $APP=app skills 真目录；$name=directory；$SSOT 已解析
[ -d "$APP" ] || mkdir -p "$APP"
[ -L "$APP" ] && echo "FATAL parent-link" && exit 1
# 仅当是我们的投影时才删（symlink→SSOT 或 含 SKILL.md 的目录）
if [ -L "$APP/$name" ]; then
  rm "$APP/$name"
elif [ -d "$APP/$name" ] && [ -f "$APP/$name/SKILL.md" ]; then
  rm -r "$APP/$name"
elif [ -e "$APP/$name" ]; then
  echo "FAIL opaque path, refuse rm: $APP/$name"; exit 1
fi
ln -s "$SSOT/$name" "$APP/$name"   # 或 copy 树 + rename
[ -e "$APP/$name" ] || exit 1
```

`copy`：`cp -R` 到临时名再 `mv`；失败不吞。  
`auto`：symlink 失败则 copy（与官方一致）。

**parent-link**：`app/skills` → SSOT 整链时，删子项可能毁 SSOT。修复：`rm` 父链 → `mkdir` → 对 enable=1 建 child-link。

## 状态对照

| | SSOT | DB | app |
|--|------|-----|-----|
| park | 有 | 行在，enable 0 | 无 |
| enable | 有 | 列 1 | child-link/copy |
| 旧散落 | 缺 | bare/无 | 实体 → **register** / **migrate** |
