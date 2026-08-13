# doctor — 对照官方 skill 设计的只读体检

**doctor** = 只读；输出 finding + `next:`；**不**自动修。用户点名「修」再走 mutate 动词（migrate / dispatch / slot / register…）。

**实现 SSOT**：包根 [`doctor.py`](doctor.py)（stdlib only）。hash 算法见 [`content_hash.py`](content_hash.py)。

```bash
SKILL_DIR=…/cc-switch-adapter   # 本 skill 目录
python3 "$SKILL_DIR/doctor.py"                  # 真机 home
python3 "$SKILL_DIR/doctor.py" --root /path/to/fake-home
python3 "$SKILL_DIR/doctor.py" --full           # 全量重算 content_hash
python3 "$SKILL_DIR/doctor.py" --remote         # 云端新鲜度检查（R1-R4）
python3 "$SKILL_DIR/doctor.py" --remote --fresh # 忽略缓存重新拉取
```

`--remote` 是**报告专用 seam**：只读 GitHub contents API，结果全部 `category=remote`，**不产生 FATAL / design-ERROR**，不改变 exit code 与 `next:` 语义；网络不可用时单条 WARN 降级，不阻塞离线报告。缓存写入 `<home>/.cc-switch/remote-cache.json`（repo 元数据 24h / 目录 24h / 文件内容 6h；`--fresh` 跳过）。传输层优先 `gh api`（已认证，5000 req/h），无 gh 时 urllib 直连兜底。

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
| **policy** | D10、D15（仅 bound） |
| **remote** | R1-R4（仅 `--remote`；报告专用，无 next 动词） |

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
| `D13.slot-dangling` | WARN | slot id 不在 skills；快照可独立陈旧 | slot |
| `D14.slot-id` | ERROR | slot 内非法 id | slot |
| `D15.fat-snapshot` | WARN | **仅 bound** profile 的 slot≠live → resnap candidate（**not enable**）。未绑定 profile 与 live 不同是多项目常态，**不报** | slot |
| `D16.binding` | — | 不进 findings；写入 baseline `bind=` | — |
| `R1.repo` | ERROR/WARN/OK | 源仓库 404（删除/私有化）→ ERROR；已归档（停止维护）→ WARN | — |
| `R2.path` | WARN/ERROR | DB 路径 404 → 探测 5 个候选根（`''`/`skills`/`.claude/skills`/…）找新位置 → WARN 漂移；探测到相近名 → WARN 疑似替代（改名）；全无 → ERROR 源 skill 已移除 | — |
| `R3.stale` | WARN/OK | 本地 `SKILL.md` 与上游默认分支内容不一致 → WARN（附双方 hash 前缀） | — |
| `R4.upstream` | INFO | 上游未安装的 skill 清单（≤12 个；过滤 README/脚手架目录） | — |

## 报告格式（seam）

```
doctor <iso-time>
baseline: user_version=N  ssot=<path>  sync=<method>  skills=N  loc=<loc>  bind=claude='…'  remote=on|off
FATAL n  ERROR n  WARN n  INFO n  OK n
remote: checked=n ok=n warn=n err=n        # 仅 --remote
categories: design_ERROR=n hygiene_notes=n (FATAL always design-critical)

[FATAL:design] D3.parent-link  app=claude  path=... → migrate
[ERROR:design] D4.canonical-id  id='tdd' → migrate
[WARN:remote]  R2.path  id=owner/repo:skills/x 路径漂移 → 上游新位置 skills/y (DB 需更新)
...
next: <verbs | clean[; hygiene present]>
```

- **exit**：仅 **FATAL → 1**；其余 0（R 系列 ERROR 不入 `next:`、不改 exit）。  
- **`next: clean`**：无 FATAL **且** 无 design-ERROR（hygiene/policy/remote 可并存）。  
- **`next:` 词表**：动词 `migrate` / `dispatch` / `slot` / `register` / `migrate|register`（非字母分支）。

## 完成准则（跑 doctor）

- 执行 `doctor.py`（可加 `--root` / `--full` / `--remote`）  
- 报告含头、counts、`[LEVEL:category]` findings、`next:`  
- **零**写 DB/锁/SSOT；`--remote` 仅写 `<home>/.cc-switch/remote-cache.json`（便利缓存，失败不报错）  
- fat 只报告，处置指向 SKILL fat 正向规则  
- 本机 profile 显示名只出现在当次报告  
- R 系列结论（漂移/过时/替代）仅供参考：**不**自动改 DB 路径、不自动重装；处置走注册/安装流程  

## 测试

```bash
python3 -m unittest tests.test_doctor_report -v
python3 -m unittest tests.test_doctor_remote -v   # R 系列（本地 mock GitHub）
```

fixture 假 home：`fixtures/{clean,parent_link,illegal_id,fat_profiles}/`；重建见 `fixtures/lib/build_all.py`。R 系列测试在 `TMPDIR` 下动态构建 home，并用 `--remote-base-url` 指向测试内 mock server，不触外网。

## 可选：云端 schema 对照（不阻塞）

```bash
curl -fsSL https://raw.githubusercontent.com/farion1231/cc-switch/main/src-tauri/src/database/mod.rs \
  | grep -E 'SCHEMA_VERSION' | head -3
```
