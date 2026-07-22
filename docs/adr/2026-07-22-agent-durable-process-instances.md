# ADR：Agent durable process instance 与启动闸门

- 日期：2026-07-22
- 状态：Accepted；按独立提交逐步启用
- 扩展决策：[Agent 工作区证明与证据化恢复](2026-07-19-agent-workspace-proof-and-resume.md)

## 决策

Agent 控制面继续复用现有 WorkflowRun、Remote Runner、Snakemake 和 artifact lineage，
不引入新的拖拽 DAG 主交互，也不在当前阶段整体迁移到 Temporal 或 LangGraph。

每次实际 OS 进程启动必须拥有独立、持久化的 process instance。`dry_run` 与 `run`
是两个不同实例，不再把 `run_attempts.process_pid/process_group_id` 当作 Agent 路径的
恢复证据。旧字段暂时只服务普通 workflow；Agent 路径不得回退读取或镜像写入它们。

V21 首先增加严格的数据契约和迁移，但不开放 Agent resume。后续提交才依次接入：

1. `workspace proof + spawn intent event + prepared process instance` 原子写入；
2. gated launcher、PID/incarnation 持久化和一次性放行 token；
3. exit/termination/lost 终态、terminal checkpoint 和 reconciler；
4. proof-gated resume 与只读 resumability projection。

## 实施状态

- V21 已落地 immutable process instance 契约，仍未接入现有执行器；
- V22 在升级事务中逐行重建既有 workspace proof，并验证 `toolAssetsHash` 确由
  `workflow/**` 内容及必需的 `workflow/Snakefile` 服务端推导；校验失败时保持 V21，
  不重写或默许旧数据；升级还要求 exact V21 checksum 与完整 baseline schema；
- V22 将 retry-stable logical activity 提升为数据库唯一约束；一旦 process instance 建立，
  同一 run 的既有 v2 event chain 禁止更新或删除，raw SQL insert 也必须满足生产 envelope；
- runtime schema 在任何升级写入前拒绝 ledger 领先于 `user_version` 的伪回拨；current
  readiness 要求 v17-v22 历史连续且名称精确、v21/v22 checksum 精确，并拒绝未来 ledger；
  ledger table、列、索引与 trigger namespace 也必须精确，migration recorder 使用冲突即失败的
  `INSERT`，不会覆盖既有审计历史，也不会允许 trigger 在提交时篡改或追加版本；
- session 与 run authorization 的 V18/V19 table、列、索引、外键及 immutable trigger 均按
  canonical SQL 验证；同名弱 trigger、残缺的旧控制面和部分升级都会在事务内 fail closed；
- V18-V22 受管表要求 trigger 集合精确，current runtime 还要求全库 trigger namespace 精确；
  启动准备器在取得 `BEGIN IMMEDIATE` 写锁后再次执行完整 readiness，阻断首次连接检查与写事务
  之间的 DDL 竞态，也不允许额外 trigger 在 proof/event 写入时联动改变 authorization fence；
- Stage 9b 已提供尚未接线的原子启动准备器，仅接受 `dry_run/pre_dry_run`，在同一事务中
  写入 workspace proof、spawn intent event 与 prepared process instance；proof 来自当前
  attempt 持久化 workdir 的真实 sealed rescan，而不是调用方自报 manifest；pre-dry-run 根目录
  只能包含 `run-config.json` 与 `workflow/`，不会把额外可变配置排除在 proof 之外；
- 输入证据会在该事务中从 authorization、session goal、current runSpec 与 upload ledger
  重新推导，并精确复核唯一的 production materialization event；同时重新打开 canonical private
  input 路径，验证权限、链接数、文件身份、字节数与摘要，缺失或被替换时不产生任何启动写入；
- 数据库只持久化 gate token 的 domain-separated hash，原始 token 只返回调用方内存；读取
  process instance 时会重新验证输入 authority、关联 proof、spawn envelope 与完整 event chain；
- gated launcher、PID/incarnation、token 放行和 terminal checkpoint 仍属于 Stage 9c，当前
  Agent 路径继续保持 fail closed。

## 原因

当前一个 run attempt 会先后启动 Snakemake dry-run 与正式 run，但只有一个
`process_group_id` 槽位。正式 run 会覆盖 dry-run 身份，进程退出后该值也不会成为带
incarnation 的终态证据。Worker 若在 `Popen` 与 started callback 之间崩溃，数据库无法判断
科学进程是否已真正开始；盲目重试会把 at-least-once 执行误当成 exactly-once。

Temporal 将 Event History 作为 append-only 恢复依据，同时明确 Activity 可能实际执行多次，
因此副作用必须幂等。LangGraph 同样只在 step/task 边界 checkpoint，未持久完成的 task 在恢复时
可能重跑。OpenAI Agents SDK 的长期 HITL 状态也要求连同 agent/SDK 定义版本持久化。
H2OMeta 采用这些 durable semantics，不复制它们的框架依赖或确定性 replay 模型。

## Process instance contract

一个 immutable launch intent 至少绑定：

- run、Agent authorization、run attempt、lease generation；
- retry-stable logical activity 与本 attempt 内的 process ordinal；
- `dry_run -> pre_dry_run proof`、`run -> pre_run proof`；
- 服务端推导的 tool asset hash；
- path-free launch spec hash；
- 一次性 gate token hash；
- hash-chained spawn-intent run event；
- content-addressed process instance ID 与 launch intent hash。

实例从 `prepared` 开始，只允许以下 CAS 状态迁移：

```text
prepared -> started | spawn_failed
started  -> exited | terminated | lost
```

Identity、proof、launch hashes 与 prepared timestamp 永久不可修改，记录不可删除。
`exited` 只表示父进程实际 reap 并观察到 exit code；`terminated` 表示 reconciler 依据准确
incarnation 确认停止；`lost` 表示已启动但没有可信 exit observation。后两者都不能冒充成功。

## 启动闸门

只记录 `prepared` intent 仍不能关闭 `Popen` 崩溃窗口。Agent 路径最终必须启动一个极小的
H2OMeta launcher helper，而不是直接启动 Snakemake：

1. 父进程原子提交 workspace proof、spawn event 与 prepared instance；
2. helper 启动后在继承 pipe 上阻塞，尚未 `exec` 科学命令；
3. 父进程捕获 PID、process group 与 incarnation，提交 `started` event/CAS；
4. 再次验证 authorization、lease、proof 和 cancellation；
5. 父进程发送一次性 token，helper 校验后 `execve` Snakemake。

父进程在放行前崩溃时 pipe EOF，helper 必须退出，科学命令不会运行。放行后崩溃时，持久化
incarnation 已足够让 reconciler 精确终止或标记 `lost`，但不得自动创建新实例。

Stage 9c 接线前必须把 `launch_spec_hash` 改为服务端从 canonical argv、cwd、环境白名单、runtime
版本与 tool asset binding 推导，不能接受调用方提供的任意 64 位十六进制值。启动 token 的消费
必须与 `started` CAS、完整 event envelope/chain 校验和再次 authorization/lease/cancel 检查绑定；
仅凭 raw SQL 写入 process event 不构成已获授权的命令放行。

## 恢复规则

- 只有 prepared intent：`launch_unknown`，禁止盲目重启；
- started 且无 terminal：先 reconcile/kill/reap，禁止新 attempt；
- exited 且 exit code 为 0：仍须 terminal workspace proof 和 artifact/output checks；
- spawn_failed、terminated、lost：不得视为成功或安全 checkpoint；
- source terminal proof 不是链头、存在开放进程、incarnation 不可验证或版本漂移时全部 fail closed；
- tracing、LLM conversation、background response ID 和 stdout 日志都不能替代本地执行账本。

## 非目标

- 不恢复 DAG 拖拽编辑器为主产品界面；
- 不 replay LLM、Python 调用栈或 Snakemake 进程内存；
- 不宣称外部副作用 exactly-once；
- 不把每行 stdout 写入事件历史；日志仍进入 log/blob/artifact；
- 不在 V21 schema 提交中移除现有 Agent resume blanket gate。

## 参考

- [Temporal Event History](https://docs.temporal.io/workflow-execution/event)
- [Temporal Activity idempotency](https://docs.temporal.io/activity-definition)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [OpenAI Agents SDK human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)
