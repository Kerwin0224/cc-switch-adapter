# experience — 事故模式与标准处置（按需加载）

**查→治→查闭环**：`doctor`（只读诊断）→ `remedy`（按 findings 分发修复）→ `doctor`（复验）。  
**四态一致**：SSOT 目录 / DB 行 / app 投影 / profile slot 引用 —— 四者必须同步增删，任何单独改一处都会产生孤儿。

## 事故模式

| 模式 | 症状 | doctor 发现 | 处置 |
|------|------|-------------|------|
| **孤儿残留** | DB 行在但 SSOT 目录没了；app 残留断链 symlink；profile slot 引用还在 → 项目应用时 toggle 失败 | D6 + D13（+ D9/D10） | `remedy` 自动清投影/引用；D6 需用户决策：`uninstall`（清残留）或 `register`（重建） |
| **SSOT 孤儿** | SSOT 有目录无 DB 行（手动拷入 / 同步产物） | D7 | `register --source <ssot>/<dir>` |
| **断链投影** | enable=1 但 app 目录 symlink 丢失（target 被删） | D9 | `remedy` 自动 `dispatch --enable` |
| **park 泄漏** | disable=0 但 app 目录残留 SSOT-link | D10 | `remedy` 自动 `dispatch --disable` |
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

## 复盘：2026-08-04 jd-coverage-review 孤儿事故

**现场**：DB 行 `local:jd-coverage-review` 存在（enabled_codex=1），SSOT 目录已消失，`~/.codex/skills/` 留断链 symlink，`求职` profile 的 claude+codex slot 各留一条引用。项目应用 profile 时 claude toggle 该 skill → "Skill 不存在于 SSOT"。

**根因**：SSOT 目录被删除时未走统一卸载路径——只删了内容，没同步 DB 行 / 投影 / slot 引用。改名疑云排查后确认：SSOT 中无任何 jd 相关目录，job-scout / qingdao-ai-resume 是独立 skill，备份目录无此 skill，日志无操作记录 → 判定为删除残留而非改名。

**处置**：删 codex 断链 symlink → 删 DB 行 → scrub 两个 profile slot 引用；随后 `register` job-scout（install-enable claude，与已有 live 投影对齐）。doctor 复验 FATAL 0 ERROR 0。

**教训**：
- **SSOT 删除必须走 `uninstall`，禁止手删 SSOT 目录**——四态一致性靠单一入口保证。
- 桌面上/同步中装 skill 后跑一次 doctor；出现 D7（SSOT 孤儿）立即 register，避免 live 与 DB 脱节。
- 判断"改名 vs 删除"：查 SSOT 是否有同名/近义目录 + 备份目录 + 日志；都不存在 → 删除残留，不是改名。
- profile 是用户**当前项目**时，slot 里每个 dangling id 都会在 apply 时变成一条用户可见警告——slot 治理（scrub）与卸载强绑定，不能省。

## 原则

- `remedy` 只自动做**可逆、语义明确**的修复（D9/D10/D13）；D6/D7 涉及"留 vs 删"的决策，永远给命令而非代执行。
- slot 子命令只改 profiles JSON，**永不碰 live**；live 只经 `dispatch` 或用户明确 `apply`。
- 每轮处置后必须复跑 doctor 验证（查→治→查），以 `FATAL 0 ERROR 0` 收尾。
