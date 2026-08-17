# MCP Governance -- Harness Compatibility

Use this reference whenever cc-switch manages an MCP across more than one app,
when one client fails while another works, or when a new agent harness is being
onboarded.

## Contents

- [MCP per-app policy](#mcp-per-app-policy)
- [Two-layer contract](#two-layer-contract)
- [Naming contract](#naming-contract)
- [Compatibility Ledger](#compatibility-ledger)
- [Decide the branch](#decide-the-branch)
- [Codex overlay](#codex-overlay)
- [Recovery when a broad change drifted](#recovery-when-a-broad-change-drifted)
- [New harness onboarding](#new-harness-onboarding)
- [Verification matrix](#verification-matrix)
- [Incident signatures](#incident-signatures)

## MCP 开关总律（MCP per-app enable policy）

cc-switch 的 MCP 行表达逐 app 路由意图。它不建立“所有 harness 同开”或
“只有两个 harness 可开”的默认值。每个非 Codex 列都从可信快照和该 harness 的
运行证据继承；新 MCP 在获得该端的真实工具调用证据前保持 park。

| app | cc-switch 管理？ | 说明 |
| --- | --- | --- |
| **claude** | ✅ | cc-switch 投影 + `enabled_claude`；只保留经验证或用户确认的行。 |
| **opencode** | ✅ | cc-switch 投影 + `enabled_opencode`；逐行验证。 |
| **hermes** | ✅，逐行 | 已有工作行按快照保留；新增或变更走 onboarding。 |
| gemini / grokbuild | ✅，逐行 | 只在本机有该列且该 harness 通过真实工具调用后启用。 |
| **codex** | ❌ **当前本机策略** | Codex 的 MCP 由自身 `~/.codex/config.toml` native 管理；cc-switch 的 `enabled_codex` 保持 0。 |

**执行规则**：先快照全部 `enabled_*`，再只修改用户点名的列。Codex 列保持 0；
其他 app 列维持其快照值，除非用户明确要求并完成该 app 的 onboarding。现有的
正常端不能因 Codex 的问题被整体关闭。

**理由**：Codex 在本机走 native transport / credential / process-environment
所有权契约，属 **Overlay** 分支。这是当前治理边界，不是“Codex 永远不能使用
cc-switch MCP”的协议能力结论；只有新的实测证据和用户确认才能改变该边界。

skill 管理不适用本律：skill 仍走「三件套」（claude / codex / opencode 同开同关）。
本节是 MCP 侧的唯一真值，`SKILL.md` 只保留指针，不重复表述。

## Two-layer contract

Treat an MCP as two contracts that must both hold:

1. **cc-switch routing**: the canonical `mcp_servers` row and its
   `enabled_<app>` columns express which clients should receive that server.
2. **Harness runtime**: each client resolves its own transport syntax,
   authentication, credential source, process environment, and restart model.

cc-switch standardizes intent. It does not prove that every harness accepts the
same serialized configuration or inherits credentials in the same way. A row
is live for a client only after both contracts are observed working.

## Naming contract

Every MCP row carries two names with different jobs. Preserve both; neither is
a place to encode transient state.

| Field | Contract | Format |
| --- | --- | --- |
| `id` | Stable canonical identity for the CC Switch row, mappings, recovery, and any client surface that exposes the identifier. | Unique, source-aligned, and directly recognizable. New IDs use lowercase kebab-case unless a recognized upstream canonical ID already exists. Existing valid IDs retain their established spelling for compatibility. |
| `name` | Unique user-facing title in the CC Switch list. | Official product casing with spaces between words: `Exa`, `GitNexus`, `OpenAI Developer Docs`, `Tavily Hikari`, `Chrome DevTools`. Add a concise descriptor only when two servers would otherwise display the same title, such as `Supabase Remote`. |

The **clean-name rule** applies to both fields:

- State belongs in the per-app `enabled_*` columns. Names never carry
  `disabled-`, `[disabled]`, `MCP:`, transport names, credential hints, or
  recovery timestamps.
- A recovery restores the canonical `id` from its trusted snapshot before
  deciding whether the display `name` needs a presentation-only correction.
- A display-name correction changes `name` only. It must preserve the stable
  `id`, `server_config`, and every enable column.
- A canonical-ID migration is an identity change, not a cosmetic rename. Map
  every dependent reference first, take a backup, and verify the old ID no
  longer appears after the transaction.

Before registering or changing a row, check that both values are unique and
that the title is meaningful without reading its configuration. Completion
criterion: a CC Switch list can show either field without exposing internal
state or making the user infer which MCP it represents.

## Compatibility Ledger

Keep compatibility evidence narrow. "Works for Claude Code" is evidence for a
named MCP, client version, and test only; it is not evidence that the same
mapping works for every MCP or every release.

### Current local evidence, 2026-08-18

| Harness | Confirmed cc-switch state | Confidence and boundary |
| --- | --- | --- |
| Claude Code | `exa`, `gitnexus`, and `tavily-hikari` were restored to their pre-incident enabled state. | Validated as preserved routing for these rows; each server still owns its own auth. |
| OpenCode | The same three rows were restored enabled. | Validated as preserved routing for these rows. |
| Hermes | `exa` and `tavily-hikari` were restored enabled; `gitnexus` remained off because it was off before the incident. | Baseline preservation, not a blanket compatibility claim. |
| Codex | Those CC Switch columns remain off. Codex uses its native `~/.codex/config.toml` overlay for the required servers. | Intentional exception: native transport and credential handling are authoritative. |
| Gemini, Grokbuild | No affected MCP row was enabled in the recovered baseline. | No compatibility conclusion. Test before enabling. |

The exact columns are runtime facts. Before acting, read `.schema mcp_servers`
and snapshot the affected rows; do not treat this table as a replacement for
that check.

## Decide the branch

Classify each `(MCP, harness)` pair before changing it.

| Branch | Observable condition | Governing action |
| --- | --- | --- |
| **Mapped** | cc-switch applies a valid native config and the harness initializes the server. | Change only that harness column, then verify the live tool path. |
| **Overlay** | The harness accepts the server but needs newer transport fields, separate auth, or a distinct process environment. | Keep cc-switch as routing policy for other apps; use the harness's native config for this one client. |
| **Unproven** | The harness is new, its mapping is absent, or initialization has not been observed. | Park only this harness column and run the onboarding procedure. |

The leading rule is **column-local**: a Codex problem authorizes a Codex-column
change, not a change to Claude Code, OpenCode, or another app's known-good
columns.

## Codex overlay

**Codex 是当前本机的 Overlay ownership policy**：Codex 的 MCP 由自身
`~/.codex/config.toml` native 管理，cc-switch 不为其投影、`enabled_codex` 保持 0。
下面仅列 native 配置的执行细节。任何改变此所有权边界的提案都要先取得新的
兼容性证据和用户确认。

Codex 需要 native 配置的典型场景：HTTP MCP 要求 `bearer_token_env_var`、OAuth、
per-tool policy，或 cc-switch 无法正确投影的环境源。

1. Preserve the other apps' `enabled_*` values exactly as recorded in the
   pre-change snapshot.
2. Set only `enabled_codex` off in the CC Switch row when native Codex config
   owns this server.
3. Configure the server natively in `~/.codex/config.toml`; use its supported
   transport fields rather than forcing an older CC Switch projection.
4. Store a secret in an owner-only environment file, never in the Codex config,
   command history, reports, or backup text.
5. Make that environment available to the process that launches Codex. A shell
   profile covers login shells only; desktop and IDE clients launched by macOS
   require their launchd environment to receive the value before they start.
6. Restart the affected Codex client and verify a fresh process initializes the
   server. For the CLI, include strict-config validation and an actual MCP tool
   call where the server provides a safe read operation.

Completion criterion: the Codex MCP starts without a missing-variable or
transport-schema error, while every untouched app column still equals its
snapshot value.

## Recovery when a broad change drifted

Use a snapshot-to-row recovery rather than changing every row to one global
state.

1. Read the pre-change database backup and current `mcp_servers` schema.
2. Restore the trusted `(canonical id, display name, enabled_*)` mapping from
   that snapshot. A cosmetic `name` is not the sole identity key: when names
   changed after the snapshot, compare the recorded server configuration and
   require an unambiguous match before changing an ID.
3. Restore every `enabled_*` column from the snapshot for each affected row.
4. Apply the explicit exception afterward, such as `enabled_codex = false` for
   a Codex overlay.
5. Restart CC Switch, re-read the rows, and compare all columns to the expected
   matrix.

Completion criterion: no temporary renamed rows remain, every restored column
matches the snapshot or an explicit exception, and the target harness passes
its own runtime check.

## New harness onboarding

For a newly added agent harness, work in this order:

1. Read the harness's current MCP documentation and inspect its live config
   source, schema, startup parent, and credential model.
2. Add or identify one MCP row with all existing app columns unchanged and the
   new harness parked.
3. Test one read-only server through the harness's native configuration. Record
   the transport, auth mechanism, environment inheritance, restart requirement,
   and exact evidence of initialization and tool use.
4. Classify the pair as Mapped, Overlay, or Unproven. Add a cc-switch mapping
   only after the Mapped branch passes.
5. If the result is Overlay, document the native config owner and keep
   cc-switch's control limited to the per-app routing decision.
6. Update the Compatibility Ledger with date, harness version, server name,
   test, and boundary. A later version change requires a new observation.

Completion criterion: every existing harness retains its snapshot state, the
new harness has an explicit branch, and one real MCP tool call demonstrates the
chosen path.

## Verification matrix

For each affected row, capture this matrix before reporting completion:

| Check | Evidence required |
| --- | --- |
| Routing | DB row shows the expected value for every `enabled_*` column. |
| Projection | The target harness's native config has the expected server entry, or the record explicitly says native config owns it. |
| Credentials | The process sees the required variable without printing its value; config and secret file permissions are owner-only. |
| Startup | A freshly started harness initializes the MCP without schema, auth, or missing-environment errors. |
| Tool path | A safe read-only tool returns a real result through the target harness. |
| Isolation | Re-reading all other app columns proves they stayed at the snapshot values. |

## Incident signatures

| Symptom | Most likely branch | First decisive check |
| --- | --- | --- |
| One harness reports a missing environment variable while other apps work. | Overlay | Compare the launching process environment with the private credential source. |
| Codex rejects a field CC Switch generated. | Overlay | Run `codex ... --strict-config`; compare the harness's supported schema with the projection. |
| A recovery left `[disabled]` names or regenerated IDs. | Recovery drift | Compare canonical names and every app column against the pre-change backup. |
| A new harness has a visible CC Switch column but no working server. | Unproven | Run native one-server initialization before enabling the column. |
| **Enabled in DB but absent from the harness tool list, with no error.** | **产物无效** | Read the harness's **native** config file (not the DB) and diff the entry against a working peer. See [[意图层/产物层|experience.md → 通用排查哲学：意图层/产物层]]. |

Never treat a configuration listing, an HTTP probe, or a successful different
harness as proof of a client-specific MCP integration. The completion evidence
is a fresh client startup plus a real, safe tool call.
