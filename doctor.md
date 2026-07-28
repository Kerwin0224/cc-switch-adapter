# doctor — 对照官方 skill 设计的只读体检

**doctor** = 只读；输出 finding + `next:`；**不**自动修。用户点名「修」再走 mutate 动词（migrate / dispatch / slot / register…）。

**实现 SSOT**：包根 [`doctor.py`](doctor.py)（stdlib only）。hash 算法见 [`content_hash.py`](content_hash.py)。

```bash
SKILL_DIR=…/cc-switch-adapter   # 本 skill 目录
python3 "$SKILL_DIR/doctor.py"                  # 真机 home
python3 "$SKILL_DIR/doctor.py" --root /path/to/fake-home
python3 "$SKILL_DIR/doctor.py" --full           # 全量重算 content_hash
```

**对照基线（runtime-first）**：本机 `.schema` + `settings.json` + 磁盘；`user_version` 以本机为准——**不**因 `≠ 16` 单独 ERROR/WARN。

## 不变量

| 不变量 | 含义 |
|--------|------|
| **unified-row** | `skills` 一行 + 多列 `enabled_*` |
| **canonical-id** | `owner/repo:<path>` \| `local:<name>`；禁 bare / `:.` |
| **SSOT** | `skillStorageLocation` → 内容根；app 仅投影 |
| **child-link** | enable 后子项链/拷；**禁** app `skills` 父目录整链 SSOT |
| **live ≠ slot** | enable+投影 = live；profile JSON = 可脏快照 |
| **park** | adapter-policy：全 `enabled_*=0`（非官方 **install-enable**） |
| **fat snapshot** | 见 SKILL 唯一正向规则；本检查只报告，不 enable |

## 严重度与 category

| 级 | 含义 |
|----|------|
| **FATAL** | 设计被破坏（exit **1**） |
| **ERROR** | 偏离设计 / closed-pipe 断（design-ERROR → 非 clean；exit 仍 0） |
| **WARN** / **INFO** | 卫生或 policy |
| **OK** | 通过（仅计入 counts） |

每条 finding：**`[LEVEL:category] CODE  msg`**，`category` ∈ `design|hygiene|policy`。

| category | 典型 CODE |
|----------|-----------|
| **design** | D0（缺 runtime）、D1 非 unified、D3、D4、D6、D9、D11、D13、D14 |
| **hygiene** | D2、D5、D7、D8、D12 |
| **policy** | D10、D15、D16 |

## 检查目录（id 稳定）

| id | 级 | 检查 | 失败 → verb |
|----|----|------|-------------|
| `D0.runtime` | FATAL | settings/db/skills 表 | migrate |
| `D1.schema` | ERROR | unified-row（`id` + `enabled_*`） | migrate |
| `D2.settings` | WARN/OK | SSOT 路径、sync 方法 | — |
| `D3.parent-link` | **FATAL** | app skills 根为 symlink | migrate |
| `D4.canonical-id` | ERROR | bare / `:.` / `..` | migrate |
| `D4.directory` | ERROR | directory 非单段短名 | migrate |
| `D5.unified-meta` | WARN | GitHub 行缺 owner/name | migrate |
| `D6.ssot-db` | ERROR | DB 有、SSOT 无或无 SKILL.md | migrate\|register |
| `D7.db-ssot-orphan` | WARN | SSOT 有 SKILL、DB 无 | register |
| `D8.hash` | WARN | hash 空；`--full` 时 drift | migrate |
| `D9.live-link` | ERROR | enable=1 但投影缺失/断/错（含 parent_missing） | dispatch |
| `D10.park-leak` | WARN | enable=0 仍有**指向 SSOT** 的投影 | dispatch |
| `D11.dup-directory` | ERROR | 多行同一 directory | migrate |
| `D12.lock` | **INFO**/hygiene | GitHub 行缺锁键等 | — |
| `D13.slot-dangling` | ERROR | slot id 不在 skills | slot |
| `D14.slot-id` | ERROR | slot 内非法 id | slot |
| `D15.fat-snapshot` | WARN/INFO | **bound** fat → WARN resnap candidate；**unbound** → INFO；处置见 SKILL fat 正向规则 | slot |
| `D16.binding` | INFO | `current_profile_id_*`（binding≠applied） | — |

## 报告格式（seam）

```
doctor <iso-time>
baseline: user_version=N  ssot=<path>  sync=<method>  skills=N  loc=<loc>
FATAL n  ERROR n  WARN n  INFO n  OK n
categories: design_ERROR=n hygiene_notes=n (FATAL always design-critical)

[FATAL:design] D3.parent-link  app=claude  path=... → migrate
[ERROR:design] D4.canonical-id  id='tdd' → migrate
...
next: <verbs | clean[; hygiene present]>
```

- **exit**：仅 **FATAL → 1**；其余 0。  
- **`next: clean`**：无 FATAL **且** 无 design-ERROR（hygiene/policy 可并存）。  
- **`next:` 词表**：动词 `migrate` / `dispatch` / `slot` / `register` / `migrate|register`（非字母分支）。

## 完成准则（跑 doctor）

- 执行 `doctor.py`（可加 `--root` / `--full`）  
- 报告含头、counts、`[LEVEL:category]` findings、`next:`  
- **零**写 DB/磁盘/锁  
- fat 只报告，处置指向 SKILL fat 正向规则  
- 本机 profile 显示名只出现在当次报告  

## 测试

```bash
python3 -m unittest tests.test_doctor_report -v
```

fixture 假 home：`fixtures/{clean,parent_link,illegal_id,fat_profiles}/`；重建见 `fixtures/lib/build_all.py`。

## 可选：云端 schema 对照（不阻塞）

```bash
curl -fsSL https://raw.githubusercontent.com/farion1231/cc-switch/main/src-tauri/src/database/mod.rs \
  | grep -E 'SCHEMA_VERSION' | head -3
```
