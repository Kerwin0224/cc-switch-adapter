# profiles — 场景设计参考（按需加载）

**场景 = profile**：一个 profile 是用户的一个工作场景。设计 profile 时先盘点
（`inventory.py`），再按本页规则判「该开 / 不该开」。

## 决策规则（优先级从高到低）

1. **三件套**：claude / codex / opencode 默认同开同关；非三件套 app 默认关。
2. **场景边界**：只装该场景要用的 skill——多了是噪音（context load），少了是
   缺功能。判断依据：读每个 skill 的 `SKILL.md` description，按场景词聚类。
3. **通用核心**：cc-switch-adapter（自管理）、writing-for-agents（写 skill /
   AGENTS 文档）随每个场景。
4. **跨场景依赖**：一个 skill 被多个场景用时，归入它服务的主场景；重复出现
   是常态，不是错误。

## 当前场景（2026-08 快照，以本机 profiles 表为准）

| 场景 | 技能簇 |
|------|--------|
| 开发 | engineering 全家桶（tdd / to-spec / code-review / diagnosing-bugs…）、gitnexus、context7、frontend-design、deploy-to-vercel |
| 运维 | 同开发 + find-skills / web-design-guidelines 等 |
| 求职 | qingdao-ai-resume、job-scout、EDUQA-from-pdfs、lark 办公簇、browser-act、smart-search |
| 办公 | lark 全家桶（base / doc / drive / sheets / slides / wiki…） |
| 视频 | hyperframes 全家桶、remotion、guizang-ppt、faceless-explainer、media-use |
| GSW | benchmark / QA 簇（benchmark-qa-manual-cleaning、deepxiv、qa-from-pdfs）、omc-reference |

## 设计产物

对每个目标场景交付三张表：

1. **现状**：`inventory.py` 全表——谁开了、谁没开，逐 app。
2. **应该**：按上述规则判出的目标集合 + 每条依据。
3. **差分 → 动词**：每项差异落一个 closed-pipe 动词（dispatch / slot /
   register / migrate）；未确认的保持原状。

产出示例（开发场景，2026-08 现状）：

- 槽位只覆盖 claude / codex；opencode 对齐三件套走 `dispatch`，不写进数组。
- `--profile 开发` 的 `[slot-only]` 项（如 lark 簇）是「快照有、live 无」——
  若该场景用不到，`slot remove`；若要用，用户确认后 `dispatch --enable` 三件套。
