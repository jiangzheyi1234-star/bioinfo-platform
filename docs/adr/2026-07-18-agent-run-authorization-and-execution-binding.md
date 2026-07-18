# ADR：Agent 运行授权与原子 execution binding

- 日期：2026-07-18
- 状态：Accepted for the next Agent-first vertical slice
- 关联研究：[先建立 Agent 运行授权与执行绑定](../research/2026-07-18-agent-run-authorization-before-provider-loop.md)
- Active branch baseline：`codex/remove-first-run-wizard` @
  `0af5f5cc445acf09c01ba1ecb0864506a4519f75`

## 决策卡

```text
Decision: 下一刀实现一次性 AgentRunAuthorization 与 AgentSession->WorkflowRun execution binding；
  authorization 和既有 run ledger 在 remote runner 同一 SQLite 事务创建
Track: Agent-first product/control-plane track
Why now: Workbench 已到 ready_to_run，但编译审批按合同不能提交执行；这是 goal 到真实结果的端到端断点
Accepted constraints: DAG 仅作内部确定性表示；复用 WorkflowRevision、Snakemake、RunLedger、worker、
  cancel/retry/resume 和 artifact lineage；serverId 只作 local routing；运行预算使用独立 effect-budget
  contract，缺失按 0；v1 仅支持 h2ometa.fastq-qc.v1@1.0.0 且一个 session 最多绑定一个 run；
  run status 不镜像到 AgentSession
Rejected alternatives: 直接复用 POST /runs；compile approval 自动 submit；caller-authored runSpec/execution；
  向 AgentSessionBudget v1 偷加字段；authorization/run 双事务；长时间持有 SQLite writer lock；
  AgentSession running/succeeded/failed 镜像；cancel+resume 冒充 pause；先接 live provider
Proof required: v19 migration、immutable trigger、effect budget fail-closed、server-owned preview、strict hash、
  reserved namespace、idempotency/conflict、fault injection rollback、server-side runSpec rebuild、worker input snapshot、
  upload/revision/policy tamper rejection、existing /runs regression、local/remote endpoint parity、Windows pytest/ruff、
  frontend typecheck/build、launcher/browser acceptance
Stop conditions: 需要 browser/provider authority；不能单事务写 binding+run；旧记录会被放宽或改写；
  需要修改 agent-session/plan/snapshot v1；或会形成第二套 run lifecycle
Delivery: research/ADR、storage contract、atomic behavior、API/facade、UI/browser 各自精确 commit/push/fetch verify
```

## 背景

H2OMeta 已经具备 goal-first AgentSession、deterministic FASTQ QC planner、不可变 PlanRevision、可审计编译审批、
WorkflowRevision 和 snapshot-derived observation。批准后的 session 停在 `ready_to_run`，并且已有合同与测试保证
此时没有 WorkflowRun。

该分离是正确的：`compile_workflow_revision` 只批准产生一个不可变可执行修订，不批准消耗计算资源或产生外部
副作用。下一步必须新增单独运行授权，而不是扩大旧 approval。

## 决策

新增 remote runner 权威 aggregate：

```text
AgentRunAuthorization == immutable authorization receipt + execution binding
```

它精确绑定当前 session/plan/revision/input/effective runSpec 与唯一 `runId`。授权成功与 WorkflowRun 创建在
同一个 `BEGIN IMMEDIATE` 中提交；任一写入失败全部 rollback。丢失响应后，同 idempotency key 与同 command
hash 返回原 authorization 和同一个 run。

首版不新增 AgentSession 的 running/succeeded/failed 状态，也不把 WorkflowRun 状态复制到 Agent ledger。
绑定后所有执行生命周期仍由既有 RunLedger 权威管理。

## Effect-budget gate

`AgentSessionBudget` 和 `agent-plan-revision.v1` 保持原样。运行提交上限放入独立、不可变的
`agent-session-effect-budget.v1`：

```text
sessionId, maxRunSubmissions = 1, actor, requestId, idempotencyKey,
commandHash, receiptHash, createdAt
```

- 缺失 effect-budget row 的任何 session（包括旧 session）有效上限为 0；
- 用户选择“允许一次运行”时，新 UI 在 session 仍为 `created` / generation 0 / 无 plan 时
  显式创建该 row；不修改 session state/version；
- 该 row 不进入 AgentSession、PlanRevision 或 snapshot v1，因此不改变旧 canonical payload、
  `planHash`、approval 或 creation replay；
- 首版只有 0/1，不支持 update、increase 或 delete；binding count 是权威 usage fact；
- 模型和 planning adapter 无此 command authority；命令要求固定 confirmation 与 governance policy；
- 已进入 planning 的旧 session 不能事后补发预算，需新建 session。

这以不破坏旧 immutable evidence 的方式落实既有 Agent-first ADR 的 fail-closed
`maxRunSubmissions` 前置条件。

## Durable contract

新增 `agent_run_authorizations`，至少包含：

```text
authorization_id, contract_version, session_id, preview_hash, plan_revision_id,
plan_generation, plan_hash, workflow_revision_id, expected_state_version,
input_manifest_digest, run_spec_hash, execution_policy_id, execution_policy_hash,
runtime_lock_hash, runtime_proof_hash, effect_budget_hash, run_id, scope, confirmation, actor,
request_id, idempotency_key, command_hash, receipt_hash, created_at
```

约束：

- `UNIQUE(session_id)`；
- `UNIQUE(run_id)`；
- `UNIQUE(session_id, idempotency_key)`；
- `scope = submit_workflow_run`；
- `confirmation = authorize-workflow-run`；
- update/delete trigger 明确失败；
- `run_id` foreign key / delete guard 防止绑定后删除 run；
- `agent_session_effect_budgets` 同样禁止 update/delete；
- schema version 从 v18 升到 v19，fresh DB 与 v18 migration 产生同一 contract。

`serverId` 不存入上述 Agent durable contract。它只在 local facade 做路由并在转发前剥离；
authorization 所在的 remote DB、session 与 bound run 已定义权威归属。

既有 `runs.server_id` 是 NOT NULL 且兼作 run-idempotency namespace。Agent 路径固定使用远端保留的
`agent-control-plane.v1`；该值是 internal submission namespace，不是 local registry serverId、actor 或
物理 runner identity。所有 caller-authored 且可以创建 run/trigger 的公开 contract 必须拒绝
`agent-control-plane.` 保留前缀。长期应将 idempotency namespace 与历史 `runs.server_id` 拆列。

## API contract

预算 grant：

```text
POST /api/v1/agent-sessions/{session_id}/effect-budget
agent-session-effect-budget-grant.v1
  expectedStateVersion = 1
  maxRunSubmissions = 1
  confirmation = enable-one-run
  requestId
  idempotencyKey
```

该命令先按 session/key/command/actor 处理 replay，同 key 同 payload 直接返回原 row；只有未命中时才
进入短 `BEGIN IMMEDIATE`。事务内第一步用同一 connection 再次查 replay/conflict，封住
两个同 key grant 同时快路 miss 的 race；仅仍未命中时才重读并检查 `created` /
generation 0 / 无 plan，然后写 immutable row。因此 grant 响应丢失后，即使之后已开始 planning，
原 key 仍能 replay；其他 grant 全部冲突。

`GET /api/v1/agent-sessions/{session_id}/effect-budget` 返回 200 strict read contract，其 `state` 只能是
`absent | present`。Workbench 中选择“允许一次运行”的新 session 必须严格按
`create/recover session -> persist pending grant -> grant/replay -> authoritative present -> plan` 前进。Grant 不确定、
absent 或 error 时不得 auto-plan；刷新、换客户端或 create 响应丢失后也用该 GET 恢复。
未选择运行预算的 planning-only session 可保持现有 auto-plan 语义。

运行授权前，remote runner 提供纯读预览：

```text
GET /api/v1/agent-sessions/{session_id}/run-authorization-preview
agent-run-authorization-preview.v1
  session/plan/workflowRevision identities
  inputManifestDigest
  runSpecHash
  executionPolicyId + executionPolicyHash
  runtimeLockHash + runtimeProofHash
  effectBudgetHash + max/used/remaining
  tool/runtime/resource summaries
  consequenceCode = create-and-enqueue-one-workflow-run
  previewHash
```

`previewHash` 是对全部授权相关精确字段的 domain-separated strict canonical hash；不包含可变
显示文案或生成时间。Browser 只显示该投影，不自行构造 runSpec/policy。

新增 remote request：

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

禁止 caller 提供 actor、runId、runSpec、graph、upload binding、execution JSON、tool parameters 或文件。
Actor 由认证 principal 推导并与 session owner/policy 校验。V1 的 remote principal 仍是 runner bearer-token
principal，receipt 不宣称能审计到终端个人；多用户前必须增加可验证的身份传递。
首版不接收自由文本 reason，避免将 PHI、路径、credential 或 model content 永久写入不可变 receipt。

V1 只授权精确 `h2ometa.fastq-qc.v1@1.0.0` deterministic adapter。未知 adapter、goal/adapter identity 不一致、
或没有 remote canonical validator 的 session 明确失败，不提供 generic fallback。

端点：

- `POST /api/v1/agent-sessions/{session_id}/run-authorization`，202，governance
  `agent_session.run_authorize`；
- `GET /api/v1/agent-sessions/{session_id}/execution-binding`，独立只读 contract。

Local facade 的 request 额外含 `serverId` routing hint，但不得让它越过远端 contract。

不修改 strict `agent-session-snapshot.v1`。若未来需要把 authorization 放进 Agent hash-chain，必须正式增加
event/snapshot v2；不得向 v1 偷加字段或事件。

## Server-side runSpec 和 preview proof

Remote runner 从权威事实重建 effective runSpec：

1. 精确 session goal context；
2. materialized upload ledger，并再次校验 uploadId、filename、SHA-256、size、MIME；
3. active PlanRevision 与 immutable WorkflowRevision；
4. WorkflowRevision graph snapshot 中的 expected runSpec；
5. 固定 builder 生成的 `agent-fastq-qc-execution.v1` 完整 execution policy。

固定 policy 必须把 queue、retry 和所有 timeout 数值完整 materialize 到 runSpec，不能依赖
`execution_policy.py` 的隐式默认。随后执行 WorkflowDesign run validation、pipeline validation 与 preflight。
Browser 批准 server preview 展示出的 exact hash/identity，不参与构造执行对象。

`agent-fastq-qc-execution.v1` 的规范 map 固定为：

```text
queueName = default
retryPolicy = {schemaVersion: execution-retry-policy.v1, maxAttempts: 3, backoffSeconds: 5}
timeoutPolicy = {schemaVersion: execution-timeout-policy.v1, queueTtlSeconds: 0,
  startToCloseTimeoutSeconds: 0, heartbeatTimeoutSeconds: 60}
```

其中两个 0 是明确禁用 queue/start-to-close deadline，不是缺失/默认；heartbeat 60 为显式值，
不读 worker lease fallback。任何数值变更都必须新 policy ID/contract，不得保留同 ID 改语义。

WorkflowRevision 现有 `workflow-runtime-lock.v1` 只记路径，不足以支撑 Agent exact execution。
该切片定义 `workflow-runtime-lock.v2` envelope 与 `agent-workflow-runtime-proof.v1` payload builder。
Proof payload 不含任何 hash 字段，在 compile 时持久：

- platform、runner protocol version/fingerprint 与已验证 bootstrap-manifest fingerprint；
- workflow runtime provider/source/version；
- Snakemake canonical path、binary SHA-256 与 reported version；
- managed conda canonical path、binary SHA-256 与 root prefix；
- workflow profile canonical dir/name 与 profile-file SHA-256；
- release dir 与 local wrapper mirror 的 deterministic tree hash；
- 上述全部字段。

`runtimeProofHash` 固定为 domain `agent-workflow-runtime-proof.v1` 下 proof payload 的 strict canonical
SHA-256；`workflow-runtime-lock.v2` envelope 固定包含 `schemaVersion`、完整 `proof` 和该
`runtimeProofHash`。`runtimeLockHash` 则是 domain `workflow-runtime-lock.v2` 下完整 envelope 的 strict
canonical SHA-256，因此明确包含 `runtimeProofHash`，不是同一个值，也不允许实现自行选择其一。

所有 path 必须 canonical，文件/目录缺失或不可 hash 时 fail closed。V1 Agent authorization 拒绝旧
`workflow-runtime-lock.v1` WorkflowRevision，要求重新 plan/approve/compile。Preview、authorize 与 worker launch
前均重建当前 proof payload/hash，与 revision envelope 的 proof/hash 全等，并用原 envelope 计算同一
`runtimeLockHash`。这覆盖实际 launch 读取的配置与 profile/wrapper
bytes，但仍不是 conda environment/package 的完整 attestation；UI 不得宣称完整环境可重现性。
该恢复指引要区分时点：绑定前 mismatch 可 replan/reapprove/recompile；绑定后 worker mismatch 使
bound run 以稳定错误失败，不得回写/rebind session。运维若恢复 exact runtime config，同 run 可按既有
retry/resume 再次验证；若要使用新 runtime/revision，必须新建 AgentSession。

`run_spec_hash` 使用保留完整 JSON 类型与字段的 domain-separated canonical hash。不得复用会删除
`False`、空字符串、空集合或 `null` 的通用 `canonical_payload_hash()`。

## 短事务 atomic mutation

先从 `workflow_run_storage.py` 提取 connection-scoped run creation primitive；现有 `create_run_record()` 保持
兼容 wrapper 和回归行为。大文件 SHA、runSpec rebuild、runtime check 和 preflight 在事务外产生
当次 candidate preview，不得在 `BEGIN IMMEDIATE` 中持有全局 writer lock。

在做任何昂贵 candidate 工作前，先规范化 request/actor 并计算 `commandHash`，再按
`sessionId + idempotencyKey` 快速查 binding：

- 同 key、同 command/actor 命中时，验证 receipt 与 bound run 的不可变 creation identities/
  submit command/event/job/idempotency origins，然后直接返回原 binding 和当前 run projection；
- 同 key 不同 command 冲突；已有 binding 但 key 不同则按 one-binding 规则拒绝；
- 只有权威地确认“无 binding”后，才重建/重算 preview。

该快路使响应丢失后的 replay 不依赖当前 upload、runtime 或 policy 仍与授权时相同。
验证的是创建来源与绑定不变式，不要求 mutable run/job status 停留在 initial accepted 值。

Agent authorization 的短事务内依次：

1. 再次处理 authorization idempotency replay/conflict，封住快路查询后的并发 race；
2. 用同一 connection 重读 session、active plan/revision、effect budget、binding count 和 lifecycle admission；
3. 校验 expected state/plan/revision 以及 candidate 的 preview/input/runSpec/policy/runtime/effect-budget hashes；
4. 生成 authorization/run identities 与内部 run idempotency key；
5. 写 `runs`、submit command、accepted event、job、run idempotency；
6. 写 authorization/binding；
7. commit。

每个写点都需要 fault-injection proof。事务外不能留下 orphan authorization、unbound run 或已排队但不可追溯的
job。

现有通用 submit command/event 把 `serverId` 当 actor；新 connection primitive 必须接收明确 actor，使 Agent
路径记录认证 principal，同时保持通用 `/runs` 的现有语义，除非另立独立修复。

内部 run idempotency key 使用 versioned domain separator 从 `sessionId + authorizationId + commandHash`
服务端派生，不复用 caller key。Authorization replay 必须先找到 binding，再全等校验 bound
run/command/event/job/idempotency；若无 binding 却命中任何 run-idempotency row，必须 fail hard，不得只凭
payload hash 把它当作 Agent replay。
一个 run 是否属于 Agent 只能由不可变 binding 判定，绝不能通过
`runs.server_id = agent-control-plane.v1` 推断。

### 授权后、执行前的 input proof

授权事务不能锁住文件 bytes。Worker 在启动 Snakemake 前必须按 bound run 读取 expected
manifest，把 upload 拷贝到 run-private input materialization，边拷贝边校验 size/SHA-256/digest，
并只把该已验证副本交给 executor。副本先写临时文件，验证后 atomic rename；崩溃残留可清理，
retry/resume 仅复用再次校验通过的已完成 materialization。不匹配时在任何科学进程启动前终止并写
稳定失败事实。
这要求覆盖“authorize 后、worker 前”修改 upload 的验收测试。

Expected manifest 的权威取法固定为
`authorization.run_id -> authorization.session_id -> immutable FASTQ goal context`；worker 重算
`fastq_qc_manifest_digest()` 并与 receipt 比较，再把 goal 的 uploadId/filename/SHA-256/size/MIME 与
runSpec 输入及当前 upload ledger 全等校验。Run-level snapshot manifest 记录 receiptHash、digest 与每个
输入的 hash/size，并写一个 run event。所有 initial/retry/resume 执行路径都必须经过该同一
run-level gate；现有 resume 不得绕过 input resolver 而直接复用未重验的 workdir/config。

## Binding 后的生命周期

V1 一个 session 只绑定一个 run：

- 同 key replay 返回相同 binding/run；
- 不同 key 的第二次 authorize 明确拒绝；
- replan 与 Agent cancel 在它们自己的事务中检查 binding 并明确拒绝；
- Agent cancel 不级联 cancel run；
- run cancel/retry/resume 使用既有独立治理命令；
- 新方案或新输入创建新 AgentSession。

Run 的 cancel 已存在；retry 只用于 failed/canceled 终态；resume 是带证据的
`snakemake --rerun-incomplete` 重执行。真正 pause 当前不存在，本 ADR 不把 cancel+resume 改名为 pause。

## Workbench

新增第二次确认面，只在以下条件同时满足时出现：

- session `ready_to_run`；
- `maxRunSubmissions == 1` 且无 binding；
- active plan/revision/hash 完整；
- 当前 principal 具备运行授权 policy。

它展示 exact plan/WorkflowRevision identity、input manifest digest、tool/runtime lock 摘要、resources、effective
execution policy 和“将创建并排队运行”的后果。用户只能提交固定 confirmation，不能编辑
runSpec 或添加自由文本。

有 binding 时展示 authorization receipt、bound `runId` 和既有 run detail 链接。Workbench 组合
snapshot-derived observation 与 binding read：无 binding 才显示待授权，有 binding 显示已绑定；observation
helper 本身继续是纯函数，不发请求、不产生 action。

Binding read 必须区分 `loading | authoritative_absent | present | error`；网络或解码错误不得当作
“无 binding”。POST 成功后直接消费返回 receipt，并失效 binding/run caches。
Binding GET 使用 200 的 strict read contract，明确返回 `state: absent | present`；只有该 `absent`
才映射为 `authoritative_absent`，transport/decode/non-2xx 全部是 error。

`runs.serverId` 对 Agent run 会显示 internal namespace，绝不能作 SSH/local API 路由。Workbench 将当前
ephemeral local `serverId` 显式带到 run detail URL 与 API；多 runner 且缺少该 hint 时 fail closed，
不得默认查询当前选中的其他 runner。

V1 只持久成功 authorization；关闭确认面表示“不执行”，不写 durable decline。Agent cancel
是独立 session command。因此这不是完整的 accept/decline/cancel 三态 approval-request lifecycle。

## 与 typed replan 和 provider loop 的顺序

FASTQ QC typed replan 紧随本切片。它只接受小型 strict adjustment，服务端确定性重建 proposal，旧 plan 与
approval 保持不可变。binding 后的 session 不允许 replan，从而避免已运行修订被“回写”。

Live provider loop 延后。在此前先建立 provider-neutral invocation/reservation/usage/retry/
`outcome_unknown`/`abandoned` facts、strict payload schema、adapter validator registry、record/replay proof 和 sandbox。
必须选定唯一 conversation/history owner；不得同时回灌 H2OMeta ledger 与 provider-managed history，
provider conversation ID 只可作非权威 opaque reference。首个 live loop 只允许顺序式只读 planning tools，
不得自动 approve、compile、authorize 或 run。

## 非目标

- 删除 DAG/graph contract 或 Snakemake；
- 新增另一个执行引擎；
- 自动运行、自动 publish 或自动 delete；
- 同一 session 多次独立 run submission；
- Agent-aware run cancel/retry UI；
- 真正 process pause/checkpoint；
- live LLM/provider、多 Agent、任意 shell/Python/MCP side effect；
- 把 chat transcript、自由文本备注或 model output 当授权事实。

## 证明计划

1. Contract：strict budget/preview/request/receipt/read，extra field/unsafe integer/secret marker/confirmation 拒绝。
2. Legacy：v18 session/plan/snapshot 读取、creation replay 与 replan 保持旧 canonical bytes/hash；不改 v1 shape。
3. Budget：缺失拒绝；created 状态显式 grant 1；grant-vs-plan 并发只允许 grant-first
   或 plan-first 后 grant 拒绝；concurrent same-key grant 只产生一 row 并返回同 receipt；
   第二个不同 grant/authorize 拒绝。
4. Migration：fresh v19、v18->v19、required table/index/FK/trigger、immutable update/delete；升级前扫描
   `runs`、`idempotency`、`workflow_triggers` 的 `agent-control-plane.` legacy collision，命中则以
   稳定 migration error 失败，不静默改写旧 identity。
5. Preview：stale input/runSpec/policy/runtime-proof/effect-budget/preview hash 全部拒绝，旧 runtime-lock v1 拒绝，
   browser 不构造 effect。
6. Storage：strict hash、same-key replay、different-payload conflict、one binding/session、one binding/run；
   grant 在 planning 后仍可 replay，authorize 在 input/runtime/policy 漂移后仍返回原 run。
7. Namespace：通用 `/runs`/trigger 拒绝 reserved prefix；internal idem key 派生；无 binding 碰撞不 replay。
8. Atomicity：run 与 binding 每个写点故障 rollback；响应丢失后同 run replay；无长 writer lock。
9. Authority：unknown adapter、stale state/plan/hash/revision、upload/revision/runSpec/tool/policy tamper 拒绝。
10. Worker：authorize 后篡改 upload 在进程启动前失败；执行只读取已验证 run-private 副本。
11. Regression：通用 `/runs`、first-run matching、run events/jobs/idempotency、worker、cancel/retry/resume 不变。
12. API/UI：principal、四态 binding、cache invalidation、ephemeral server routing、multi-runner 直链 fail-closed、
    无 DAG 创作、mutation 精确一次。
13. Windows pytest/ruff、frontend typecheck/build、`run.bat --web` 与真实浏览器验收；验收后清理本地产物。
14. 端到端：真实浏览器从 Agent goal -> plan -> compile approval -> run authorization ->
    WorkflowRun -> artifact/result detail 完成一次 happy path。

## 后果

正向：H2OMeta 获得从科学 goal 到真实可追溯结果的最小端到端闭环；所有未来 Agent 自主性都必须经过一个
精确、可恢复、可审计的 effect boundary；既有 run execution 与 lineage 投资被完整复用。

代价：需要 v19 migration、独立 effect budget、preview、run storage primitive 抽取、worker 输入物化和
第二次审批 UI；旧 session 默认不能运行；真实 pause 仍未实现。接受这些成本，因为任何更短路径都会
放宽授权、引入双写或形成双权威。

## 参考

- [完整深度研究与一手来源](../research/2026-07-18-agent-run-authorization-before-provider-loop.md)
- [Agent-first control plane](2026-07-15-agent-first-control-plane.md)
- [Snapshot-derived Agent observation](2026-07-18-snapshot-derived-agent-observation.md)
