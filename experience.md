# experience — 事故模式与标准处置（按需加载）

**查→治→查闭环**：`doctor`（只读诊断）→ `remedy`（按 findings 分发修复）→ `doctor`（复验）。  
**三态所有权 + 快照引用**：SSOT 目录 / DB 行 / app 投影是 skill 的所有权状态；profile slot 是用户快照，可独立陈旧或 dangling。

## 事故模式

| 模式 | 症状 | doctor 发现 | 处置 |
|------|------|-------------|------|
| **孤儿残留** | DB 行在但 SSOT 目录没了；app 残留断链 symlink；profile slot 引用还在 → 项目应用时 toggle 失败 | D6 + D13（+ D9/D10） | `remedy` 只给 uninstall/register 命令；profile dangling 由用户显式 `slot scrub` |
| **SSOT 孤儿** | SSOT 有目录无 DB 行（手动拷入 / 同步产物） | D7 | `register --source <ssot>/<dir>` |
| **断链投影** | enable=1 但 app 目录 symlink 丢失（target 被删） | D9 | `remedy` 自动 `dispatch --enable` |
| **park 泄漏** | disable=0 但 app 目录残留 SSOT-link | D10 | `remedy` 自动 `dispatch --disable` |
| **trio drift** | claude/codex 与 opencode 不同步（profile 只配前两者，opencode 忘对齐） | 无 D 码；`inventory.py` policy seam 报 drift | 用户点名对齐 → `dispatch` 三件套 |
| **fat snapshot** | slot 比 live 多（离开项目 auto-save / 手改） | D15（仅绑定 profile） | 用户点名项目 → `slot resnap` / `slot scrub`；**不**自动 enable |

## 诊断证据链（四查）

出现任何"Skill 不存在 / toggle failed"类警告时，按固定顺序四查：

1. **DB 行**：`SELECT id, directory, enabled_claude, enabled_codex FROM skills WHERE id LIKE '%<name>%'`
2. **SSOT 目录**：`ls $SSOT/<directory>`（缺失 = 孤儿残留源）
3. **app 投影**：`ls -la ~/.claude/skills/ ~/.codex/skills/ | grep <name>`（断链 symlink 是残留标记）
4. **profile slot**：`python3 pipe.py slot list --profile <name>`（`# dangling` 标记）

四查结果决定走向：查 1 有 + 查 2 无 = 孤儿残留 → 走**卸载清理**；查 2 有 + 查 1 无 = SSOT 孤儿 → 走 **register**。

## 标准处置命令

```bash
python3 "$SKILL_DIR/doctor.py"                                  # 查
python3 "$SKILL_DIR/remedy.py" [--apply]                        # 治（dry-run 默认）
python3 "$SKILL_DIR/pipe.py" slot list|scrub|resnap|add|remove  # slot 治理（dry-run 默认，--apply 写）
python3 "$SKILL_DIR/pipe.py" uninstall --id 'local:x' [--apply] # 完整卸载（SSOT 缺失时自动走孤儿路径）
python3 "$SKILL_DIR/pipe.py" register --id 'local:x' --directory x --source ... [--app claude]
```

## 云端 skill 更新检查（--remote + R3 之后）

**触发**：用户要求检查云端来源 skill（`owner/repo:path`）是否过时、同步上游、问"作者有没有出新版"。

**检查**（只读，报告 seam）：

```bash
python3 "$SKILL_DIR/doctor.py" --remote          # R1 仓库存在/归档 → R2 路径漂移 → R3 stale → R4 上游未装
python3 "$SKILL_DIR/doctor.py" --remote --no-cache   # 绕过 <home>/.cc-switch/remote-cache.json 重查
```

R2.path 提示"DB 需更新" → 用 `pipe.py migrate` 修正 id 路径（migrate 自动重算 hash、同步投影与 profile 快照）。R4.upstream 是 INFO，是否补装由用户决定。

**R3.stale 的更新流程**（作者未实现，`--remote` 只报不改）：

1. **取远程快照**：`https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip` 解压到临时目录（cc-switch `download_repo` 同款；ZIP 比 codeload tarball 快，tarball 下载可能被截断且无校验）。每仓库一次，全部 skill 共用。
2. **匹配**：按**目录名最后一段**（`rsplit('/')`，大小写不敏感）在解压树中定位 skill——天然容忍路径漂移，无需维护 id→新路径映射。
3. **确认**：目录级 `content_hash.py dir_hash()` 对比（R3 只比 SKILL.md；references/scripts 等目录文件也会变，实测 14 个 skill 的 SKILL.md 相同但目录 hash 不同，必须目录级确认）。
4. **覆盖**：`rsync -a --delete <快照>/ $SSOT/<directory>/`（`--delete` 清掉上游已删文件；symlink 投影自动跟随）。
5. **同步 DB**：路径漂移 → `migrate`（先内容后 migrate，顺序反了会把旧 hash 写进 DB）；无漂移 → `UPDATE skills SET content_hash=?, updated_at=? WHERE id=?`（等价 cc-switch `update_skill` 的 persist；**不要**用 migrate 同 id 刷，会产生无谓 DB 备份）。
6. **复验**：`doctor.py --full`（FATAL 0 ERROR 0）+ 重跑 `--remote` 确认 stale 清零。

**陷阱**：
- **`__pycache__` 计入哈希**：Rust/Python 的 dir_hash 只跳过 `.` 开头条目。本地目录有它就永远判 stale；运行 python 一律 `PYTHONDONTWRITEBYTECODE=1`，更新前清掉 SSOT 残留。
- **cc-switch `update_skill` 保留 id/directory**：只换内容与哈希，路径漂移必须单独 `migrate`。
- **离线/限流**：`--remote` 离线时降级为单个 WARN；用 `gh api`（认证 5000 req/h）比裸 urllib 稳。
- **CRLF 行尾会误报 R3.stale**：本地 `read_text` 通用换行把 CRLF→LF，远程保留 CRLF，哈希永远不同（browser-act 首例）。R3 已做行尾规范化（`\r\n`→`\n`）；手写对比脚本时同样要规范化，或用目录级 dir_hash（基于原始字节，不受行尾影响）。
- **R4.upstream 有噪声**：DRIFT_ROOTS 把仓库根目录的脚手架文件（Dockerfile、go.mod、CODEOWNERS 等）也当"skill"列出——是已知局限，看名单时只信带 SKILL.md 的条目。

## 复盘：2026-08-04 jd-coverage-review 孤儿事故

**现场**：DB 行 `local:jd-coverage-review` 存在（enabled_codex=1），SSOT 目录已消失，`~/.codex/skills/` 留断链 symlink，`求职` profile 的 claude+codex slot 各留一条引用。项目应用 profile 时 claude toggle 该 skill → "Skill 不存在于 SSOT"。

**根因**：SSOT 目录被删除时未走统一卸载路径——只删了内容，没同步 DB 行 / 投影 / slot 引用。改名疑云排查后确认：SSOT 中无任何 jd 相关目录，job-scout / qingdao-ai-resume 是独立 skill，备份目录无此 skill，日志无操作记录 → 判定为删除残留而非改名。

**处置**：删 codex 断链 symlink → 删 DB 行 → scrub 两个 profile slot 引用；随后 `register` job-scout（install-enable claude，与已有 live 投影对齐）。doctor 复验 FATAL 0 ERROR 0。

**教训**：
- **SSOT 删除必须走 `uninstall`，禁止手删 SSOT 目录**——所有权状态靠单一入口保证；快照引用由用户显式治理。
- 桌面上/同步中装 skill 后跑一次 doctor；出现 D7（SSOT 孤儿）立即 register，避免 live 与 DB 脱节。
- 判断"改名 vs 删除"：查 SSOT 是否有同名/近义目录 + 备份目录 + 日志；都不存在 → 删除残留，不是改名。
- profile 是用户**当前项目**时，slot 里每个 dangling id 都会在 apply 时变成一条用户可见警告；卸载不替用户改变快照，需显式 `slot scrub`。

## 原则

- `remedy` 只自动做**可逆、语义明确**的修复（D9/D10）；D6/D7/D13 涉及留、删或快照治理的决策，永远给命令而非代执行。
- slot 子命令只改 profiles JSON，**永不碰 live**；live 只经 `dispatch` 或用户明确 `apply`。
- 三件套同步：profile 槽位覆盖 claude/codex，opencode 用 `dispatch` 对齐；分析先跑 `inventory.py`。
- 每轮处置后必须复跑 doctor 验证（查→治→查），以 `FATAL 0 ERROR 0` 收尾。
