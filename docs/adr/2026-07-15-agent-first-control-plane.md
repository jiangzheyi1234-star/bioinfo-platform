# ADR: Agent-First Control Plane

Status: Accepted

Date: 2026-07-15

## 背景

H2OMeta 已经具备 `WorkflowDesignDraft -> WorkflowRevision -> RunLedger` 可复现边界、经过验证的
capability graph、Snakemake 编译、不可变工作流修订和 remote runner 持久账本。当前产品问题不是
“是否用 LLM 替换工作流引擎”，而是“是否仍要求科学用户先拖出 DAG，系统才开始帮助他”。

Biomni 等生物医学 Agent 证明了 goal-driven 研究入口的价值；LangGraph、OpenAI Agents SDK、
Google ADK、AutoGen 与 Temporal 的实践又表明，生产 Agent 不能只有聊天循环，还需要 checkpoint、
可恢复的人类审批、受限工具调用和稳定的执行身份。Galaxy、Seqera 等科学工作流产品即使采用表单或
意图驱动的启动方式，仍保留版本化 pipeline、类型化输入、运行监控、报告与 lineage。

## Decision Card

```text
Decision: 在现有 draft/compiler/runner 之上建立 provider-neutral AgentSession 控制面。
Track: architecture-track
Baseline: origin/main cb9266b6e2d32193f657d3de002b0aff14524f3d;
          branch codex/remove-first-run-wizard at 3ff6f0b84d9117b81731859b533270aa7dbfda95
Why now: DAG-first 要求科学用户先描述实现，再表达目标，交互顺序反了。
Accepted constraints: Windows-owned proof；remote runner SQLite 继续权威；Snakemake 继续是执行目标；
  不强制 agent framework/provider SDK；已有 capability、revision、provenance、artifact、lease、
  fencing gate 全部保留。
Rejected alternatives: chat-only UI；remote_runner 内调用 LLM；Agent-as-DAG；任意生成 shell/code；
  运行可变 draft；审批和提交运行合并为一个命令；删除 React Flow 或领域图。
Ownership split: apps/api/core 负责 planner adapter 和本地编排；apps/remote_runner 负责持久 session、
  plan、approval 事实；apps/web 负责 Agent-first workbench 和专家投影视图。
Proof required: Windows pytest/ruff、schema migration、幂等/重启恢复、npm build、launcher smoke，
  以及 FASTQ QC 的真实浏览器验收。
Stop conditions: dirty-file 冲突；remote artifact/schema 不同步；持久化 secret；无乐观锁的状态迁移；
  或任何绕过 capability/revision gate 的路径。
Cleanup: 验收后清理研究缓存、测试产物；保留用户创建的文件。
```

## 决策

H2OMeta 转为 **Agent-first，而不是 chat-only**。

默认 workbench 从科学目标、输入、约束和期望证据开始，展示结构化方案、验证问题、审批、活动、结果和
provenance。聊天只是控制面之一，不是事实来源；每个会产生后果的动作都必须成为类型化命令和持久事件。

DAG 不再是主创作交互，但继续承担：

- 供验证器和 Snakemake 编译器消费的确定性工作流图；
- lineage、运行进度和 plan diff 投影；
- 面向专家的只读检查面，用于查看 ports、resources、revisions 和 artifacts。

DAG 不得承载隐藏的模型推理、对话轮次或控制面 retry。React Flow 只是 view adapter，领域图 contract
继续独立于 React Flow。

## 持久 Contract 边界

| Contract | 可变性 | 权威 Owner | 用途 | 可运行 |
| --- | --- | --- | --- | --- |
| `AgentSession` | 仅状态机迁移 | `apps/remote_runner` | 长期 goal、budget、当前 plan generation、approval 与 audit | 否 |
| `PlanRevision` | 不可变 | `apps/remote_runner` | 精确结构化方案、归一化验证结果、plan hash 与 draft 身份 | 否 |
| `WorkflowDesignDraft` | 通过 `expectedRevision` 修改 | `apps/remote_runner` | 人与 Agent 协作编辑的科学工作流设计 | 否 |
| `WorkflowRevision` | 不可变 | `apps/remote_runner` | 含 graph/tool/runtime/checksum provenance 的编译产物 | 是，只能按引用运行 |
| `RunLedger` | append-only 事实加投影 | `apps/remote_runner` | command、attempt、lease、event、artifact、evidence、reconcile | 执行事实 |

`PlanRevision` 不替代 `WorkflowDesignDraft`。它把一次归一化方案绑定到精确的 `draftId`、draft
`revision` 和 plan-only 验证结果。`planHash` 覆盖可执行方案、解析后的 `toolRevisionId`、resource
binding、验证证据、planner metadata 和 budget snapshot；纯展示文案不进入 hash。

任何实质性 draft 修改都会使当前 approval 失效，并生成新的 `PlanRevision`。Approval 持久记录
`planRevisionId`、`planHash`、`planGeneration`、approver、scope 和 timestamp。Compile 再次核对
draft revision 与 hash，随后创建或复用不可变 `WorkflowRevision`。Approval 永远不直接提交运行。

每次 replan 创建带 `parentPlanRevisionId` 的子 `PlanRevision`。若基于已审批或已编译方案 replan，
同时 fork `WorkflowDesignDraft`，绝不修改旧 `WorkflowRevision`。审批前修正可以通过现有
`expectedRevision` 更新活动 draft，但仍必须产生新的 plan revision。

## 部署与信任边界

- 模型/provider 调用与 planner adapter 运行在本地 `apps/api`/`core`，用户选择的 credential 和本地
  context 不跨入 remote runner。
- Remote runner 持久化 `AgentSession`、`PlanRevision`、approval、budget accounting 和 append-only
  `AgentEvent`；它不调用 LLM，也不存 provider credential。
- `serverId` 只用于本地路由，不远端持久化。Provider audit 只保存中性、已脱敏的 `adapterId`、
  `adapterVersion`、`modelRef`。
- Local API 可以校验、路由和聚合，但不得维护影子 Agent/run 数据库。
- Agent event 使用独立 aggregate 与 hash chain，不混入 `run_events`；一个 session 可以产生多个
  plan、workflow revision 和 run。

本决策不要求引入 LangGraph、Temporal、OpenAI Agents SDK、Google ADK 或 AutoGen。它们的持久化
模式用于约束 contract；原生状态机被证明可靠后，才评估 adapter。

## `agent-session.v1` 状态机

首版只做到 submit-ready：

```text
created -> planning -> awaiting_approval | plan_failed
awaiting_approval -> ready_to_run | changes_requested | cancelled
plan_failed | changes_requested | ready_to_run -> planning
cancelled -> terminal
```

命令必须携带 `expectedStateVersion`，approval 还必须携带 `expectedPlanHash`；成功命令递增
`stateVersion`。客户端提供 `idempotencyKey`，重复命令返回原结果。非法迁移必须明确失败。复合 planning
中途崩溃后只能留下可恢复 command 或明确 `plan_failed` event，不能出现“看似已审批”的半成品。

最小事件集为 `agent.session_created`、`agent.plan_requested`、`agent.draft_created`、
`agent.draft_revised`、`agent.plan_validated`、`agent.plan_rejected`、`agent.approval_granted`、
`agent.changes_requested`、`agent.workflow_revision_compiled`、`agent.replan_requested` 和
`agent.session_cancelled`。

## 安全与审计不变量

1. Planner 只能选择 `agentSelectableTools` 中具有精确 `capability-bundle-v1`、`toolRevisionId`、
   类型化 port、environment lock、fixture、expected artifact 和通过证据的工具；registry planning 与
   remote validation 仍是权威。
2. 任意生成 shell、Python、Snakemake rule 或 caller-supplied `RuleSpec` 不得跨越控制面边界；未知
   payload 明确失败。
3. Session 有 plan generation、planner/tool call、wall time、external bytes、model token/cost 与 run
   submission 硬预算。达到硬上限只能暂停或失败，模型不能提高自己的预算；首个切片
   `maxRunSubmissions` 为 `0`。
4. Side effect 必须分级。Draft planning 可逆；compile 需要持久审批；run submit、cancel、data delete、
   credential change 和 external publish 各自需要独立 policy 或 approval。
5. Event 只存结构化方案、脱敏摘要、hash、tool result 和 decision evidence；不存 API key、authorization
   header、raw credential、raw chain-of-thought、system prompt、未脱敏 model output 或含 secret 的路径。
6. Tool input/output 必须 schema 校验并限制大小；UI 文本和工具内容都是 untrusted data，不是指令。
   Approval 详情必须展示精确 action、arguments、target、risk、affected revision 和 budget impact。
7. Run submit 继续只接受不可变 `workflowRevisionId`；attempt lease、fencing、candidate output adoption
   和 artifact lineage 不变。

## 首个纵向切片：FASTQ QC

第一刀无需真实 LLM。确定性 provider-neutral adapter `fixture.fastq-qc.v1` 接受“对这些 FASTQ 做质量
检查并生成汇总报告”，从 registry 选择 FastQC 到 MultiQC 的精确 capability bundle：

```text
create AgentSession
  -> propose exact tool revisions
  -> create/fork WorkflowDesignDraft
  -> existing plan-only validation
  -> persist immutable PlanRevision and planHash
  -> visible human approval
  -> verify hash and compile WorkflowRevision
  -> ready_to_run (no submission)
```

验收必须证明：重启恢复；重复命令幂等；过期 state/hash 被拒绝；不可由 Agent 选择的工具被拒绝；approval
可审计；replan lineage 不可变；approval 没有创建任何 `RunLedger` 记录。先证明控制面，再接 provider
adapter 或自主执行循环。

## 非目标

- 替换 Snakemake，或新增 engine-independent workflow DSL。
- 删除图 contract、React Flow、workflow history 或 lineage view。
- 把聊天记录当成权威状态。
- 首刀引入 multi-agent delegation、开放式研究、RAG memory、任意代码执行或强制 MCP 工具面。
- 首刀 approval 后直接 submit、自动 retry 或自动 publish。
- 把 Kubernetes、Temporal、Redis、Postgres、Argo、Nextflow 或 CWL 设为前置依赖。

## 影响

科学用户可以先表达 intent 和 evidence，而不是先操作画布；H2OMeta 同时保留工作流平台需要的确定性和
可审计性。代价是新增持久 aggregate、migration、approval UI 和明确 recovery semantics。我们接受该
成本，因为把 chat-only Agent 直接接到 run API 会让 failure、approval 和 reproducibility 更难证明。

## 研究来源

- Biomni repository 与 paper：<https://github.com/snap-stanford/Biomni>、
  <https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1>
- LangGraph durable execution 与 interrupts：
  <https://docs.langchain.com/oss/python/langgraph/durable-execution>、
  <https://docs.langchain.com/oss/python/langgraph/interrupts>
- OpenAI Agents SDK human-in-the-loop：
  <https://openai.github.io/openai-agents-python/human_in_the_loop/>
- Google ADK resume 与 session state：<https://google.github.io/adk-docs/runtime/resume/>、
  <https://google.github.io/adk-docs/sessions/state/>
- AutoGen save/resume state：
  <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html>
- Temporal durable execution 与 workflow versioning：<https://docs.temporal.io/workflow-execution>、
  <https://docs.temporal.io/workflow-definition#workflow-versioning>
- Model Context Protocol tools、elicitation 与 security：
  <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>、
  <https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation>、
  <https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>
- Galaxy workflow editor：
  <https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/workflow-editor/tutorial.html>
- Seqera Launchpad 与 reports：<https://docs.seqera.io/platform-cloud/launch/launchpad>、
  <https://docs.seqera.io/platform-cloud/reports/overview>
