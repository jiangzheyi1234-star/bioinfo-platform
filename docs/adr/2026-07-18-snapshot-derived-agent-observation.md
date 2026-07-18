# ADR：先做 snapshot-derived Agent observation

- 日期：2026-07-18
- 状态：Accepted for the next frontend-only slice
- 关联研究：[Agent observation before the regular-file capsule](../research/2026-07-18-agent-observation-before-file-capsule.md)
- Production baseline：`origin/main` @ `cb9266b6e2d32193f657d3de002b0aff14524f3d`
- Active branch baseline：`codex/remove-first-run-wizard` @ `2a26d8375c36df327d8a1c4294dec453406720d6`

## 决策卡

```text
Decision: 下一刀先从 agent-session-snapshot.v1 派生 frontend-only agent-session-observation.v1，不实现 regular-file C primitive
Track: Agent-first product track; activation track remains gated and dormant
Why now: Workbench 已有权威原子 snapshot，却不能直接回答当前卡点、等待方、状态持续时间和可测 replan 预算；file capsule 仍无 consumer 且关键语义未冻结
Accepted constraints: 无新数据库、API、schema、治理 action、mutation、vendor SDK、trace exporter 或后台任务；只读既有 snapshot；不读取 event payload
Rejected alternatives: 立即写 file capsule；引入 OpenTelemetry backend；从配置上限伪造 usage；自动 stalled/SLA；把 observation 写回 runner；从 observation 触发动作
Proof required: 纯函数 fail-closed 测试、七状态 attention、时间异常、event linkage、replan accounting、隐私字段缺席、frontend contract、typecheck/build、真实 Workbench browser smoke
Stop conditions: 需要 provider usage、token/cost、tool args/results、prompt/model output、command hash、路径、跨 session 聚合、远端 contract 或任意 side effect
Delivery: ADR/research、behavior、UI proof 分阶段精确 commit/push；不触碰用户未跟踪文件
```

## 背景

H2OMeta 已经完成 Agent-first 的 durable session、plan、approval、atomic snapshot 和 Workbench 主入口。
现有 snapshot 在 remote runner 的同一事务中读取，完整重算含私有 `command_hash` 的 event hash chain，随后
通过 `agent-session-snapshot.v1` 交给浏览器。Workbench 已显示 plan、approval 和事件时间线，但还没有一个
紧凑的“现在发生什么”观察面。

与此同时，activation native owner 已证明 directory capability 与 directory leaves。Regular-file capsule
在 proof-only synthetic bytes 下可以继续独立证明，但 archive inspector 没有 verified decompressed payload
replay，production wheel 没有 root seed/consumer，journal、ACL/xattr、relocation、fresh walk、receipt/marker 与
supply-chain wiring 仍未冻结。它不是当前 Agent-first 主路径上的最高价值下一刀。

## 决策

新增本地纯派生合同：

```text
agent-session-observation.v1
```

它只接受已 decode 的 `AgentSessionSnapshot` 与显式 client observation epoch，返回：

- snapshot head identity：session、state version、plan generation、head sequence/hash/time；
- lifecycle：当前 status、进入时间、可选 age、时间质量、下一 attention；
- 只读计数：events、plans、approvals、replans、plan failures、change requests；
- 精确 integrity 声明：snapshot endpoint 要求 runner full-chain gate；browser 只验证 public
  sequence/link；browser 不能重算
  已隐去 `commandHash` 的 event hash。这里的 runner 声明固定为
  `required_by_snapshot_endpoint`，表示正式 endpoint 的成功响应必须经过该 gate，不是 browser 自己的证明；
- 固定 redaction policy，证明 observation 不展示 payload、request identity、actor、path/URI、model output、
  command hash 或 credential。

该值不序列化、不缓存、不写 runner、不跨 session 聚合，也不发送给第三方。

## 派生不变量

纯函数必须 fail closed：

1. 使用 snapshot 原顺序，不排序；event 非空且 `sequence === index + 1`。
2. Genesis `prevEventHash` 为 `null`，后续每项精确等于前一 `eventHash`。
3. Genesis 必须精确为 `agent.session_created: null -> created, stateVersion=1,
   planGeneration=0`；后续每项 `fromStatus` 必须精确等于前一项 `toStatus`，禁止用断裂的状态链伪造
   进入当前状态的时间。
4. 当前 runner 实际发出的 mutation event 必须匹配精确状态对，`stateVersion + 1`；只有 append-only
   `agent.approval_granted: awaiting_approval -> awaiting_approval` 保持版本不变。`plan_requested` 只允许
   generation `0 -> 1`，`replan_requested` 只允许从 `plan_failed | changes_requested | ready_to_run`
   进入 `planning` 且 generation `+1`，其他 event 保持 generation。
5. 尚未由当前 runner 实际发出的 `agent.draft_created` / `agent.draft_revised` 与未知 event 在本地
   observation v1 中明确拒绝；未来启用时必须先版本化其 event 语义，不能按 same-status 猜测。
6. Head 的 status/generation 与 session 一致；最大 event state version 与 session 一致。
7. 不要求 event count 等于 state version；一个 state version 可以对应多个事件。
8. `stateEnteredAt` 必须倒序找到首个
   `toStatus === session.status && fromStatus !== toStatus`；genesis `null -> created` 合法；找不到就拒绝，
   不得 fallback 到 same-status 事件。
9. timestamp 无法解析时返回 `invalid_timestamp`；client clock 回退时返回 `clock_regression`；两者 age
   都是 `null`。非负结果只能标记 `client_estimate`，不能叫 `ok`：browser 无法识别向前偏快的本地时钟，
   因而任何 age 都不得推断 timeout/stalled。
10. `replansUsed = max(0, planGeneration - 1)`，必须与 `agent.replan_requested` 精确计数一致且不得超过
   `maxReplans`；超预算 snapshot 必须拒绝，不能用 remaining clamp 掩盖。
11. 任何 counter 都只按稳定字段或精确 event type 计算，不读取 `event.payload`。
12. 所有派生失败只返回稳定错误码；错误消息不得拼入 snapshot、payload、actor、request、path 或 model
   output sentinel。

## Attention 映射

```text
created             -> plan_not_started
planning            -> planning_recovery_available
awaiting_approval   -> human_approval_required
plan_failed         -> plan_failed
changes_requested   -> typed_replan_required
ready_to_run        -> run_authorization_pending
cancelled           -> terminal
```

Observation 只说明下一关注点，不授权或执行 plan、replan、approval、compile、run、cancel、retry 或 resume。

## 预算边界

当前 ledger 可权威派生 replan 次数；因此显示 `used / maxReplans` 与 remaining 合法。

以下只有 limit，没有 usage fact，首版不得显示“已用 0”或“剩余全部”：

- `maxModelTurns`；
- `maxToolCalls`；
- `maxRetries`；
- `maxWallClockSeconds`；
- token、cost、cache token 或 provider retry。

未来 provider adapter 必须先产生 provider-neutral、脱敏、append-only usage event，再新增独立预算合同。
Client `Date.now()` 与 session 创建时间之差不是 authoritative wall-clock accounting。

## UI 范围

Workbench 只新增一个紧凑 observation panel，放在 event timeline 前，显示：

- 当前 status 与 attention；
- 明确标注为 client estimate 的当前状态持续时间，或精确时间异常；
- replans `used / limit`；
- event count、head sequence 与“snapshot endpoint requires full-chain validation”。

Hash 详情继续留在 timeline。首版不增加 dashboard、图表、跨 session 汇总、阈值告警、payload viewer 或
export settings。

## Integrity 与隐私

Remote runner 的 atomic snapshot endpoint 是完整链验证点。Browser 验证公开 sequence 与 prev-link，只能说明
正式 endpoint 要求该 gate，不能宣称自己重算了 event hash，也不能把普通 decoded fixture 冒充 browser
cryptographic proof。Observation 不接收或读取 event payload，也不重复 timeline 中的
actor/request/idempotency 字段。

OpenTelemetry GenAI 语义仍在 Development，且 input/output、system instruction、prompt variable 与 tool
definition 属 opt-in 内容。OpenAI Agents SDK 也明确提醒 generation/tool spans 可含敏感内容。因此本轮不接
exporter；未来 exporter 必须从版本化安全投影生成，默认不含内容。

## Regular-file capsule 的分层恢复条件

隔离的 dormant file-capsule proof 不需要等待完整 production publisher。它在以下四项冻结后可以恢复：

1. fixed exact-`bytes` chunk 或 native archive reader；
2. chunk/file size 上限；
3. proof-only final mode profile 与 exact file-capability syscall/state/error/identity contract：create-only strict
   `openat2` (`O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC` 与严格 resolve flags)；只有 resolver `EAGAIN`
   可有界重试；issued `EINTR` 必须进入 `namespace_outcome_unknown` 并烧毁 opaque name；成功 fd 立即
   adopt；`pwrite` 正数短写在同一 C 调用内推进 offset 并继续，zero 或 error（含 `EINTR`）才 poison
   且不由 Python 重放；`fchmod`/`fsync`/`close` 不重试；create/adopt 与单 chunk partial-write loop
   各自在一次 C 调用内完成。
4. sibling extension ABI/package 形状，以及 standard-GIL CPython 3.12、3.13、3.14 的 required Ubuntu
   完整行为矩阵。

File identity 必须覆盖 `S_ISREG`、FD_CLOEXEC、dev/ino/uid、与 parent 同 device、`nlink == 1`、
`st_size == next_offset/expected_size`、initial `fchmod(0600)` 与每个 leaf 的 pre/post reproof。Retained fd
不证明最终 pathname binding。File `fsync` 与同一 parent capsule 的 directory `fsync` 是两个 leaf；前者不
代表 namespace durable，后者继续由已有 directory leaf 或未来 orchestrator 负责，不属于 file owner。

Production materializer/authority wiring 仍必须等待另一层门槛：verified real payload replay/provenance；
opaque staging journal、orphan quota 与 fresh-session reconciliation；relocation 顺序及 pre/post evidence；完整
ACL/xattr/capability policy；trusted-root fresh reopen/walk 与真实 filesystem/mount/storage acceptance；受控
native artifact provenance/root issuance；receipt/marker-last publication。这些条件不阻止 disconnected proof，
但在全部满足前严禁 runtime consumer、publication、prepared 或 execution authority。

恢复后仍按 decision -> mechanical split -> behavior -> required Ubuntu evidence -> payload replay -> trusted-root/
receipt/marker -> production wiring 分阶段提交。不得因本 ADR 删除现有 native proof 或降低禁止 consumer 的门禁。

## 后果

正向：Agent-first 主界面获得立即可用的状态解释；无 shadow state；无外部 tracing 风险；未来 provider usage
与 exporter 有清晰插入点；activation 线避免过早锁死 byte-ingress API。

代价：首版不能提供 token/cost/tool-call dashboard，也不能自动判断 stuck；这些空白会被显式标成“没有权威
usage fact”，而不是用零值掩盖。

## 证明计划

1. 新增纯 `agent-session-observation.ts` 与完整 helper tests。
2. 新增小型 panel；只修改 `agent-workbench-page.tsx`，不扩大已有 798 行的
   `use-agent-workbench-state.ts`。
3. 覆盖七种 attention、approval same-status timing、invalid/clock regression、sequence/link/head mismatch、
   replan mismatch、隐私字段缺席。
4. 跑 frontend Python contracts、目标 Playwright helper spec、TypeScript/build 和 snapshot backend regression。
5. 用 `run.bat --web` 完成真实 browser smoke；若样式或 chunk 404，先重启完整 launcher。
6. behavior 与 UI evidence 各自精确 commit/push，并从目标远端回读 SHA。

未来恢复 native behavior 时，required Ubuntu job 必须在 standard-GIL CPython 3.12、3.13、3.14 每个 minor
运行完整行为矩阵，并执行 validator 与 `abi3audit --strict`；只 import abi3 wheel 不构成 behavior proof。

## 参考

- [完整深度研究与来源](../research/2026-07-18-agent-observation-before-file-capsule.md)
- [Agent-first control plane](2026-07-15-agent-first-control-plane.md)
- [Capsule-only directory leaves](2026-07-18-capsule-only-directory-leaf-primitives.md)
