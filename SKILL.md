---
name: cc-switch-adapter
description: >
  closed-pipe：经 cc-switch 登记/迁移 skill——install-enable 或 park、
  canonical-id、project-slot（live≠slot）、register/dispatch、parent-link。
  Use when the user installs or migrates skills via agent, or mentions
  cc-switch skill 管理、Profiles、fat snapshot、bare id、parent-link。
---

# cc-switch-adapter

**closed-pipe**：SSOT → DB（**canonical-id** + **park** 或 **install-enable**）→ 锁 → 仅 enable 后 **child-link**。

**权威源（runtime-first）**：① 本机 settings/DB/磁盘/锁 → ② 可选 `farion1231/cc-switch` → ③ 本 skill。以 ① 为准。

## 官方产品 vs adapter-policy

| | **官方桌面应用** | **本 adapter** |
|--|------------------|----------------|
| 新装默认 | **install-enable** 当前 app | 未点名 app → **park** |
| 点名 app | UI / 安装进该 app | **install-enable**（≈ `only(app)`） |
| 现在开了什么 | **live** | **live** |
| 卸载 | 不 scrub 项目 slot | 默认可 scrub slot（adapter-policy） |
| 体检 | — | **doctor**（`doctor.py`） |
| 改 live | UI / apply | **dispatch** 或明确 apply |

**park** ≠ 官方安装默认。**install-enable** = 开该列 + 投影。

## 0. 解析 SSOT + parent-link 预检

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
```

可变操作前：已存在的 app `skills` 若为 symlink → **FATAL**，先 **migrate**。  
**完成准则**：`$SSOT` 正确；app skills 根为真目录。

## 协议（短）

| 词 | 含义 |
|----|------|
| **park** | 全 `enabled_*=0`，零投影（adapter-policy） |
| **install-enable** | 点名 app：enable + child-link |
| **live** | enable + 投影 |
| **project-slot** | profile JSON 目标/快照集；详见 [project-slot.md](project-slot.md) |
| **fat snapshot** | 下方唯一规则 |
| **canonical-id** | `owner/repo:<path>` \| `local:<name>` |
| **child-link** | [file-layout.md](file-layout.md)；禁盲删非投影目录 |
| **doctor** | [doctor.py](doctor.py) 只读 |
| **register / dispatch** | [pipe.py](pipe.py) 可变实现 |

### fat snapshot（唯一正向规则）

```
set(slot) − set(live) 非空
  → 报告 + 可选 slot resnap/scrub（只 JSON）
  → live 只经 dispatch，或用户明确 apply 且已确认/已 resnap
```

---

## 动词路由（主）

| 意图 | 动词 | 实现 |
|------|------|------|
| 体检 | **doctor** | `python3 "$SKILL_DIR/doctor.py"` → 报告 → **stop** |
| 查→治闭环 | **remedy** | `python3 "$SKILL_DIR/remedy.py" [--apply]`（按 findings 分发：D9/D10/D13 自动修，其余给命令） |
| 新装 / orphan 入库 | **register** | `pipe.py register`（默认 park；`--app` → install-enable） |
| 开/关 app | **dispatch** | `pipe.py dispatch --enable\|--disable` |
| slot 治理 | **slot** | `pipe.py slot list\|scrub\|resnap\|add\|remove`（dry-run 默认，`--apply` 写） |
| 卸载 / 孤儿清理 | **uninstall** | `pipe.py uninstall --id X [--keep-ssot] [--apply]` |
| parent-link / bare id / hash | **migrate** | 见下；hash = [content_hash.py](content_hash.py) |

`SKILL_DIR` = 本 skill 安装目录（已知路径；勿依赖 `$0`）。  
可选：`--root <fake-home>`（doctor / pipe / remedy 均支持）。

字母 A–M 仅历史锚，**不要**当主路由。

### doctor

```bash
python3 "$SKILL_DIR/doctor.py"          # 可选 --root / --full
```

读 [doctor.md](doctor.md) 仅当需要检查目录。  
**完成准则**：完整报告 + `next:`；仅 FATAL→exit≠0；零写入；fat 只指向正向规则。  
出现 `Skill 不存在 / toggle failed` 类警告 → 先 [experience.md](experience.md) 四查，再 `remedy`。

### remedy

```bash
python3 "$SKILL_DIR/remedy.py"          # dry-run：打印 AUTO/CMD/SKIP 计划
python3 "$SKILL_DIR/remedy.py" --apply  # 执行 auto（D9→enable、D10→disable、D13→scrub）
```

**完成准则**：auto 项 FIXED；D6/D7 等决策项只给命令不代执行；尾部 doctor recheck 对比前后。

### register（新装 ∪ orphan）

统一路径（**pipe** 为可变 SSOT；亦可逐步手写等价步骤，结果须满足完成准则）：

```bash
# park（默认）
python3 "$SKILL_DIR/pipe.py" register \
  --id 'local:my-skill' --directory my-skill \
  --source /path/to/content --name 'My Skill'

# install-enable 点名 app
python3 "$SKILL_DIR/pipe.py" register \
  --id 'owner/repo:my-skill' --directory my-skill \
  --source /path/to/content --app claude \
  --repo-owner owner --repo-name repo
```

步骤语义：① 内容进 SSOT（含 `SKILL.md`）② canonical 行；未点名 → park ③ GitHub → 锁 ④ 点名 app → dispatch enable ⑤ hash via content_hash。  
**不**因「当前项目」写 project-slot。

**完成准则**：SSOT + 行存在；park ⇒ 全 enable 0 且无投影；named ⇒ 该 app live↔磁盘；profiles 未静默改。

### dispatch

```bash
python3 "$SKILL_DIR/pipe.py" dispatch --id 'local:my-skill' --app claude --enable
python3 "$SKILL_DIR/pipe.py" dispatch --id 'local:my-skill' --app claude --disable
```

顺序对齐官方 `toggle_app`：**投影先于**（或与）DB enable 成对；disable **保留 SSOT**；**不**改 profiles。  
symlink | copy 跟 `skillSyncMethod`（[file-layout.md](file-layout.md)）。

**完成准则**：`enabled_*` ↔ 磁盘；disable 后 SSOT 仍在；无 profile 写入。

### slot

用户点名项目时：`pipe.py slot list|scrub|resnap|add|remove`（默认 dry-run，`--apply` 才写 profiles JSON；**永不碰 live**）。  
apply 前若 fat → 先确认或 resnap。全文 [project-slot.md](project-slot.md)。

```bash
python3 "$SKILL_DIR/pipe.py" slot list --profile '求职'           # 看引用，# dangling 标记
python3 "$SKILL_DIR/pipe.py" slot scrub --profile '求职' --apply  # 去 DB 无行的引用
python3 "$SKILL_DIR/pipe.py" slot resnap --profile '求职' --app claude --apply
python3 "$SKILL_DIR/pipe.py" slot add|remove --profile X --app claude --id 'local:x' --apply
```

**完成准则**：resnap 后 `set(slot)==set(live)`；scrub 后无 dangling；live 未动。

### uninstall（卸载 ∪ 孤儿清理）

```bash
python3 "$SKILL_DIR/pipe.py" uninstall --id 'local:x' [--keep-ssot] [--apply]
```

计划 = 删投影 → 删锁键 → 删 SSOT（`--keep-ssot` 保留）→ 删行 → **scrub 全 profile slot 引用**。  
SSOT 目录已缺失（孤儿残留）→ 自动走残留清理路径，只清行/断链投影/slot 引用。  
**硬护栏**：SSOT 删除必须走本命令，禁止手删 SSOT 目录（见 [experience.md](experience.md) 复盘）。

**完成准则**：行不在；无投影/断链；无 slot 引用；SSOT 不在或保留；锁键不在。

### migrate

| 子场景 | 做法 |
|--------|------|
| parent-link | `rm` 父链 → `mkdir` → 对 enable=1 建 child-link |
| bare id | 新 canonical INSERT（拷 enable）→ DELETE 旧；scrub slot；[db-schema.md](db-schema.md) |
| hash / 误报 | `python3 "$SKILL_DIR/content_hash.py" "$SSOT/<dir>"` → `UPDATE content_hash` |

**完成准则**：无 bare/parent-link；enable 不丢；hash=现场。  
硬护栏：不用 `clear_skills` 当常规迁移；不整表 park。

---

## 参考

- [pipe.py](pipe.py) · [doctor.py](doctor.py) · [remedy.py](remedy.py) · [content_hash.py](content_hash.py)  
- [experience.md](experience.md) · [project-slot.md](project-slot.md) · [db-schema.md](db-schema.md)  
- [doctor.md](doctor.md) · [file-layout.md](file-layout.md) · [lock-file.md](lock-file.md)  
