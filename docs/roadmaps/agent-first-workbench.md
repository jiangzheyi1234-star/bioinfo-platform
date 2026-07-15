# Agent-First Workbench Roadmap

Status: Current

Last reviewed: 2026-07-15

本路线图落实 `docs/adr/2026-07-15-agent-first-control-plane.md`。它扩展而不替换
`docs/adr/2026-06-07-durable-control-plane-roadmap.md` 中已接受的持久生命周期。

## North Star

科学用户提交 goal、inputs、constraints 和期望 evidence。H2OMeta 提出类型化且经过验证的方案，解释
关键决策，在有后果的动作前暂停审批，编译不可变 workflow，通过现有 durable runner 执行，并交付带
lineage 的结果。用户可以 stop、resume、reject、fork 或 replan，而不会丢失审计历史。

默认 workbench 围绕以下生命周期组织：

```text
Goal -> Proposal -> Validation -> Approval -> WorkflowRevision -> Run -> Evidence
```

Chat 可用于澄清 goal，但不是持久状态模型。DAG 是确定性 execution、diff、progress 和 lineage 的专家
只读投影。

## 交付规则

- 只交付保持 `WorkflowDesignDraft -> WorkflowRevision -> RunLedger` 的纵向切片。
- Contract 必须 provider-neutral；接真实 model 前先通过确定性 adapter 证明。
- 所有持久 Agent 事实放在 remote runner；本地编排不维护 shadow state。
- 每个规划工具都需要精确 `toolRevisionId` 和有效 capability bundle。
- Propose、approve、compile、submit 必须是四个独立类型化命令。
- 每一阶段都要证明其新增状态的 restart recovery、idempotency、optimistic concurrency 和 redaction。
- 每个集成切片后保持 Windows launcher 与 Windows-owned proof 通过。

## Phase 0 — Contract 与 Guardrail

Outcome：在 UI 和 provider 接入前稳定原生控制面词汇。

Deliverables：

- 严格的 `agent-session.v1`、`plan-revision.v1`、command、event、budget、approval contract。
- 带 `expectedStateVersion` 且明确失败的纯 `AgentSession` transition function。
- Canonical `planHash` serialization；测试证明纯展示字段不改变 hash。
- Plan、draft write、compile、submit、cancel、delete、credential、external publish 的 side-effect/risk
  分类。
- Redaction policy 测试，拒绝 secret、authorization header 和 chain-of-thought 字段。
- 提升 remote runner schema version 前完成 schema/API compatibility 决策。

Exit criteria：

- Contract 与状态机测试覆盖每个允许和拒绝的迁移。
- Planner interface 不包含 provider enum、SDK type、credential 或 arbitrary-code 字段。
- 首刀预算有明确硬上限，且 `maxRunSubmissions: 0`。

## Phase 1 — 持久 FASTQ QC Planning 切片

Outcome：不调用 LLM、不提交 run，也能 restart-safe 地 propose、validate、approve、compile 真实工作流。

Deliverables：

- Remote SQLite `agent_sessions`、不可变 `plan_revisions`、`agent_approvals` 和 append-only、
  hash-chained `agent_events`，通过 forward migration 与 schema contract 检查加入。
- Remote command 与对应 local API：create/get/list、events、plan、approve/request changes、replan、cancel。
- `fixture.fastq-qc.v1` 选择精确注册的 FastQC、MultiQC capability bundle，并生成严格
  `WorkflowDesignDraft` proposal。
- 在公开边界上复用现有 plan-only validation 与 compile service。
- 用 `parentPlanRevisionId` 保留 replan lineage；审批/编译后 replan 必须 fork draft。

Required scenario：

1. 用唯一 `creationRequestId` 为 FASTQ QC/report goal 创建 session。
2. 对已注册 `reads.fastq` 或 `reads.fastq.gz` input 进行 plan。
3. 持久化精确 draft revision、normalized preview、validation evidence、budget 与 `planHash`。
4. State version、plan generation、plan hash、tool revision 或 draft revision 过期时拒绝 approval。
5. 有效 approval 只编译不可变 `WorkflowRevision`，状态变为 `ready_to_run`。
6. 证明没有创建 run command、attempt 或 run event。
7. Replan 后，旧 plan、draft/revision reference、approval 和 workflow revision 仍可查询且未改变。

Exit criteria：

- 每个非终态都能在进程重启后恢复。
- 相同 idempotency key 的重复 plan/approval/replan 只产生一次持久效果。
- Capability gate、budget、stale write、stale hash 都返回明确 problem details。
- 旧 schema migration 和空数据库创建都在 Windows 通过。

## Phase 2 — Agent-First Web Workbench

Outcome：科学用户无需打开 canvas 即可完成 Phase 1。

主视图包含：

- goal、inputs、constraints、evidence expectations 与 budget controls；
- structured plan card，展示 tools、exact revisions、inputs/outputs、resources、risks 和 validation；
- approve、request changes、replan、cancel、resume，并明确 action scope；
- 由 `agent_events` 派生的持久 activity timeline；
- compile readiness 与不可变 `WorkflowRevision` identity；
- 只读 “Execution graph” advanced panel；
- plan/draft/revision diff、artifact/evidence panel 和明确 blocked recovery action。

Exit criteria：

- Browser acceptance 覆盖 create -> plan -> approve -> compile -> reload -> replan。
- Approval UI 显示 hash 绑定的精确 action、target、arguments、risk 和 budget impact。
- Stale approval 与 capability failure 可见，绝不退化为 empty/loading state。
- 迁移期间保留现有 generated-workflow builder，但默认旅程不新增 drag/drop 功能。
- Windows `npm run build`、`run.bat --web`、local smoke 与 browser proof 通过。

## Phase 3 — Live Provider Adapter

Outcome：一个或多个 live planner 可生成同一严格 contract，但不成为控制面。

Deliverables：

- 本地 provider-neutral adapter interface，包含 deterministic fixture、record/replay test adapter 与
  一个由配置选择的 production adapter。
- Structured-output validation、retry ceiling、timeout/cancellation、token/cost accounting、
  prompt/tool version audit 与脱敏 observability。
- Retrieval 只访问获批 capability 和 project context；检索文本仍是 untrusted data。
- Planner output 通过 strict contract validation 与现有 remote plan-only gate 后才可接受。
- Model/provider 故障留下可恢复 `plan_failed`，不能留下 half-approved draft。

Exit criteria：

- 更换 provider 不改变 persisted contract 或 transition。
- Recorded replay 生成相同 normalized draft 与 `planHash`。
- Prompt injection、oversized output、unknown tool、forged revision、secret echo、budget exhaustion 安全
  失败。
- API response、event、log、SQLite 中没有 raw chain-of-thought 或 credential。

## Phase 4 — 显式 Run 与 Evidence Loop

Outcome：已审批、已编译 workflow 可以提交和解释，同时不放松 runner safety。

Deliverables：

- 独立 scoped run approval/policy 与仅引用 `workflowRevisionId` 的幂等 submit command。
- Agent session 只链接 run id；run facts 仍完全归 `RunLedger`。
- Read-only run observation、结构化 failure classification、artifact/evidence summary，以及有界 retry
  或 replan proposal。
- Retry 继续使用 attempt、lease、fencing、candidate-output verification 和 atomic adoption。
- 从 failed/completed run replan 时，创建新 plan/draft/workflow revision lineage，保留旧 run 为 evidence。

Exit criteria：

- Duplicate submit 不能创建 duplicate run。
- Agent restart 不会在没有幂等 command result 时重复 side effect。
- Retry/replan recommendation 不能越过 budget 或自我审批。
- FASTQ QC 通过真实 FastQC/MultiQC artifact 完整验收，并展示 run-artifact lineage。

## Phase 5 — 扩展 Scientific Workbench

Outcome：只在控制面闭环被证明后扩展能力。

候选切片：

- 显式 database revision/evidence 的 database-bound taxonomy analysis；
- multi-sample QC 与 comparative report；
- 带 source snapshot/citation 的只读 literature/data discovery adapter；
- project template 与可复用 Agent goal/constraint preset；
- 组织级 approval/compute budget policy pack；
- 有证据支持时再增加 RO-Crate、Workflow Run RO-Crate、CWL 或 Nextflow export adapter。

Kubernetes、Temporal、Redis worker、Postgres、multi-agent delegation、autonomous publication 和
arbitrary-code sandbox 仍是可选后续决策，不是成熟度打勾项。

## 跨阶段验收矩阵

| 属性 | 必要 proof |
| --- | --- |
| Determinism | normalized proposal/hash fixture；精确 tool/runtime revision |
| Durability | 每个持久状态 stop/restart；resume 不重复 effect |
| Concurrency | 拒绝过期 `expectedStateVersion`、draft revision、plan hash |
| Idempotency | duplicate create、plan、approval、compile、replan、submit command |
| Human control | 持久 scoped approval 与 changes-requested lineage |
| Budget safety | hard limit、accounting event、模型不可自增 ceiling |
| Secret safety | contract rejection、log/event/DB scan、redaction test |
| Reproducibility | immutable WorkflowRevision、manifest hash、capability evidence、artifact lineage |
| UX | no-canvas 主路径、reload/resume、blocked recovery、expert graph projection |
| Platform | Windows pytest/ruff、migration、npm build、launcher smoke、真实浏览器 evidence |

## 指标

产品价值和控制面正确性分开度量：

- goal 到 valid proposal、approval 到 compiled revision 的中位时间；
- plan acceptance、changes-requested、validation-failure、replan 比例；
- 只使用精确 selectable capability bundle 的 proposal 比例；
- 被安全拒绝或 replay 的 stale/duplicate command；
- restart 后恢复的 session 与因 budget 阻断的 session；
- 具有完整 workflow/tool/runtime revision 和 artifact lineage 的 run；
- approval 前必须打开 expert graph 的用户数量（诊断指标，不是成功目标）。

不要把 model autonomy 或 chat length 当主指标。领先质量信号是：在明确用户控制下，得到有用、有效、
可审查、可复现的科学结果。

## 研究基线

实现期间定期复核 ADR 收集的 durability、human-in-the-loop、tool security、workflow versioning 和
scientific UX 一手资料：

- <https://github.com/snap-stanford/Biomni>
- <https://docs.langchain.com/oss/python/langgraph/durable-execution>
- <https://openai.github.io/openai-agents-python/human_in_the_loop/>
- <https://google.github.io/adk-docs/runtime/resume/>
- <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html>
- <https://docs.temporal.io/workflow-execution>
- <https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>
- <https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/workflow-editor/tutorial.html>
- <https://docs.seqera.io/platform-cloud/launch/launchpad>
