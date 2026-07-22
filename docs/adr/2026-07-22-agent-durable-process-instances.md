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
  readiness 要求 v17-v23 历史连续且名称精确、v21/v22/v23 checksum 精确，并拒绝未来 ledger；
  ledger table、列、索引与 trigger namespace 也必须精确，migration recorder 使用冲突即失败的
  `INSERT`，不会覆盖既有审计历史，也不会允许 trigger 在提交时篡改或追加版本；
- session 与 run authorization 的 V18/V19 table、列、索引、外键及 immutable trigger 均按
  canonical SQL 验证；同名弱 trigger、残缺的旧控制面和部分升级都会在事务内 fail closed；
- V18-V23 受管表要求 trigger 集合精确，current runtime 还要求全库 trigger namespace 精确；
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
  process instance 时会重新验证 launch intent、spawn envelope 与完整 event chain；`started` writer
  还会重新验证当前输入 authority、关联 proof、lease、取消状态与事件链；
- Stage 9c1 增加尚未接执行器的 V23 lifecycle foundation：服务端绑定的 canonical launch spec、
  Linux/Windows incarnation contract、`prepared -> started|spawn_failed -> terminal` CAS/read model，
  以及 exact schema/readiness。V23 升级拒绝任何既有非 `prepared` process row，不为未受验证的
  历史 started/terminal 状态背书；
- run-event.v2 的 `prev_event_hash` 始终指向同一 run 的紧邻全局事件；process payload 另以
  `priorProcessEventId/Hash` 绑定 spawn intent 到 started/spawn_failed、started 到 terminal。
  因此其他 run event 可以穿插，全局审计链与单进程状态链都不会断裂；event append 与 row CAS
  位于同一 savepoint，exact replay 是只读结果；
- Stage 9c1 的 launch spec 在内存中精确绑定 argv、resolved cwd、完整且 canonical 排序的 child
  environment、stdio/session/helper/runtime identity 与服务端 proof；Windows 环境名按 case-fold
  去重。argv、cwd、环境值和可执行路径不进入 DB/event，持久层只保留由一次性内存 key 计算的
  domain-separated digest；
- Stage 9c1 只提供事务后放行契约：connection-scoped CAS 结果不构成放行凭据，commit-owning
  wrapper 只有在 `started` 提交成功且确为首次迁移后，才至多调用一次 gate-release callback；
- Stage 9c2 才能接入执行器：必须由服务端 resolver 从已验证 runtime/artifact、run spec 与环境策略
  构建命令，并复核 helper/runtime 的实际磁盘 digest；当前调用方给出的 path/hash 不能被视为
  production authority。Stage 9c2 还必须实现跨平台 gated launcher 与 SQLite 安全门；
- Stage 9c3 才增加 incarnation-aware reconciler、terminal evidence 与 prepared-crash 回收。当前
  worker 与 executor 都以稳定的 `durable_process_launcher` gate 阻断 Agent-owned run，不能因为
  V23 已存在就称为可启动、可暂停恢复或 exactly-once。

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

只记录 `prepared` intent 仍不能关闭创建进程与数据库提交之间的崩溃窗口。Agent 路径不能直接
调用普通 `Popen` 启动 Snakemake；Stage 9c2 必须实现以下平台专用协议：

- Windows：`CreateProcessW(CREATE_SUSPENDED)` 创建主线程仍暂停的进程，将进程加入
  kill-on-close Job Object，并在仍持有 live process handle 时用 `GetProcessTimes` 捕获
  `(pid, creationTimeFiletime)`；`started` 提交成功后才 `ResumeThread`。FILETIME 以无前导零的
  uint64 十进制字符串进入 canonical JSON，避免跨语言 JSON 安全整数失真；
- Linux：极小的 `posix_gate_helper` 在 inherited pipe 上阻塞，创建新 session/process group，
  捕获 `(bootId, pid, procStartTicks)`；pidfd 用于无 PID-reuse 竞态的在线观察与终止。只有
  `started` 提交成功后父进程才写入放行 frame，helper 随后 `execve` 精确命令；
- 两个平台都必须先原子提交 workspace proof、spawn event 与 prepared instance；启动后再次验证
  authorization、lease、proof、input materialization、event chain 与 cancellation，再提交 started。

父进程在放行前崩溃时，Linux helper 必须因 pipe EOF 退出；Windows suspended process 必须由
Job Object/controller 清理，科学命令不得开始。放行后崩溃时只能依据精确 incarnation 做 reconcile，
不得自动创建新实例。普通 PID、日志或“进程名看起来相同”都不是恢复证据。

服务端 command resolver 是 Stage 9c2 的启用前置条件：它从已验证 runtime proof、artifact manifest、
不可变 run spec、workspace proof 与明确环境策略构建 canonical argv/cwd/完整 child environment，
并对 helper/runtime 文件做稳定读取与 digest 比对。把调用方自报的 path/hash 与服务端 proof 放在
同一个 JSON 中并不能建立信任关系，因此 9c1 recorder 仍不得接到 production executor。

## SQLite 安全门

SQLite 官方披露的 WAL-reset bug 影响 3.7.0 到 3.51.2，并在 3.51.3 修复。Stage 9c1 因未接
production launcher 不以本机 SQLite 版本作为可运行证明；Stage 9c2 必须在构建、artifact preflight、
runner startup/readiness、install/reuse、activation 与 rollback 全路径对 `<3.51.3` fail closed。

当前 remote-runner 0.1.5 artifact lock 中的 libsqlite 3.53.0 只能证明该 artifact 内容满足版本下限，
不能替代目标机实际加载库的运行时检查。接线必须发布新 artifact version，并让安全门结果进入可审计
readiness/activation evidence；未知版本、解析失败或回滚到不安全 artifact 都必须拒绝启动。

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
- 不宣称 SQLite commit 与 OS process release 原子，也不宣称进程或外部副作用 exactly-once；
- Stage 9c1 只保证 durable authorization 与每个 prepared instance 至多一次 gate-release attempt；
- 不把每行 stdout 写入事件历史；日志仍进入 log/blob/artifact；
- 不在 V21 schema 提交中移除现有 Agent resume blanket gate。

## 参考

- [Temporal Event History](https://docs.temporal.io/workflow-execution/event)
- [Temporal Activity idempotency](https://docs.temporal.io/activity-definition)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [OpenAI Agents SDK human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [SQLite WAL-reset bug](https://sqlite.org/wal.html#the_wal_reset_bug)
- [Microsoft CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
- [Microsoft GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Linux pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
- [Linux `/proc/<pid>/stat`](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)
