# 深度研究：先建立 Agent 运行授权与执行绑定，再接 provider loop

日期：2026-07-18
状态：下一 Agent-first 纵向切片的决策输入，不代表已启用运行提交

## 执行摘要

H2OMeta 下一步应优先打通 deterministic FASTQ QC 的 `ready_to_run -> WorkflowRun`，但不能让现有编译审批、浏览器构造的
`runSpec` 或通用 `POST /api/v1/runs` 直接承担 Agent 运行授权。正确的最小切片是：新增一次性的、不可变的
`AgentRunAuthorization` / execution binding，并配套独立 effect budget、server-owned exact preview 与
worker 执行前输入物化。授权事实和既有 WorkflowRun 在 remote runner 的同一个短 SQLite 事务
里原子创建，响应丢失后的重试返回同一个 authorization 和 `runId`。

排序应为：

1. **运行授权与 execution binding**：补齐 Agent 控制面到既有执行内核之间的安全效应边界；
2. **FASTQ QC typed replan**：复用已经存在的 generation、parent lineage、plan hash 和预算框架；
3. **provider-neutral invocation/reservation/usage facts**：先用 deterministic fixture/record-replay 证明；
4. **单 provider、顺序式、只读 planning loop**；
5. 最后才评估多 Agent、开放网络、沙箱化代码执行和副作用工具。

这不是退回 DAG-first。DAG 继续作为 WorkflowRevision 中确定性的编译、验证、执行和 lineage 表示；用户主
交互继续是 goal、typed plan、approval、observation、run authorization 和 results。运行授权是所有自主
Agent 都必须经过的 effect boundary，不是新的画布或流程编排器。

## 研究问题

在当前 H2OMeta 已有 durable AgentSession、不可变 PlanRevision、编译审批、WorkflowRevision、RunLedger 和
snapshot observation 的前提下，下一刀应选：

- A：独立运行授权与 Agent-to-Run execution binding；
- B：FASTQ QC typed replan；
- C：provider-neutral 多轮 Agent loop 与 usage accounting。

判断标准是端到端产品价值、可复用基础、授权与恢复安全、事实可审计性、实现可证明性，以及是否会绕过现有
capability/revision/run gate。

## 研究方法

仓库基线为 `codex/remove-first-run-wizard` @
`0af5f5cc445acf09c01ba1ecb0864506a4519f75`。三个只读审计分别检查：

- `ready_to_run` 到 WorkflowRun 的授权、提交、取消、retry、resume 与事务边界；
- typed replan 与 provider loop 的现有合同、预算和 durable fact 缺口；
- OpenAI、Temporal、LangGraph、MCP、Microsoft、A2A、Anthropic、Biomni、OpenTelemetry 与 OWASP 的一手实践。

Firecrawl 通过仓库 wrapper 以“不设时限”的 exhaustive 层运行。决策集合包含 16 个结构化搜索、94 个结果、
93 个唯一 URL，并直接抓取关键官方页面。综合时排除了社区问答、Medium 和聚合文章，只采用官方规范、官方
文档、项目仓库与 Biomni 原论文。临时 `.firecrawl/next-agent-slice/` 只是忽略的研究缓存，ADR 落盘后删除。

## 当前 H2OMeta 的真实边界

### 编译审批明确不等于运行审批

- `AgentApprovalRecord.scope` 只能是 `compile_workflow_revision`。
- Approval 创建不可变 WorkflowRevision，并把 session 推到 `ready_to_run`；它不会创建 run。
- 生命周期测试明确证明 approval 后 `list_runs == []`。
- Workbench 合同明确禁止 `ready_to_run` 自动调用 `/api/v1/runs`。

因此不能通过扩展旧 approval scope、按钮复用或隐式自动提交来“打通执行”。这会把两个风险级别不同的效应
合并，并破坏已经接受的 Agent-first ADR。

### 现有执行内核值得复用

`workflow_run_storage.py` 已在一个事务中写入：

- `runs`；
- `run_commands`；
- `run_events`；
- `run_jobs`；
- 通用 run idempotency。

现有执行层还具备 preflight、admission、attempt lease、fencing、cancel、terminal retry、基于
`snakemake --rerun-incomplete` 的证据化 resume 与 artifact lineage。新切片应提取 connection-scoped 的
run creation primitive，而不是复制一个 Agent 专用执行引擎。

### 通用 `/runs` 不能成为 Agent 授权边界

通用接口接受 caller 提供的完整 `runSpec`，缺少 Agent session、plan generation、plan hash、expected
state version、第二次明确确认和不可变 execution binding。`workflow_design_submission.py` 虽校验 draft 与
WorkflowRevision，但仍允许 caller 提供 upload binding 与 `execution`，且没有把 execution policy 与
WorkflowRevision 中的期望值做全等绑定。

Agent 路径若直接调用它，浏览器仍可能替换输入或执行策略。正确复用层级是内部 run mutation，不是公共
request contract。

### FASTQ QC 已有可重建的输入事实

FASTQ QC goal context 持久保存 `uploadId`、filename、SHA-256、size 和 MIME，并定义稳定的
`fastq_qc_manifest_digest()`。远端 planner validation 已重新读取 materialized upload ledger、重建精确
capability proposal 并要求 canonical equality。运行授权可以再次执行相同上传校验，并从 immutable
WorkflowRevision / draft / goal context 服务端重建 runSpec；浏览器无需也不得提交 graph、runSpec 或新文件。

### 运行预算必须与旧 plan hash 分离

早期 Agent-first ADR 已明确：启用运行前必须新增 fail-closed `maxRunSubmissions`，旧 session 按 0。
但当前 `AgentSessionBudget` 同时进入 `agent-plan-revision.v1` canonical payload 和 `planHash`，也嵌套在
strict snapshot v1 中。直接添加 default=0 会让旧 plan 读取立即触发
`AGENT_PLAN_CANONICAL_PAYLOAD_MISMATCH`；迁移改写旧 canonical payload/hash 又会破坏 approval 证据。

因此授权切片必须：

- 保持 `AgentSessionBudget`、PlanRevision 与 snapshot v1 原样；
- 新建独立、不可变的 `agent-session-effect-budget.v1`，row 缺失即有效上限 0；
- 新 UI 只在 session 仍为 `created` / generation 0 / 无 plan 时显式 grant 1；
- 已进入 planning 的旧 session 不得事后补 grant，需新建 session；
- 实际 usage 由不可变 binding 数量给出，不能从 limit 猜测。

Runnable session 的客户端顺序必须是
`create/recover -> persist pending grant -> grant/replay -> GET authoritative present -> plan`；grant 不确定、
absent 或 error 时不得 auto-plan。Planning-only session 才可保持现有 auto-plan。

### 历史 `runs.server_id` 不是 Agent 路由身份

现有 `runs.server_id` 是 NOT NULL，并与 caller idempotency key 组成通用 run 的幂等域；但
`RemoteRunnerConfig` 没有 local registry `serverId`，而 Agent 信任边界要求该 local alias 不进入远端
durable contract。最小安全方案是使用保留的 internal namespace `agent-control-plane.v1`，同时：

- 所有 caller-authored run/trigger 入口拒绝 `agent-control-plane.` 前缀；
- 内部 run idempotency key 从 session/authorization/command identity 做 domain-separated 派生；
- 无 Agent binding 时命中 run-idempotency 必须 fail hard，不得只比 payload hash 就 replay；
- 一个 run 是否属于 Agent 只能由不可变 binding 判定，不能从该保留 namespace 推断；
- 返回 run 中的该 `serverId` 不得被 UI 用作 local/SSH 路由。

V18 -> v19 migration 在写 schema version 前扫描既有 `runs`、`idempotency` 与 `workflow_triggers` 的
`agent-control-plane.` legacy collision；发现时以稳定 migration error 失败，绝不静默改写历史 identity。

长期更干净的模型是把 idempotency namespace 与历史 `runs.server_id` 拆分。

## 外部实践的共同结论

### 1. Approval 必须绑定具体请求，而不是授予模糊能力

OpenAI Agents SDK 把 approval 绑定到具体 tool call ID；暂停结果可转为 durable `RunState`，批准后恢复原始
顶层 run。OpenAI MCP approval request 同时暴露 request ID、工具名和 arguments，并用对应
`approval_request_id` 回应。共同含义是：批准“这个精确调用”，不是批准某个模型以后都可以执行同类动作。

对 H2OMeta 的推论：run authorization 必须绑定 exact session、plan revision/generation/hash、WorkflowRevision、
input manifest、runSpec hash 和 expected state version；compile approval 不得外溢为 submit 权限。

### 2. Durable handle 必须在异步工作开始前存在

OpenAI background Responses 先返回可轮询 response identity；实验性 MCP Tasks 要求 task 在返回
handle 前 durable 创建；A2A 用唯一 task ID 和显式 lifecycle 支持长任务；Temporal 与 LangGraph
都依赖稳定 workflow/thread identity 与 checkpoint 恢复。这些资料支持的共同原则是稳定
durable identity、可恢复与 replay-safe side effect，并不规定业务必须使用 SQLite 单事务。

对 H2OMeta 的本地设计选择：authorization 与 run 恰好位于同一 remote SQLite，因此用一个短
事务提交两者是比 outbox/事务消息更小、更易证明的实现。这是仓库条件下的工程决策，
不是对外部规范的过度引申。

### 3. Resume 可能重放，副作用必须幂等

LangGraph 明确说明 resume 时节点从头执行，interrupt 前的代码会再次运行；Temporal 把 replay 与 activity
side effect 分开；OpenAI HITL 把批准结果保存在同一 RunState。对 H2OMeta，丢失 202 响应后使用同一
idempotency key 重试必须读取同一 binding 和 run，不能再次排队。

### 4. 人类输入与显示必须类型化

MCP elicitation 使用受限 JSON Schema，区分 accept、decline、cancel，并要求清楚显示哪个 server 在请求
什么以及原因。Microsoft Agent Framework 用 typed RequestPort/response handler 把 response 路由回原始
request。运行授权 UI 因此必须展示 server-owned exact revision、输入摘要、资源/执行策略和后果，
确认值使用固定 literal。V1 不把自由文本备注写入不可变 receipt，也不宣称已实现完整
accept/decline/cancel 三态 request lifecycle。

### 5. Tool 与远端内容默认不可信

MCP Tools 将工具视为可能执行任意代码，要求校验 input、显示 tool input 并由用户确认敏感操作；OpenAI
提醒恶意 MCP server 可从模型上下文外泄数据；OWASP 把高风险动作的人类审批和最小权限列为 prompt
injection 的缓解措施。

H2OMeta 不应把 browser、LLM output、自由文本备注、MCP payload 或对话内容当作 runSpec。唯一可信执行输入来自
remote runner 的 upload、ToolRevision、WorkflowRevision 和 policy ledger。

### 6. Provider run state 和 trace 都是敏感且需要版本化的

OpenAI `RunState` 包含 context、usage、model responses、tool input、approval、nested resumption 和 trace
metadata，官方建议把它视为持久数据并与 agent/SDK version 一起存储。OpenAI tracing 与 OpenTelemetry
GenAI conventions 都可能涉及输入、输出或 tool 内容；相关语义仍在演进。

这说明 C 不是“在现有 deterministic planner 前加一次模型调用”。在 live provider 前，H2OMeta 必须先有
版本化、脱敏、provider-neutral 的 invocation、reservation、usage、retry 与 checkpoint facts。

### 7. Agent 应从最简单、可测的模式逐步增加自主性

Anthropic 建议从简单可组合模式开始，只在结果证明值得时增加复杂度；Agent 需要环境 ground truth、人工
checkpoint、停止条件和 sandbox 测试。Biomni 的价值来自检索增强规划、150 个工具、105 个软件包、59 个
数据库与代码执行环境，但其公开仓库也明确警告当前 LLM-generated code 拥有完整系统权限，生产必须隔离。

H2OMeta 应学习 Biomni 的 goal-driven、retrieval/tool selection 和 adaptive planning，不应复制其当前的全权限
代码执行信任模型。

## 三个候选的比较

| 候选 | 已有基础 | 新增风险面 | 端到端价值 | 决策 |
| --- | --- | --- | --- | --- |
| A 运行授权与 binding | WorkflowRevision、run ledger、preflight、idempotency、worker、result UI | exact preview、原子绑定、input materialization、第二审批 | 打通 goal 到真实结果 | **现在做** |
| B typed replan | generation、parent、plan hash、budget、fork draft、再审批 | typed adjustment 与 canonical rebuild | 改善纠错，但仍不能执行 | **A 后做** |
| C provider loop | 只有 deterministic planner identity 与 budget ceilings | durable turn、usage、retry、secret、sandbox、validator registry | 长期最高 | **先事实底座，暂不 live** |

typed replan 的实现成本更低，这是最强反对意见；它的 generation、parent、hash、budget 等多数
持久化骨架已存在。仍把 A 放前面的原因是：当前
Agent Workbench 的端到端断点恰好在 `ready_to_run`。B 让方案更可改，却仍不能安全地产生任何结果；A 则
建立未来 autonomous loop 也不得绕过的 effect boundary。
该 A>B>C 排序是结合 H2OMeta 当前断点的产品/架构判断，不是外部框架给出的通用排序。

## 推荐合同

### 独立 effect budget

`agent_session_effect_budgets` 以 session 为主键，持久 `agent-session-effect-budget.v1`、
`max_run_submissions=1`、actor、request/idempotency/command/receipt hashes 与 created time。Row 不可 update/delete；
缺失即有效上限 0。`POST /agent-sessions/{id}/effect-budget` 只在 `created` / generation 0 /
无 plan 时接受固定 `enable-one-run` confirmation。处理顺序必须先 replay；未命中时在一个短
`BEGIN IMMEDIATE` 中第一步用同一 connection 再查 replay/conflict，封住并发 same-key fast miss；
仅仍未命中时才重读 admission 并写 immutable row，封住 grant-vs-plan TOCTOU。
已提交
grant 的响应若丢失，即使随后已开始 planning，原 key/command/actor 仍返回原 row。它不修改
AgentSession 状态，也不进入 plan/snapshot v1。

`GET /agent-sessions/{id}/effect-budget` 始终返回 200 strict read contract，`state` 只能是
`absent | present`。只有权威 `present` 才允许 runnable session 进入 plan；create/grant 响应丢失、刷新或
换客户端都通过该 GET 恢复，transport/decode/non-2xx 不得解释为 absent。

### 不可变表：`agent_run_authorizations`

首版一张表同时承担 authorization receipt 和 execution binding，避免两表双写：

```text
authorization_id                 primary key
contract_version                 agent-run-authorization.v1
session_id                       unique (v1 one binding per session)
preview_hash
plan_revision_id
plan_generation
plan_hash
workflow_revision_id
expected_state_version
input_manifest_digest
run_spec_hash                    strict canonical JSON; preserves false/empty/null semantics
execution_policy_id
execution_policy_hash
runtime_lock_hash
runtime_proof_hash
effect_budget_hash
run_id                           unique; foreign key / delete guarded
scope                            submit_workflow_run
confirmation                     authorize-workflow-run
actor                            authenticated runner token principal
request_id
idempotency_key                  unique with session
command_hash
receipt_hash
created_at
```

表必须有 update/delete 禁止触发器。首版不存自由文本 reason，避免 PHI、路径、credential 或
model content 进入永久 receipt。Public field 使用 `receiptHash`，避免与 Agent contract 的
secret-like `authorization*` key guard 冲突。

`serverId` 只作 local API 路由 hint，不进入 Agent durable contract。运行表的历史 NOT NULL 列使用远端
保留 namespace `agent-control-plane.v1`，并由公开 run/trigger contract 拒绝该前缀。该值不是
actor、route 或 runner identity。

### Server-owned preview 与 request

`GET /api/v1/agent-sessions/{session_id}/run-authorization-preview` 服务端重建 exact effect，返回：

```text
agent-run-authorization-preview.v1
session/plan/workflowRevision identities
inputManifestDigest
runSpecHash
executionPolicyId + executionPolicyHash
runtimeLockHash
runtimeProofHash
effectBudgetHash + max/used/remaining
tool/runtime/resource summaries
consequenceCode = create-and-enqueue-one-workflow-run
previewHash
```

`previewHash` 使用 domain-separated strict canonical JSON，覆盖全部授权字段，不覆盖可变文案或时间。
Browser 只展示该 projection。Remote POST 只接受：

```text
agent-run-authorization-request.v1
expectedStateVersion
expectedPlanRevisionId
expectedPlanGeneration
expectedPlanHash
expectedWorkflowRevisionId
expectedPreviewHash
expectedInputManifestDigest
expectedRunSpecHash
expectedExecutionPolicyHash
expectedRuntimeProofHash
confirmation = authorize-workflow-run
requestId
idempotencyKey
```

禁止 `serverId`、actor、runId、runSpec、graph、upload、execution JSON、tool parameters、新文件或自由文本。
Local facade 可以额外接受 `serverId` 作为路由字段，但必须在转发前剥离。当前 actor 仅能证明
runner bearer-token principal，不宣称审计到终端个人；多用户前必须增加可验证身份传递。

V1 只接受精确 `h2ometa.fastq-qc.v1@1.0.0` deterministic adapter 与对应 goal schema。任何未知 adapter、
context/adapter 身份不一致或缺少 remote canonical validator 的 session 都以稳定 unsupported 错误拒绝；不得
为了“通用”而退回 caller-authored WorkflowDesign/runSpec。

新增 run authorization POST、preview GET、binding GET 及对应 governance actions。不静默扩展 strict
`agent-session-snapshot.v1`；binding/effect budget 使用独立 read contract。未来若进入 Agent event chain，
应正式定义 event/snapshot v2。

### 完整 effective policy 与 runtime 边界

Remote runner 从 goal、materialized upload ledger、active PlanRevision、immutable WorkflowRevision 和 graph snapshot
重建 runSpec。固定 `agent-fastq-qc-execution.v1` builder 必须把 queue、retry 和所有 timeout 数值全部
materialize，不依赖可随代码变动的隐式默认。

规范 policy map 固定为：

```text
queueName = default
retryPolicy = {schemaVersion: execution-retry-policy.v1, maxAttempts: 3, backoffSeconds: 5}
timeoutPolicy = {schemaVersion: execution-timeout-policy.v1, queueTtlSeconds: 0,
  startToCloseTimeoutSeconds: 0, heartbeatTimeoutSeconds: 60}
```

两个 0 明确禁用 queue/start-to-close deadline，不表示缺失或默认；heartbeat 60 不读取 worker fallback。
任何数值变更都要求新 policy ID/contract。

现有 `workflow-runtime-lock.v1` 只记路径，不足以支撑 Agent exact execution。新
`agent-workflow-runtime-proof.v1` payload 不含 hash 字段，持久 platform、runner protocol
version/fingerprint、已验证 bootstrap-manifest fingerprint、workflow runtime provider/source/version、
Snakemake canonical path/binary SHA/reported version、managed conda canonical path/binary SHA/root prefix、
profile canonical dir/name/file SHA，以及 release/local wrapper mirror deterministic tree hash。

`runtimeProofHash` 是 domain `agent-workflow-runtime-proof.v1` 下该 payload 的 strict canonical SHA-256。
`workflow-runtime-lock.v2` envelope 固定包含 `schemaVersion`、完整 `proof` 和该 hash；`runtimeLockHash` 是
domain `workflow-runtime-lock.v2` 下完整 envelope 的 strict canonical SHA-256，明确包含
`runtimeProofHash`，两者不是可互换字段。旧 v1 lock 不可授权，必须重新 plan/approve/compile。
Preview、authorize 与 worker launch 都重建 proof payload/hash 并与 revision envelope 全等。

该 proof 覆盖受 runner 管理、实际 launch 读取的 runtime/profile/wrapper 输入，但仍不是 conda
environment/package 的完整 attestation。绑定前 mismatch 可 replan/reapprove/recompile；绑定后 mismatch 使
bound run 稳定失败，不允许 rebind。恢复 exact runtime 后可对同 run retry/resume 并再次验证；改变
runtime/revision 则创建新 AgentSession。

## 短事务 mutation 与恢复

授权服务必须先从既有 run storage 提取 connection-scoped primitive，并保留通用 `/runs` wrapper 行为不变。
大文件 SHA、runSpec rebuild、runtime check 和 preflight 在 writer transaction 外产生 candidate preview。

但不能先重建 candidate 再判断 replay。服务先规范化 request/actor、计算 `commandHash`，按
`sessionId + idempotencyKey` 快速查 binding。同 key、同 command/actor 则验证 receipt 与 bound run 的不可变
creation identities 以及 submit command/event/job/idempotency origins，直接返回原 binding 和当前 run
projection；同 key 不同 command 或已 binding 但 key 不同均冲突。只有权威地确认无 binding
后才做昂贵校验。这使 202 丢失后的 replay 不依赖当前 input/runtime/policy 仍与授权时相同；
验证不要求 mutable run/job status 停留在 initial accepted 值。

一个短 `BEGIN IMMEDIATE` 中完成：

1. 再次查询 authorization replay/conflict，封住快路查询后的并发 race；
2. 用同一 connection 重读 session、active plan/revision、effect budget、binding count 和 lifecycle admission；
3. 精确比较 expected state/plan/revision 与 candidate preview/input/runSpec/policy/runtime/budget hashes；
4. 生成 authorization/run identities 与 domain-separated internal run idempotency key；
5. 创建 run、submit command、accepted event、job 和 run idempotency；
6. 写不可变 authorization/binding；
7. commit 后返回 202。

授权哈希不得复用会删除 `False`、空值等字段的 `canonical_payload_hash()`。内部 run key 从
`sessionId + authorizationId + commandHash` 派生，不用 raw caller key。Replay 必须从 Agent binding
开始并全等验证 bound run/command/event/job/idempotency；无 binding 却碰撞 run key 时 fail hard。故障注入
覆盖每个写点，证明 rollback 后无 orphan binding 或 unbound run。

文件 bytes 在事务后仍可能漂移。Worker 从 `run_id -> authorization.session_id -> immutable FASTQ goal`
取得 expected manifest，重算 `fastq_qc_manifest_digest()` 并与 receipt 全等，再把 goal 中每个
uploadId/filename/SHA-256/size/MIME 与 bound runSpec 和当前 upload ledger 全等校验。随后才把 upload
拷贝到 run-private input materialization，边拷贝边校验 size/SHA-256/digest，并只将该副本交给 executor。

副本先写临时文件，验证后 atomic rename；run-level snapshot manifest 记录 receiptHash、digest 与逐输入
hash/size，并写 run event。崩溃残留可清理；initial/retry/resume 都必须经过同一 run-level gate，现有 resume
不得直接复用未重验 workdir/config。只有再次校验通过的完整 materialization 才可复用，不匹配在任何科学
进程启动前以稳定错误失败。

## 生命周期与 UI

首版一个 session 最多绑定一个 run。binding 后：

- Agent `replan` 与 Agent `cancel` 在同一数据库事务内明确拒绝；
- 不把 run status 写进 AgentSession，也不新增 running/succeeded/failed 影子状态；
- cancel/retry/resume 继续由 `runId` 对应的 WorkflowRun 控制面权威处理；
- Agent cancel 不隐式 cancel run；
- 新分析或新方案创建新的 AgentSession。

snapshot-only `agent-session-observation.v1` 在 `ready_to_run` 只能提示“检查运行授权”。Workbench 必须同时读取
binding：无 binding 时显示第二次授权；有 binding 时显示 bound `runId` 和现有 run detail 链接，不再显示
“待授权”。这应通过新的组合只读投影完成，不让 observation 自己发请求或产生 mutation。

UI 的确认面至少显示：plan/WorkflowRevision identity、input manifest digest、工具与 runtime lock 摘要、资源和
effective execution policy，以及“将创建并排队运行”的明确后果。按钮不得允许用户编辑 runSpec
或填写自由文本。V1 关闭确认面只表示不执行，不持久 decline；Agent cancel 是独立命令。

Binding 投影必须区分 `loading | authoritative_absent | present | error`；网络/解码错误不得当作
“无 binding”。POST 成功后消费返回 receipt 并失效 binding/run caches。Agent run 中持久的
`runs.serverId` 是 internal namespace，绝不能作 local route。Workbench 将当前 ephemeral local `serverId`
显式传入 run detail URL/API；多 runner 且缺失 hint 时 fail closed，不查当前偶然选中的其他 runner。
Binding GET 使用 200 的 strict read contract，明确返回 `state: absent | present`；只有该 `absent`
才映射为 `authoritative_absent`，transport/decode/non-2xx 都是 error。

## Pause、cancel、retry、resume 的准确命名

当前 run 控制面：

- cancel 已实现，并能向活跃 attempt 发出 cooperative termination；
- retry 只用于 failed/canceled 终态；
- resume 是终态 run 的证据化 `snakemake --rerun-incomplete` 重执行；
- 真正 pause 不存在，没有 paused state、process checkpoint 或 worker 语义。

因此本切片不把 cancel+resume 包装成 pause。未来真实 pause 必须在 run/attempt/job/lease/command/event 模型中
单独设计；AgentSession 不持有第二套执行状态。

## Provider loop 的前置事实

在 live provider 前至少需要：

- durable `planner_invocation_started`，发生在任何 provider side effect 之前；
- runner-authoritative model-turn/tool-call/retry reservation，预算按 reservation 计数；
- completed/failed/`outcome_unknown`/`abandoned` facts，带稳定 invocation/turn/call identity；
- provider request 可能已发出但本地未持久结果时烧毁 reservation，不写成 failed 或 usage=0；
- provider usage 的 `reported | unavailable` 区分，缺失不能写 0；
- token/cost 分离，cost 带 currency 与 pricing snapshot identity；
- event-type-specific strict payload 和 size cap，只存 template/hash/digest/error code；
- 禁止 raw prompt、transcript、model output、tool args/results、credential、path 与 chain-of-thought；
- fail-closed adapter/remote validator registry；
- deterministic fixture 与 record/replay proof。

还必须选定唯一 conversation/history owner。H2OMeta ledger、provider conversation 与 SDK session 不得同时回灌，
否则会重复上下文；provider conversation/session ID 只可作非权威 opaque reference。

达到这些前置条件后，首个 live loop 仍只应是单 session、顺序式、只读 planning tools 与 strict structured
output，不含副作用工具、自动 run、多 Agent 或任意代码。

## Contrarian views

### “typed replan 的多数骨架已有，应该先做”

它确实更便宜，也应紧随 A。反对优先级的理由不是技术不可行，而是它不解决当前最高价值的端到端断点。
此外运行授权先冻结 effect boundary，typed replan 随后可以明确规定 binding 后不可再修改旧 session。

### “直接复用 `/runs` 最快”

这会把 caller-supplied upload/execution/runSpec 带入 Agent path，且 compile approval 没有覆盖它们。即使通用
run idempotency 正确，也没有 Agent authorization receipt，不能证明谁批准了哪一个 plan/input/policy。

### “把 run status 加到 AgentSession 最直观”

这会产生两套权威生命周期并最终漂移。AgentSession 只记录 goal、plan、approval 和 binding；WorkflowRun
继续拥有 queue、attempt、cancel、retry、resume 和 result 状态。

### “先接 Biomni-like loop 才是真 Agent”

Biomni 的开放执行建立在巨大、策展过的 action environment 上，公开实现仍明确要求 production sandbox。
H2OMeta 当前没有 provider invocation checkpoint、usage reservation、sandbox 或副作用工具授权；先接 loop 会
让模型调用和预算在崩溃后变成未知事实，并可能绕过 capability/revision gate。

## Stop conditions

若实现需要以下任一行为，应停止并新立合同：

- browser/provider 提交 runSpec、graph、runId、upload binding 或任意 execution JSON；
- 未注册/未知 planner adapter 获得 run authorization；
- compile approval 自动授权 run；
- authorization 与 run 分两个事务；
- 修改 AgentSessionBudget/PlanRevision/snapshot v1 形状或改写旧 canonical bytes/hash；
- 缺失 effect-budget row 时按 1 处理，或进入 planning 后事后 grant；
- 公开 run/trigger 路径可占用 `agent-control-plane.` 保留 namespace；
- 没有 server-owned preview 就让用户确认，或将 stale preview 静默升级为新 policy；
- 在 SQLite writer transaction 中对大文件做 SHA/preflight；
- worker 直接读取未经 bound digest 验证的 upload bytes；
- 把 run status 镜像进 AgentSession；
- binding 后仍允许同 session replan/cancel；
- 将 cancel+resume 宣称为 pause；
- 复用会丢弃 false/empty/null 的 hash 作为 receipt/preview/runSpec hash；
- 在 authorization event/trace 中保存 raw prompt、model output、tool content、path 或 credential；
- 为了接 SDK/provider 而让远端存 credential 或调用 LLM；
- 同时回灌本地 history 和 provider-managed conversation/session。

## 开放问题

- governance audit projection 是否需要 connection-scoped writer，还是 immutable authorization receipt 已足够作为
  权威事实并让 audit projection 可重建？
- input manifest digest 的 goal-context 与 materialized-byte domains 是否还需要分开持久？
- 长期是否应把 idempotency namespace 从历史 `runs.server_id` 拆成独立列？
- 未来一个 session 多次 run submission 是新 contract version，还是每次 retry/resume 始终复用同一个 run？
- 真实 pause 是否值得支持，还是对 Snakemake batch workload 继续采用 cancel + terminal resume 更诚实？
- provider invocation facts 应进入 Agent event v2，还是单独 aggregate 后由 workspace snapshot v2 原子组合？

## 分阶段交付建议

1. 本研究与 ADR，冻结 one-session/one-binding、独立 effect budget、exact preview 和短事务边界；
2. behavior 1：v19 effect-budget/authorization schema、contracts、immutable storage、legacy compatibility/migration proof；
3. behavior 2：server-owned preview、固定 policy builder、reserved namespace 与 connection-scoped run creation；
4. behavior 3：短事务 authorize+run、worker run-private input proof、endpoint/governance/local facade；
5. UI：显式 effect grant、第二确认、四态 binding、ephemeral server route 和 run detail handoff；
6. fault injection、Windows pytest/ruff、typecheck/build、launcher/browser acceptance；
7. 每阶段精确 commit/push/fetch verify；随后单独做 FASTQ QC typed replan。

## 一手来源

- [OpenAI Agents SDK human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [OpenAI Agents SDK RunState](https://openai.github.io/openai-agents-python/ref/run_state/)
- [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/)
- [OpenAI Agents SDK running agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI API background mode](https://developers.openai.com/api/docs/guides/background)
- [OpenAI MCP and connectors approvals](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [Temporal Human-in-the-Loop AI Agent](https://docs.temporal.io/ai-cookbook/human-in-the-loop-python)
- [Temporal Workflows](https://docs.temporal.io/workflows)
- [Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)
- [Temporal Activity Execution](https://docs.temporal.io/activity-execution)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [MCP elicitation 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
- [MCP tools 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [MCP authorization 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [MCP Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview)
- [Microsoft Agent Framework HITL](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)
- [Microsoft Agent Framework durable extension](https://learn.microsoft.com/en-us/agent-framework/integrations/durable-extension)
- [A2A official specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- [Biomni paper](https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1.full.pdf)
- [Biomni repository](https://github.com/snap-stanford/biomni)
- [OpenTelemetry GenAI agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [Anthropic Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- [Anthropic Measuring AI agent autonomy](https://www.anthropic.com/research/measuring-agent-autonomy)
- [Anthropic Long-running Claude for scientific computing](https://www.anthropic.com/research/long-running-Claude)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [OWASP Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)

## Rerun inputs

```text
workflow: firecrawl-deep-research
topic: choose the next H2OMeta Agent-first slice among exact run authorization
  and Agent-to-Run execution binding, typed FASTQ QC replan, and a
  provider-neutral multi-turn loop; preserve immutable WorkflowRevision,
  capability gates, Snakemake execution, artifact lineage, privacy, durable
  recovery, idempotency, and separate approval scopes
depth: exhaustive (no time limit)
source preference: official specifications, primary documentation, source code,
  Biomni paper/repository, and security standards
output: cited markdown with repository gap analysis, candidate comparison,
  contrarian findings, stop conditions, open questions, and staged delivery
```
