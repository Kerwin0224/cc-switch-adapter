---
name: cc-switch-adapter
description: >
  closed-pipe：经 cc-switch 登记/迁移 skill——install-enable 或 park、canonical-id、
  project-slot（live≠slot）、doctor、register/dispatch、parent-link。
  Use when the user installs or migrates skills via agent, or mentions
  cc-switch skill 管理、Profiles、fat snapshot、bare id、parent-link。
---

# cc-switch-adapter

用 **closed-pipe** 代操：本机 SSOT → DB（**canonical-id** + **park** 或 **install-enable**）→ 锁 → 仅 enable 后 **child-link**。存量用 **migrate**；项目启用集走 **project-slot**（先分清 **live** vs **slot**）。

**权威源（runtime-first）**：① 本机 `settings.json` + `cc-switch.db` + 磁盘 + 锁 → ② 可选云端 `farion1231/cc-switch` → ③ 本 skill。以 ① 为准。

## 官方产品 vs adapter-policy

| | **官方桌面应用** | **本 adapter（agent 旁路）** |
|--|------------------|------------------------------|
| 新装默认 | **install-enable**：只开**当前 app**，立刻投影 | 用户**未点名 app** → **park**（全 `enabled_*=0`，零投影） |
| 点名 app | UI 勾选 / 安装进该 app | **install-enable** 该 app（≈ 官方 `only(app)`） |
| 「现在开了什么」 | live | 同样只认 **live**（`enabled_*` + 投影） |
| 卸载 | 删 SSOT/DB/投影；**不** scrub 各项目 slot | 默认可 scrub 全部 **project-slot** 中该 id（**adapter-policy** 卫生，非官方行为） |
| 体检 | 无此 CLI | **doctor**（只读 `doctor.py`） |
| 改 live | UI / apply 项目 | **dispatch**（用户点名）或明确 **apply** |

**park** = adapter-policy 入库默认，**不是**「官方安装就是全关」。  
**install-enable** = 点名 app 时与官方一致：开该列 + **child-link**。

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

**完成准则**：`$SSOT` 与 `skillStorageLocation` 一致；已知本机 `skills` 列。DB：`~/.cc-switch/cc-switch.db`；锁：`~/.agents/.skill-lock.json`。

## 1. 预检 parent-link

对已存在的 app `skills` 目录：`[ -L "$app_dir" ]` → FATAL，先 **migrate**（A）。

**完成准则**：每个存在的 app skills 路径都是真实目录。

## 共用协议

| 词 | 含义 |
|----|------|
| **park** | adapter-policy：全 `enabled_*=0`，零 child-link |
| **install-enable** | 点名 app：只开该列 + child-link（≈ 官方） |
| **child-link** | enable 后在真目录下链/拷 SSOT 子项；全文 [file-layout.md](file-layout.md) |
| **canonical-id** | `owner/repo:<path>` 或 `local:<name>`；禁 bare 与 `:.` |
| **live** | `enabled_*=1` + 对应 app 投影——**唯一「现在开了什么」** |
| **project-slot** | `profiles.payload.skills.<app>` 的 id 列表：某次拍照/离开时的副本，可脏 |
| **fat snapshot** | `set(slot) − set(live)` 非空（见下方**唯一规则**） |
| **closed-pipe** | SSOT → DB → 锁 → 仅 enable 后投影 |
| **doctor** | 只读体检；实现 = [doctor.py](doctor.py) |

**ownership**：未点名 app → **park**；点名 app → **install-enable** / **dispatch**；改 slot 仅用户点名项目（**slot**）；**migrate** 保留 enable。

**runtime 数据 ≠ skill 正文**：profile 显示名、本机清单只从 DB 读；正文只用 `<profile-name>` / 机制词。

### fat snapshot（唯一正向规则）

```
set(slot) − set(live) 非空
  → 报告为 fat snapshot（policy）
  → 可选：对该项目 slot 做 resnap / scrub（只改 profiles JSON）
  → live 只经 dispatch，或用户明确「按该项目 apply」且已确认/已 resnap
```

其它文件若提到 slot⊃live，只指向本条，不另写「禁止漏开」堆叠。

---

## 分支路由

字母为锚；`doctor` 报告的 `next:` 用动词（migrate / dispatch / slot / register）。

| 意图 | 锚 | 动词 |
|------|-----|------|
| parent-link | **A** | migrate |
| 新装 | **B** | register（+ 可选 install-enable） |
| orphan 导入 | **C** | register |
| 卸载 | **D** | migrate |
| 开/关 app（改 live） | **E** | dispatch |
| hash / 误报 | **F** | migrate |
| doctor / 体检 | **G** | doctor → stop |
| MCP | **H** | register |
| 改项目 skill 列表 / resnap | **P** | slot |
| bare id 规范化 | **M** | migrate |

### A. 修 parent-link

`rm` 父链接 → `mkdir` → 对 enable=1（或用户要求全量）建 child-link。

**完成准则**：`$APP` 真目录；SSOT 未删；应启用项为合法 child-link。

### B. 安装（closed-pipe）

1. 内容进 `$SSOT/<directory>/`（含 `SKILL.md`）。  
2. DB：**canonical-id**；未点名 app → **park**；同名已存在则保留 enable、只补元数据。  
3. GitHub → 锁（[lock-file.md](lock-file.md)）。  
4. 用户点名 app → **install-enable**（走 **E**）；否则停（**不**因「当前项目」自动写 project-slot）。  
5. hash 按 [db-schema.md](db-schema.md)。

**完成准则**：SSOT + canonical 行；未点名则全 park 且无 app 链接；点名则该 app live 与投影一致；GitHub 锁完整。

### C. 适配 orphan

副本→SSOT→源信息→DB。默认 **park**；用户要保持可用 → **install-enable** 发现集 + child-link。

### D. 卸载

备份可选 → DELETE 行 → 拆各 app 链接 → 删 SSOT → 锁删键 → scrub **所有** project-slot 中该 id（adapter-policy；官方不保证 scrub）。

### E. 分发 / install-enable（只动 live）

`UPDATE enabled_*` + 建/删 child-link。  
**完成准则**：DB enable 与磁盘一致；SSOT 在 disable 后仍在。

E **不**自动改 profiles。绑定项目下关掉 skill 后，slot 可能仍留该 id，直到切换项目 auto-save 或显式 **P resnap**。

### F. reconcile

重算 SSOT hash → `UPDATE content_hash`。  
**完成准则**：hash = 现场值；有源则 owner/name 非空。

### G. doctor（只读）

1. 需要检查目录/格式时读 [doctor.md](doctor.md)。  
2. 执行包根程序（**唯一实现**）：
   ```bash
   # SKILL_DIR = 本 skill 安装目录（用户或 agent 已知路径；勿依赖 $0）
   python3 "$SKILL_DIR/doctor.py"    # 可选 --root <fake-home> / --full
   ```
3. 打印报告；按 `next:` 列出建议；**默认停**。用户点名「修」再 mutate。

**完成准则**：完整报告 + `next:`；仅 FATAL 时 exit≠0；零写入；fat 只指向上方正向规则；本机专名只出现在当次报告。

### H. MCP

`.schema` 为准；默认 **park**。

### P. project-slot

| | **live** | **project-slot** |
|--|----------|------------------|
| 存哪 | `skills.enabled_*` + 投影 | `profiles` JSON 里的 id 数组 |
| 表示 | **此刻**开了哪些 | 某次 create / 离开 auto-save / 手改时的副本 |
| 谁改 | UI、**E**、apply | auto-save、resnap、**P** |
| 读法 | 「现在启用了 X」只看 live | slot 有 X **不能**推出「现在启用了 X」 |

产品切换项目时：① 离开项 **auto-save** live→slot；② 目标项 **apply** 按 slot 对 live 做最小 diff；③ `current_profile_id_*` 只是绑定名，可与 live 长期不一致。

`null` = 未快照（apply 不动）；`[]` = 空集；`[id,…]` = 目标集。id 用 **canonical-id**，不是 directory。scope 仅 claude / claude-desktop / codex；其它 app 只用 **E**。

**判读**：一律用上方 **fat snapshot** 正向规则。  
- slot 有、live 无 → fat → resnap/scrub 或报告；**不**自动 enable  
- live 有、slot 无 → live 更新；切走会 auto-save；非用户要求则不强制关  
- 用户说「这项目没启用 X」→ 信用户 + live；X 在 slot → 脏 slot

**子操作**（仅用户点名）：

1. **resnap**：`slot.<app> = SELECT id … WHERE enabled_*=1`——**只改 JSON**  
2. **scrub**：去掉表中不存在的 id；bare→canonical（常随 **M**）  
3. **add/remove id**：改数组；**默认不 apply**  
4. **apply**：用户明确「按某项目套到 live」——会改 enable；slot 仍胖会打开差集 → **先确认或先 resnap**

SQL 示例：[db-schema.md](db-schema.md)。

**完成准则**：slot 与意图一致（resnap 后该 app `set(slot)==set(live)`）；解释/清洗场景不擅自改 live；项目名来自用户或本机 `SELECT name FROM profiles`。

### M. 规范化迁移

bare→canonical / `local:`；INSERT 拷贝 enable → DELETE 旧；合并按位或；scrub 全项目 slot；SSOT+链接；F。

**完成准则**：无 bare；enable 不丢；slot 无悬空；parent-link 通过。  
硬护栏：不用 `clear_skills` 当常规迁移；不整表 park。

---

## 参考（按需）

- [doctor.py](doctor.py) — doctor 可执行实现  
- [doctor.md](doctor.md) — 检查项与报告格式  
- [db-schema.md](db-schema.md) — 表、hash、park INSERT、resnap  
- [lock-file.md](lock-file.md) · [file-layout.md](file-layout.md)  
- 云端（可选）：`farion1231/cc-switch`
