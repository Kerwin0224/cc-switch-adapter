# experience — 规则与方法（按需加载）

**查→治→查闭环**：`doctor`（只读诊断）→ `remedy`（按 findings 分发修复）→ `doctor`（复验）。
**三态所有权 + 快照引用**：SSOT 目录 / DB 行 / app 投影是 skill 的所有权状态；profile slot 是用户快照，可独立陈旧或 dangling。

维护纪律：本文件只收**可执行规则**；新事故先蒸馏成规则入位，再在文末「复盘档案」加一行出处。不写叙事体复盘。

## 事故模式

| 模式 | 症状 | doctor 发现 | 处置 |
|------|------|-------------|------|
| **孤儿残留** | DB 行在但 SSOT 目录没了；app 残留断链 symlink；profile slot 引用还在 → 项目应用时 toggle 失败 | D6 + D13（+ D9/D10） | `remedy` 只给 uninstall/register 命令；profile dangling 由用户显式 `slot scrub` |
| **SSOT 孤儿** | SSOT 有目录无 DB 行（手动拷入 / 同步产物） | D7 | `register --source <ssot>/<dir>`；桌面装完 skill 后跑一次 doctor，见 D7 即 register |
| **断链投影** | enable=1 但 app 目录 symlink 丢失（target 被删） | D9 | `remedy` 自动 `dispatch --enable` |
| **park 泄漏** | disable=0 但 app 目录残留 SSOT-link | D10 | `remedy` 自动 `dispatch --disable` |
| **pair drift** | claude 与 codex 不同步 | 无 D 码；`inventory.py` policy seam 报 drift | 用户点名对齐 → `dispatch` 双 app（trio drift 已随 opencode 解耦废止） |
| **fat snapshot** | slot 比 live 多（离开项目 auto-save / 手改） | D15（仅绑定 profile） | 用户点名项目 → `slot resnap` / `slot scrub`；**不**自动 enable |
| **点名删除** | 用户要求删掉某个 skill 并「清理干净」（pair 全开常见） | 无 D 码（正常态） | `uninstall --apply` 一次清行/SSOT/投影/lock；profile 无引用则零残留 |

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

## 删除与清理规则

- **SSOT 删除必须走 `uninstall --apply`，禁止手删目录**——所有权状态靠单一入口保证；dry-run 先列出全部删除面再落笔。
- **复验清单**：DB count=0、SSOT + 各 app 投影 `ls` 全消失、lock JSON 无 key、`doctor` FATAL 0 ERROR 0、`inventory` 行消失。
- **仓库订阅是独立关联面**：uninstall 不动 `skill_repos`；订阅去留先查该仓库剩余 skill（`gh api repos/<owner>/<repo>/contents/skills`），还有可装项就保留订阅；用户追加点名才 `DELETE FROM skill_repos`。
- **改名 vs 删除判定**：SSOT 同名/近义目录 + 备份目录 + 日志三者全空 → 删除残留，不是改名。
- profile 是用户**当前项目**时，slot 里每个 dangling id 都会在 apply 时变成用户可见警告；卸载不替用户改变快照，需显式 `slot scrub`。

## 云端 skill 更新检查（--remote + R3 之后）

**触发**：用户要求检查云端来源 skill（`owner/repo:path`）是否过时、同步上游、问"作者有没有出新版"。

**检查**（只读，报告 seam）：

```bash
python3 "$SKILL_DIR/doctor.py" --remote          # R1 仓库存在/归档 → R2 路径漂移 → R3 stale → R4 上游未装
python3 "$SKILL_DIR/doctor.py" --remote --no-cache   # 绕过 <home>/.cc-switch/remote-cache.json 重查
```

R2.path 提示"DB 需更新" → 用 `pipe.py migrate` 修正 id 路径（migrate 自动重算 hash、同步投影与 profile 快照）。R4.upstream 是 INFO，是否补装由用户决定。

**R3.stale 的更新流程**（作者未实现，`--remote` 只报不改）：

0. **方向判定（先于一切覆盖；出处见复盘档案 2026-08-25、2026-09-10）**：R3 的 "behind upstream" 只是「内容不同」的措辞化，判不了领先/落后。对任何可能被本地开发的仓库——尤其 **adapter 自身**（SKILL_DIR 即 SSOT 投影，永不进批量覆盖名单；对自身的任何 uninstall/覆盖都要先用 staging 副本执行收尾，否则砍掉的就是正在运行的 pipe.py）——先反查方向：`h = sha256(local SKILL.md 经 universal-newline 文本 encode())[:8]`，遍历上游 `git log --format=%H` 逐 commit 算 `git show <c>:SKILL.md` 同规则 hash。命中任一版本 ⇒ 本地是滞后副本，可安全覆盖；全不命中 ⇒ 本地存在未推送改动 ⇒ 停手报告用户，绝不 rsync。SSOT 不是 git clone，无快照无备份，`--delete` 覆盖即永久丢失。dry-run 的完成标准要包含方向证据，不是只有 diff 清单。
1. **取远程快照**：`https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip` 解压到临时目录（cc-switch `download_repo` 同款；ZIP 比 codeload tarball 快，tarball 下载可能被截断且无校验）。每仓库一次，全部 skill 共用。
2. **匹配**：按**目录名最后一段**（`rsplit('/')`，大小写不敏感）在解压树中定位 skill——天然容忍路径漂移，无需维护 id→新路径映射。
3. **确认**：目录级 `content_hash.py dir_hash()` 对比（R3 只比 SKILL.md；references/scripts 等目录文件也会变，实测 14 个 skill 的 SKILL.md 相同但目录 hash 不同，必须目录级确认）。
4. **覆盖**：`rsync -a --delete <快照>/ $SSOT/<directory>/`（`--delete` 清掉上游已删文件；symlink 投影自动跟随）。
5. **同步 DB**：路径漂移 → `migrate`（先内容后 migrate，顺序反了会把旧 hash 写进 DB）；无漂移 → `UPDATE skills SET content_hash=?, updated_at=? WHERE id=?`（等价 cc-switch `update_skill` 的 persist；**不要**用 migrate 同 id 刷，会产生无谓 DB 备份）。
6. **复验**：`doctor.py --full`（FATAL 0 ERROR 0）+ 重跑 `--remote` 确认 stale 清零。

**陷阱**：
- **`__pycache__` 计入哈希**：Rust/Python 的 dir_hash 只跳过 `.` 开头条目。本地目录有它就永远判 stale；运行 python 一律 `PYTHONDONTWRITEBYTECODE=1`，更新前清掉 SSOT 残留。
- **大仓库截断**：文档资产型仓库（实测 heygen-com/hyperframes）ZIP/tarball 都可能截断且无校验——终点是 `git clone --depth 1 --filter=blob:none --sparse` + `git sparse-checkout set <skill路径>`，只拉目标目录。
- **根级 skill**：id 形如 `owner/repo:SKILL.md` 时源目录是仓库根本身；步骤 2 匹配到 `SKILL.md` 即定位仓库根，staging 别把 `<src>/SKILL.md/` 当目录拼。
- **register 复制保 symlink**：pipe.py register 以 `copytree(..., symlinks=True)` 落 SSOT（2026-09-10 修复；此前物化 symlink，曾在升级 adapter 自身时拷坏自带 fixtures——staging 源含 symlink 时验证 `ls -la` 仍是指向）。
- **cc-switch `update_skill` 保留 id/directory**：只换内容与哈希，路径漂移必须单独 `migrate`。
- **离线/限流**：`--remote` 离线时降级为单个 WARN；用 `gh api`（认证 5000 req/h）比裸 urllib 稳。
- **CRLF 行尾会误报 R3.stale**：本地 `read_text` 通用换行把 CRLF→LF，远程保留 CRLF，哈希永远不同（browser-act 首例）。R3 已做行尾规范化（`\r\n`→`\n`）；手写对比脚本时同样要规范化，或用目录级 dir_hash（基于原始字节，不受行尾影响）。
- **R4.upstream 有噪声**：降级探测把仓库根目录的脚手架文件（Dockerfile、go.mod、CODEOWNERS 等）也当"skill"列出——已知局限，看名单时只信带 SKILL.md 的条目。

## 原则

- `remedy` 只自动做**可逆、语义明确**的修复（D9/D10，`--apply` 只代跑 `[AUTO]`；`[CMD]` 是打印的手动命令、`[SKIP]` 是用户决策，--apply 都不碰）；D6/D7/D13 涉及留、删或快照治理的决策，永远给命令而非代执行。
- slot 子命令只改 profiles JSON，**永不碰 live**；live 只经 `dispatch` 或用户明确 `apply`。
- pair 同步：live 集合以 claude/codex profile 槽位为准；opencode 已解耦（2026-08-25），保持默认关；分析先跑 `inventory.py`。
- 每轮处置后必须复跑 doctor 验证（查→治→查），以 `FATAL 0 ERROR 0` 收尾。

## 复盘档案（规则的出处索引，一案一行）

| 日期 | 事件一句话 | 沉淀到 |
|------|-----------|--------|
| 2026-08-04 | jd-coverage-review 被手删 SSOT 目录：DB 行 + 断链 symlink + 两个 dangling slot，项目 apply 时 toggle 失败 | 四查证据链；「删除必须走 uninstall」；fat snapshot 行的 dangling 语义 |
| 2026-08-14 | wps-office 点名删除：uninstall --apply 一次闭环；订阅因仓库尚余 3 个可装 skill 而保留 | 「删除与清理规则」整节 |
| 2026-08-25 | adapter 批量 R3 更新打掉未推送开发内容（本地 hash 不命中上游任一 commit；APFS 快照/编辑器历史/Trash/分支全空；用户确认放弃恢复） | R3 流程第 0 步方向判定 |
| 2026-09-10 | 同类事故第二次：批量「升级」未执行第 0 步，uninstall+register 重装 15 个 skill 把 08-25 重建的 pair 文档/脚本回滚到上游（经会话转录重放编辑恢复）；连带暴露 doctor "reinstall" 误导文案与 register 物化 symlink | SKILL.md 治步 R3 指针；doctor R3 文案改 "differs + 方向先行"；pipe.py 保 symlink；test_inventory pair 断言补齐 |
