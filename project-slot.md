# project-slot（按需加载）

**live** = `skills.enabled_*` + 投影（「现在开了什么」的唯一真相）。  
**project-slot** = `profiles.payload.skills.<app>` 的 id 数组（某次拍照 / 离开 auto-save / 手改的副本，可脏）。

| | **live** | **project-slot** |
|--|----------|------------------|
| 存哪 | DB enable + app 目录 | `profiles` JSON |
| 谁改 | UI、**dispatch**、apply | auto-save、resnap、**slot** |
| 读法 | 「现在启用了 X」只看 live | slot 有 X **不能**推出「现在启用了 X」 |

## 产品切换项目时

1. **auto-save**：离开项 live → 该项目 slot  
2. **apply**：按目标 slot 对 live 做最小 diff  
3. `current_profile_id_*` 只是绑定名，可与 live 长期不一致  

`null` = 未快照（apply 不动）；`[]` = 空集；`[id,…]` = 目标集。  
id 用 **canonical-id**，不是 directory。  
scope 仅 claude / claude-desktop / codex；其它 app 只用 **dispatch**。

## fat snapshot

见 SKILL 顶部**唯一正向规则**。摘要：

```
set(slot) − set(live) 非空
  → 报告 fat snapshot
  → 可选 resnap / scrub（只改 profiles JSON）
  → live 只经 dispatch，或用户明确 apply 且已确认/已 resnap
```

- slot 有、live 无 → fat → resnap/scrub 或报告；**不**自动 enable  
- live 有、slot 无 → live 更新；非用户要求不强制关  
- 用户说「这项目没启用 X」→ 信用户 + live；X 在 slot → 脏 slot  

## 子操作（仅用户点名项目时）

1. **resnap**：`slot.<app> = SELECT id … WHERE enabled_*=1`——只改 JSON  
2. **scrub**：去掉表中不存在的 id；bare→canonical（常随 **migrate**）  
3. **add/remove id**：改数组；默认不 apply  
4. **apply**：用户明确「按某项目套到 live」——会改 enable；slot 仍胖会打开差集 → 先确认或先 resnap  

SQL 示例：[db-schema.md](db-schema.md)。

## 完成准则

- resnap 后该 app `set(slot)==set(live)`  
- 解释/清洗场景不擅自改 live  
- 项目名来自用户或本机 `SELECT name FROM profiles`；正文不写机器专名  
