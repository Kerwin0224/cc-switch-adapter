---
name: cc-switch-adapter
description: >
  closed-pipe：经 cc-switch 登记/迁移 skill 与 MCP——park 安装、canonical-id、
  project-slot（快照≠live）、doctor 体检、reconcile、orphan、parent-link。
  Use when the user installs or migrates skills via agent, or mentions
  cc-switch skill 管理、doctor、是否最新设计、默认不启用、Profiles、
  快照偏胖、bare id、check_updates 误报、orphan、父级 symlink。
---

# cc-switch-adapter

用 **closed-pipe** 代操：本机 SSOT → DB（**canonical-id** + **park** 或 **per-app enable**）→ 锁 → 仅 enable 后 **child-link**。存量用 **M** 迁到 **unified-row**；项目启用集走 **project-slot**（先读懂 **live vs 快照**）。

**权威源（runtime-first）**：① 本机 `settings.json` + `cc-switch.db` `.schema` + SSOT/app 磁盘 + `~/.agents/.skill-lock.json` → ② 可选云端 `https://github.com/farion1231/cc-switch` raw/手册 → ③ 本 skill 参考。行为以 ① 为准；**不把本机 cc-switch 开发树当前置**。

## 0. 每次：解析 SSOT

```bash
SSOT=$(python3 - <<'PY'
import json
from pathlib import Path
home = Path.home()
cfg = json.loads((home/".cc-switch"/"settings.json").read_text())
loc = cfg.get("skillStorageLocation", "cc_switch")
print(home/".agents"/"skills" if loc == "unified" else home/".cc-switch"/"skills")
PY
)
mkdir -p "$SSOT"
sqlite3 ~/.cc-switch/cc-switch.db ".schema skills" | head
```

**完成准则**：`$SSOT` 与 `skillStorageLocation` 一致；已知本机 `skills` 列（缺列跳过）。DB：`~/.cc-switch/cc-switch.db`；锁：`~/.agents/.skill-lock.json`。

## 1. 预检 parent-link

对已存在的 app `skills` 目录（含 override）：`[ -L "$app_dir" ]` → FATAL，先 **A**。

**完成准则**：每个存在的 app skills 路径都是真实目录。

## 共用协议

| 协议 | 何时 | 要点 |
|------|------|------|
| **park** | 只说安装/入库 | 有的 `enabled_*=0`，零 child-link；提示 UI 或 **P** |
| **per-app enable** | 点名 app，或 M/C 保留已开 | 只改点名列 + child-link |
| **child-link** | enable 为真 | 真目录下 `ln -s "$SSOT/$name"`；全文 [file-layout.md](file-layout.md) |
| **canonical-id** | 任何写入 id | GitHub：`owner/repo:<path>`（path 可含 `/`）；无源：`local:<name>`；禁 bare 与 `:.` |
| **live** | 判断「用户现在启用了什么」 | `skills.enabled_*=1` + 对应 app 磁盘投影——**唯一真相** |
| **project-slot** | 项目 JSON 里的 id 列表 | **上次拍照/离开时的启用集副本**，可脏、可偏胖；≠ live |

**ownership**：B/C 默认 park；**E** 改 live 仅用户点名 app；**P** 改快照仅用户点名项目，且先分清要改的是 live 还是 slot；**M** 保留 enable。

**runtime 数据 ≠ skill 正文**：profile 显示名、某机 skill 清单、当前绑定 id 只从本机 DB/settings 解析；正文与示例只用 `<profile-name>` / 机制词（live、slot、fat snapshot）。

---

## 分支路由

| 意图 | 分支 |
|------|------|
| parent-link | **A** |
| 新装 | **B** |
| orphan 导入 | **C** |
| 卸载 | **D** |
| 开/关 app（改 live） | **E** |
| hash / 误报 | **F** |
| doctor / 是否最新设计 / 体检 | **G** |
| MCP | **H** |
| 改项目 skill 列表 / 收瘦快照 / 解释 live≠快照 | **P** |
| bare id 等规范化 | **M** |

### A. 修 parent-link

`rm` 父链接 → `mkdir` → 对 enable=1（或用户要求全量）建 child-link。

**完成准则**：`$APP` 真目录；SSOT 未删；应启用项为合法 child-link。

### B. 安装（closed-pipe + park）

1. 内容进 `$SSOT/<directory>/`（含 `SKILL.md`）。  
2. DB：**canonical-id** + **park**；同名已存在则保留 enable、只补元数据。  
3. GitHub → 锁（[lock-file.md](lock-file.md)）。  
4. 点名 app → **E**；否则停（**不**因「当前项目」自动写入 project-slot）。  
5. hash NULL 或按 [db-schema.md](db-schema.md) 写。

**完成准则**：SSOT 实体 + canonical 行；未点名则 enable 全 0 且无 app 链接；GitHub 锁完整。

### C. 适配 orphan

副本→SSOT→源信息→DB。默认 park；用户要保持可用 → 发现集 per-app enable + child-link。

### D. 卸载

备份可选 → DELETE 行 → 拆各 app 链接 → 删 SSOT → 锁删键 → **所有** project-slot 去掉该 id。

### E. 分发（只动 live）

`UPDATE enabled_*` + 建/删 child-link。  
**完成准则**：DB enable 与磁盘一致；SSOT 在 disable 后仍在。

要点：E **不会**自动改 profiles。用户在绑定项目下关掉 skill，该项目 slot 可能仍留着该 id，直到切换项目触发 auto-save 或显式 **P resnap**。

### F. reconcile

重算 SSOT hash → `UPDATE content_hash`。  
**完成准则**：hash = 现场值；有源则 owner/name 非空。

### G. doctor（只读体检）

对照官方 skill 不变量跑 **doctor**（非修）：**unified-row**、**canonical-id**、SSOT、**child-link**（无 parent-link）、hash、live 投影、lock、**project-slot** 悬空/bare、**fat snapshot**。

1. 读 [doctor.md](doctor.md) 检查目录、category、报告 seam 与完成准则。  
2. 执行包根只读程序（**唯一实现**，勿手写等价脚本）：
   ```bash
   SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"  # 或本 skill 的绝对路径
   python3 "$SKILL_DIR/doctor.py"             # 可选 --root <fake-home> / --full
   ```
3. 按报告 `next:`（动词：migrate/dispatch/slot/register…）列出建议；**默认停**。用户点名「修」再 mutate。

**完成准则**：`[LEVEL:category] CODE` 报告 + `next:`；exit 仅 FATAL 非 0；零写入；fat 不得写成漏 enable；本机专名只出现在当次报告。

### H. MCP

`.schema` 为准；默认 park。

### P. project-slot（必读：live vs 快照）

#### 机制（勿再弄反）

| | **live** | **project-slot**（`profiles.payload.skills.<app>`） |
|--|----------|------------------------------------------------------|
| 存哪 | `skills.enabled_*` + app 目录链接 | `profiles` 行 JSON 里的 **id 数组** |
| 表示 | **此刻**开了哪些 | **某次** create / 离开该项目 auto-save / 手改时的启用集 |
| 谁改 | Skills 勾选、**E**、apply 项目 | 切项目前的 auto-save、create/resnapshot、**P** 手改 |
| 读法 | 「用户现在启用了 X」只看 live | 「快照里有 X」**不能**推出「用户启用了 X」 |

切换项目（产品）时：

1. **auto-save**：把**当前 live** 写回**正在离开**的项目的 slot（该 scope）。  
2. **apply**：按**目标**项目 slot 对 live 做 `toggle_app` diff（slot 有而 live 无 → 打开；slot 无而 live 有 → 关掉）。  
3. `current_profile_id_<scope>` **只是绑定名**；绑定名对应的 slot 与 live 可长期不一致（只绑指针、apply 未跑完、或在项目内改过 live 未 resnap）——**正常可能**。差集默认读作 **fat snapshot**，不是「该把差集全打开」。

`null` = 该侧从未快照（apply 不动）；`[]` = 空集（apply 清空）；`[id,…]` = 目标集。id 必须是 **canonical-id** / `local:…`，不是 directory 名。scope 仅 claude / claude-desktop / codex；gemini 等只用 **E**。

#### 判读规则（硬）

| 观察 | 正确结论 | 错误结论（禁止） |
|------|----------|------------------|
| slot 有、live 无 | **fat snapshot**（偏胖/过期）或未 apply | 「漏 enable 了，帮你打开」 |
| live 有、slot 无 | live 比快照新；切走会 auto-save 进离开的项目 | 「多开了，必须立刻关掉」除非用户要严格 apply |
| 绑定项目 slot ⊃ live | **以 live 为当下意图**；slot 待 resnap | 用 slot 覆盖用户已关掉的 skill |
| 用户说「没在该项目启用 X」 | 信用户 + 信 live；X 若在 slot → 脏 slot | 争辩「快照里有就是启用了」 |

#### 子操作（仅用户点名时）

1. **resnap（收瘦/对齐）**：`slot.claude = SELECT id FROM skills WHERE enabled_claude=1`（其它 app 列类推）。**只改 JSON，不改 enable**。用于「快照跟现在 live 一致」。  
2. **scrub**：去掉不在 `skills` 表的 id；bare→canonical（常随 **M**）。  
3. **add/remove id**：用户点名项目 + skill 时改数组；**默认不 apply**。  
4. **apply**：仅用户明确「按某项目套到 live / 马上生效」——会改 enable；若 slot 仍胖，会打开差集——**先确认或先 resnap**。

手改示例与表结构：[db-schema.md](db-schema.md)。

**完成准则**：

- 改动的 slot 与用户意图一致（resnap 后 `set(slot)==set(live)` 于该 app）  
- 未在「仅解释/清洗」场景下擅自 enable 差集  
- 项目名只来自用户点名或本机 `SELECT name FROM profiles`；未点名不猜；不把 git 路径当项目

### M. 规范化迁移

bare→canonical / `local:`；INSERT 拷贝 enable → DELETE 旧 id；合并按位或；scrub 全项目 slot；SSOT+链接；F。

**完成准则**：无 bare id；enable 不丢；slot 无悬空；parent-link 通过。

硬护栏：不用 `clear_skills` 当常规迁移；不整表 park。

---

## 参考（按需）

- [doctor.py](doctor.py) — doctor 可执行实现（报告 seam）  
- [doctor.md](doctor.md) — 检查项、category、报告格式（无嵌脚本）  
- [db-schema.md](db-schema.md) — 表、hash、park INSERT、profiles、resnap  
- [lock-file.md](lock-file.md) — 锁  
- [file-layout.md](file-layout.md) — 目录与 child-link  
- 云端（可选）：`farion1231/cc-switch`  
