# H2OMeta Next-Phase Roadmap

> 核心判断：Remote Agent 发布机制已成熟，但任务执行控制面仍需完成产物发布、
> crash recovery 和端到端验收闭环。下一阶段目标是先形成可证明可靠的单任务系统，
> 再升级为可恢复、可观测、受控并发的工作流平台。

## 实施顺序

```
1. 收尾 Active reconciler、Candidate adoption 和 E2E   (P0)
2. 建立调度准入、Destination/Queue 和 Worker Slot 模型  (P0)
3. 加固 SQLite 并发基础，保持执行并发为 1               (P0)
4. 接入并发所需的最低日志、指标和 readiness             (P0)
5. 启用并验收 2 个并发槽位，再评估扩到 4                (P0)
6. 完成结构化日志、指标和 diagnostics                   (P1)
7. 接入 Apptainer software deployment method          (P1)
8. 接入官方 Snakemake Slurm executor plugin/profile    (P1)
9. 修复并验收单用户 Docker Compose 草案                (P1, 暂缓)
10. 多用户认证、Postgres、对象存储                      (P2)
11. 有明确规模需求后再考虑 Kubernetes                   (P2)
```

当前主线不以 Docker 交付为目标。先完成任务执行、恢复、并发和可观测性闭环，
再回到平台容器化。Docker 文件保留为实验性草案，不作为当前可部署版本发布。

---

## P0-1: Active Reconciler + Worker Crash Recovery

### 状态

- 已完成，真实可靠性 Gate 已通过（2026-06-13）。
- Worker supervisor 在领取新任务前运行 active reconciler。
- 过期 lease 会 fence 旧 attempt、终止旧进程树，并根据重试次数 requeue 或 dead-letter。
- 旧 Shadow Reconciler 测试和兼容函数均已删除。
- Candidate output 已接入真实 executor 产物发布链，adopt 会在事务内复核
  active lease、size/hash，并原子写入 artifact、ledger、lineage 和 run completion。
- attempt 输出已隔离到 `results/attempts/<attempt_id>/generation-<n>`，日志文件也包含 attempt id。
- claim 路径不再直接接管过期 lease；必须由 reconciler 先完成 fence 和终止确认。
- fence 事务、进程终止和 requeue/dead-letter 已拆成独立阶段，终止期间不持有 SQLite 写事务。
- 历史 staging 库中的重复 adopted output edge 已通过幂等迁移修复：保留最早 output edge，
  后续重复 edge 改写为稳定 `#legacy-<edge_id>` port name，再创建 partial unique index。
- 真实 staging deploy 和 worker SIGKILL acceptance 已通过：
  - artifact digest: `66bf1325db10c5907e26fb0cf5b18d4a88f96518e77f588696d75e720b5ea9fc`
  - staging deploy: release `/home/zyserver/.h2ometa/runner/releases/0.1.1-control-plane`,
    bindPort `38903`, pid `2923846`
  - canonical Gate: `python skills/h2ometa-remote-smoke-test/scripts/remote_worker_crash_recovery_acceptance.py --allow-runner-kill`
  - Gate run: `run_worker_crash_750e708d7905`
  - old attempt `att_1b9f3a646869` fenced after SIGKILL of pid `2923934`
  - new attempt `att_50e0b825daea` completed on pid `2924481`
  - lease generations `[1, 2]`, artifact count `3`, lineage count `3`,
    fence event count `1`, requeue event count `1`
  - result: `RESULT: ok`

### 最终评分

- 迁移安全：9/10
- 恢复语义：9/10
- 验收证据：9/10
- 平台完成度：8.5/10

### 目标

使用主动恢复控制环处理 Worker crash 和过期 lease。

### 具体工作

1. **过期 lease fencing**：检测到过期 lease 后，将对应 attempt 标记为 fenced，阻止其后续发布结果。
2. **终止旧 attempt 进程组**：使用 `_process_group_recorder` 记录的 PGID，向旧进程组发送 SIGTERM/SIGKILL。
3. **可重试任务重新入队**：检查 attempt 的 retry_count，未超限则重置 lease 并回到 queued 状态。
4. **重试超限 → dead-letter**：超过 max_retries 的任务进入 `dead_letter` 状态，附带失败原因。
5. **Candidate output 验证后 adopt**：executor 先登记 candidate，再校验完整性和
   checksum，验证通过后原子 adopt；禁止旧 attempt 直接发布正式 artifact。
6. **幂等性**：所有 reconciliation 操作必须幂等，重复执行不产生副作用。
7. **Attempt 隔离**：候选输出写入 attempt 专属 staging/result 目录，正式 adopt
   前不进入 run 级可见结果目录。
8. **终止确认后恢复**：先提交 fence，再在事务外发送 SIGTERM，超时后 SIGKILL；
   只有终止成功或明确确认进程不存在后才 requeue。

### 验收标准

- 运行中强杀 worker 进程，重启后任务能恢复或明确失败。
- 同一输出只被采用一次（通过 attempt_id + lease_generation 双重校验）。
- Reconciler 自身可重复运行，不产生重复事件。
- 真实 executor 使用 candidate → verify → adopt 链路，不再直接发布正式 artifact。
- Candidate 唯一键包含 `run_id + attempt_id + lease_generation + output_key`。
- Adopt 时重新读取文件计算 size/hash，并在单一事务中重新验证 active lease，
  写入 artifact、lineage、adopt 状态和 run completion。
- `(run_id, output_key)` 只能存在一个正式采用结果，重放不会产生部分或重复 artifact。
- 真实启动 worker、强杀进程并重启，验证旧进程停止、generation 增加且只采用一次输出。
- 确认无生产调用后删除 `run_shadow_reconciler_once()`。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `apps/remote_runner/reconciler.py` | 主动恢复控制环 |
| `apps/remote_runner/reconciler_actions.py` | fencing、进程终止、requeue、dead-letter |
| `apps/remote_runner/worker_supervisor.py` | 每轮领取前运行 active reconciler |
| `tests/test_reconciler_active.py` | 恢复控制环测试 |
| `tests/test_reconciler_actions.py` | 平台进程终止测试 |

### 验证命令

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/bio_ui_codex_uv_venv_pytest
export UV_CACHE_DIR=/tmp/bio_ui_codex_uv_cache
unset UV_PYTHON
export UV_PYTHON_INSTALL_DIR=/tmp/bio_ui_codex_uv_python
uv run pytest tests/test_reconciler_active.py tests/test_reconciler_actions.py tests/test_remote_runner_run_worker_supervisor.py -v
```

---

## P0-2: 完整 UI 端到端验收

### 状态

- Windows 本地核心 UI Gate 已通过（2026-06-14）：18 passed、0 failed、0 skipped。
- 核心 Playwright suite 现在自行创建前置数据：要求 ready runner、`file-summary-v1`
  workflow、WorkflowReady tool；缺失时用 `P0_2_*` 错误显式失败，不再跳过。
- Draft plan/compile 必须成功并生成 `workflowRevisionId`，再提交并完成对应
  WorkflowRevision run；详情页展示 WorkflowRevision，产物页展示 artifact id。
- artifact 验收覆盖 API preview、UI artifact card、`sha256` 和 `storageUri`。
  本地 remote-runner 查询层已补充 `fetch_run_results().lineageEdges` 单测断言。
- 远端 runner HTTP 合约新增字段（例如 run results 的 `lineageEdges`）只有在连接的
  remote runner 重建/部署到对应源码后，才能加入 live Playwright 硬断言。
- 当前本地核心 suite 的断线恢复是 polling-gap 持久性检查，不等同于真实 worker
  停启恢复；真实 worker-restart 仍属于独立远端 Gate。

### 目标

新增 Playwright 端到端测试，覆盖完整用户工作流。

### 具体工作

1. **核心流程**：连接 → 保存 Draft → Validate → Compile WorkflowRevision → 上传输入 → Submit → 查看事件和日志 → 预览产物 → 验证 lineage。
2. **幂等性**：重复提交不产生重复运行。
3. **取消**：运行中可取消任务。
4. **断线恢复**：Agent 暂时断线后能恢复连接并继续。
5. **WorkflowRevision 可见性**：运行详情和结果页面展示 WorkflowRevision 信息。

### 验收标准

- Playwright 核心验收在干净状态下达到 0 failed、0 skipped。
- 测试失败时输出截图和 trace 供调试。
- Draft plan/compile 必须返回成功并生成 revision；同一 fixture 创建、提交并验证
  该 revision 对应的 run、artifact 和 UI；lineage 在本地 storage/query 层有硬断言，
  远端 HTTP 字段待 runner 重部署后纳入 live E2E。
- 取消请求必须记录 command 和事件，并能从详情链路查询到对应 command。
- 断线恢复核心 suite 仅验证轮询间隔后的 run detail/event 持久性；真实停止并重启
  worker 的恢复验收必须作为独立远端 Gate 运行。
- 核心 suite 与需要真实集群/外部环境的 optional suite 分离。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `tests/e2e/api-helpers.ts` | 自建 E2E fixture、WorkflowRevision draft/compile/submit helper |
| `tests/e2e/workflow-lifecycle.spec.ts` | 核心生命周期、artifact、WorkflowRevision UI Gate |
| `tests/e2e/idempotency-and-cancel.spec.ts` | 幂等、取消 command/event、polling-gap 持久性 |
| `apps/web/app/components/workflows-page-model.ts` | WorkflowRevision、event command、artifact metadata 模型 |
| `apps/web/app/components/workflow-run-detail-panel.tsx` | WorkflowRevision、artifact id、cancel command 可见性 |
| `apps/remote_runner/execution_query_storage.py` | run results 暴露 lineage edges |
| `tests/test_candidate_output_storage.py` | 本地 lineage results 查询回归 |

---

## P0-3A: 调度准入与并发基础层

### 状态

- 本地核心控制面 Gate 已通过（2026-06-14）：P0-3A 聚焦/回归 pytest
  84 passed，P0-2 Playwright 核心回归 18 passed、0 skipped。
- `runSpec.execution.queueName` 进入严格 API/request model；提交时写入
  `run_jobs.queue_name`，worker claim 只领取自身 queue。
- claim 前先做 admission：slot/resource 不可用时任务保持 queued，记录
  `wait_reason_json`，不创建 attempt 或 lease。
- attempt/lease 记录 `session_id` 和 `slot_id`；资源分配写入
  `run_resource_allocations`，completion 和 fence 路径都会幂等释放。
- worker slot 状态进入 `run_worker_slots`；slot 心跳使用
  `(worker_id, session_id, slot_id)` fencing，旧 session 不能覆盖新进程。
- supervisor 已拆出单独 reconciler controller；slot loop 不再各自运行 reconciler。
- SQLite 连接启用 WAL 和 `busy_timeout`，并有启动迁移覆盖新增列/表。
- P0-3A 仍保持生产单槽：默认 ResourcePool 为 1，supervisor 默认拒绝
  `concurrency_limit > 1`，多槽真实启用留到 P0-3B。

### 目标

在保持真实执行并发为 1 的情况下，先建立可证明正确的调度、准入和状态模型。

### 具体工作

1. **独立执行路由契约**：`runSpec.execution.queueName` 表示执行队列；
   不复用表示参考数据库绑定的 `resourceBindings`。
2. **Destination/Queue 路由**：运行提交时解析 execution destination 和 queue；
   worker 只领取其声明 queue 的任务。
3. **资源准入后再 claim**：只有可用 slot 和资源满足时，才创建 attempt/lease；
   资源不足的任务保持 queued，并记录等待原因。
   资源 reservation 必须持久化，或明确整个数据库只有一个调度所有者并证明
   crash 后可以从 attempt/slot 状态重建 allocation。
4. **Worker Slot 状态**：一个 supervisor/controller 管理多个独立 `slot_id`；
   每个 slot 维护独立 attempt、状态和心跳，worker 汇总 active slot 数。所有
   slot 更新使用 `(worker_id, session_id, slot_id)` fencing，旧 session 不得覆盖新进程。
5. **单 Reconciler Controller**：reconciler 由 supervisor 的独立控制循环运行，
   不随 slot 数量重复执行。fence 使用短事务提交，进程终止在事务外完成，再以
   新短事务记录 termination 和 requeue/dead-letter 结果。
6. **SQLite 并发基础**：启动时完成 schema migration；配置 WAL、busy timeout；
   保持短写事务，并增加并发写和恢复测试。盘点所有 `state_version`、event sequence
   和 hash-chain 写路径，使用 CAS 或 `BEGIN IMMEDIATE` 防止丢失更新和链分叉。
7. **ResourcePool 幂等性**：重复 acquire/release 不改变 semaphore 容量；资源分配
   绑定 attempt/slot，并能在 crash recovery 后回收。
8. **单并发硬 Gate**：P0-3A 完成前，配置、supervisor 和 ResourcePool 三层都必须
   拒绝超过 1 个 active slot，不能仅依赖默认参数。

### 验收标准

- 不同 queue 的 worker 不会领取其他 queue 的任务。已覆盖。
- 资源/slot 不足时任务保持 queued，不创建 attempt 或 lease，并写入 wait reason。
  已覆盖。
- claim 成功会持久化 allocation；completion 和 fence 路径会幂等释放。已覆盖。
- slot 状态不会因其他 slot 或旧 session heartbeat 被覆盖。已覆盖。
- supervisor 中 reconciler 由独立 controller 运行，不在 slot loop 中重复运行。已实现。
- SQLite 连接启用 WAL 和 `busy_timeout`。已覆盖。
- 并发仍固定为 1 时，现有生命周期与 E2E 行为无回归。已覆盖。
- 真实 2 槽并发、并发压力下 event hash-chain 验证、远端多任务 acceptance 留到 P0-3B。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `apps/api/models.py` | Local API 允许 `runSpec.execution` |
| `apps/remote_runner/api_models.py` | Remote runner API 允许 `runSpec.execution` |
| `apps/remote_runner/admission_storage.py` | Admission wait reason、allocation ledger、slot 状态 helper |
| `apps/remote_runner/run_execution_storage.py` | Queue 过滤与 admission-aware claim |
| `apps/remote_runner/run_worker_storage.py` | Worker/slot 状态模型 |
| `apps/remote_runner/worker_supervisor.py` | 单 controller + 独立 slots |
| `apps/remote_runner/resource_pool.py` | 幂等资源分配与恢复 |
| `apps/remote_runner/storage_core.py` | WAL、busy timeout、migration 边界 |
| `apps/remote_runner/storage_schema.py` | run worker slot 与 allocation schema |
| `tests/test_remote_runner_run_execution_storage.py` | Queue/admission/allocation/WAL 验收 |
| `tests/test_remote_runner_run_worker_storage.py` | session/slot fencing 验收 |

---

## P0-3B: 受控并发启用

### 状态

- 受控 2-slot 验收已通过，生产默认仍保持单槽位。
- 真实远端 Snakemake 2-slot acceptance 已证明两个任务并发运行、取消隔离、
  resource-wait 不提前创建 attempt/lease，且验收后恢复单槽默认。
- Worker crash/restart acceptance 仍作为 destructive gate，与 2-slot gate 共同组成
  execution control-plane runtime release gate：
  `uv run python scripts\remote_runner_release_gate.py --allow-two-slot --allow-runner-kill`。
- 3-4 槽位仍未默认启用；需要真实吞吐或等待时间证据后再评估。

### 目标

先启用并验证 2 个并发槽位；有真实吞吐或等待时间证据后再决定是否默认扩到 4。

### 具体工作

1. 通过配置显式设置 worker slot 数、总 CPU、内存、临时磁盘和 GPU。
2. 每个 attempt 使用独立工作目录、日志和进程组。
3. H2OMeta 管理 workflow 级 admission；Snakemake 继续管理单个 workflow DAG
   内部的 rule 资源与并行度。
4. 增加并行运行、独立取消、worker crash、资源不足和重启恢复测试。

### 验收标准

- 两个真实任务可同时运行，并记录各自 slot 和资源分配。
- 取消一个任务不会终止或污染另一个任务。
- worker crash 后不会重复发布结果或泄漏资源分配。
- 指标可观察 queued、admitted、running、resource-wait 和 completed 状态。
- 2 槽位稳定验收后，才允许配置 3-4 槽位。

---

## P1-1: 结构化日志、指标和 Diagnostics

### 状态

- 进行中。
- JSON formatter、指标容器、健康信息和 diagnostics 脚本已创建。
- P0-3C 最小执行诊断切片已接入：`/health/execution-diagnostics`
  汇总 queue metrics、worker/slot health、SQLite WAL/busy timeout、active lease、
  allocation、resource-wait、recent events 和不变量；runtime release gate 可写
  `release-gate-evidence.json`。
- `configure_structured_logging()` 已接入 Local API 和 Remote Runner 启动入口，
  并禁用 Uvicorn 默认 `log_config`，避免启动时覆盖 JSON formatter。
- completed、failed/dead-letter、lease expiry、worker heartbeat、queue wait 和
  run duration 的最小真实事件点已接入指标容器。
- Local API readiness 仍需加入队列深度、磁盘余量和 worker 状态阈值。
- 并发启用前先完成最小集：slot/attempt 状态、资源等待、lease expiry、
  SQLite busy、运行成功/失败和 worker heartbeat 指标。

### 目标

建立全链路可观测性基础。

### 具体工作

1. **JSON 结构化日志**：统一 log format，包含 timestamp、level、component、message。
2. **全链路 ID**：携带 `requestId`、`commandId`、`runId`、`attemptId`、
   `slotId`、`correlationId`；字段命名尽量兼容 OpenTelemetry semantic conventions。
3. **指标**：队列长度、等待时间、运行时长、失败率、lease 过期数、worker heartbeat、磁盘空间。
4. **`/health/ready` 增强**：纳入 worker 状态、队列状态和磁盘余量。
5. **`service-info` 增强**：返回真实运行计数和队列深度。
6. **Diagnostics bundle**：一键导出，过滤 token、SSH 密码和路径敏感信息。

### 验收标准

- API 和 Remote Runner 启动后默认输出可解析 JSON 日志。
- 一次完整运行能产生 requestId、runId、attemptId 关联日志。
- 成功、失败、取消、lease expiry 和 worker heartbeat 会更新真实指标。
- readiness 在磁盘不足、worker 不可用或队列异常时返回 degraded/not-ready。
- diagnostics 自动化测试证明 token、密码、私钥路径和认证头不会泄露。
- `/health/ready` 未通过时返回 HTTP 503，submission admission 复用同一判定。
- readiness 覆盖 stale worker、SQLite busy、磁盘阈值、指标采集失败和最老任务
  等待超阈值；不能只依据 queue depth 是否为零。
- Diagnostics 对完整序列化 bundle 注入 canary，扫描凭据 URI、认证头、token、
  私钥路径和异常/日志文本；文档声称收集 recent logs 时必须真实包含脱敏日志。
- `runId/attemptId/slotId` 进入日志上下文，不作为高基数指标 label。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `core/logging_config.py` | 新增或重构 |
| `apps/api/system_service.py` | 增强 |
| `apps/remote_runner/metrics.py` | 新增 |
| `scripts/collect_diagnostics.py` | 新增 |

---

## P1-2: 任务级运行环境适配器

### 状态

- 进行中。
- Native、Conda、Apptainer adapter 及 environment lock 数据结构已创建。
- 当前 adapter 尚未接入 Snakemake 实际命令构建和运行链。
- Slurm profile/plugin 尚未接入。

### 目标

建立统一的 execution environment contract，支持多种运行环境。

### 环境优先级

```
native → conda → apptainer → docker（可选）
```

### 具体工作

1. 保留现有锁定 Conda 环境作为默认。
2. 通过 Snakemake `software-deployment-method: apptainer` 接入容器执行，
   H2OMeta adapter 负责配置、检查、lock 和 provenance，不包裹整个
   Snakemake controller 进程。
3. 每个 ToolRevision/WorkflowRevision 记录镜像 digest 或 environment lock。
4. Docker 只作为支持 Docker 的计算节点选项，不作为 Remote Agent 硬依赖。
5. 使用官方 `snakemake-executor-plugin-slurm` 和 profile；H2OMeta 负责
   destination 选择、依赖检查、profile 管理和状态/错误归一化，不自行重写
   `sbatch`、`squeue`、`sacct`、`scancel` 调度实现。
6. 不急着做 Kubernetes。
7. 拆分 compute destination/global profile（`--profile`）与 revision-specific
   workflow profile（`--workflow-profile`），避免 executor、jobs 和 rule resources 混层。
8. 将 Slurm executor/storage plugin 的版本、摘要和 import/readiness 检查纳入
   受控 workflow runtime artifact。

### 验收标准

- Apptainer 通过 Snakemake software deployment method 进入真实执行命令。
- 运行记录保存镜像 digest/environment lock，并能在结果详情中追溯。
- Slurm profile 可通过官方 plugin 完成 submit、status 和 cancel，H2OMeta
  能归一化插件返回的 job ID、状态和失败原因。
- 同一 workflow 可通过 profile 在 local 与 Slurm 之间切换。
- 在 Slurm pilot 前明确并验证 shared filesystem 或 Snakemake storage plugin
  策略，包括绝对路径、UID/GID、权限、原子 rename、stage-in/out 和 image cache。
- attempt 持久化远端 Slurm job identity；live cancel 和 controller crash recovery
  均能取消或清理残留 jobs，完成 stage-out 后才能 candidate adopt。
- 先完成 local executor + rule-level Apptainer，再进入单一 shared-FS Slurm 集群 pilot。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `apps/remote_runner/env_adapters/` | 新增目录 |
| `apps/remote_runner/env_adapters/base.py` | 新增：抽象接口 |
| `apps/remote_runner/env_adapters/conda.py` | 新增：现有逻辑提取 |
| `apps/remote_runner/env_adapters/apptainer.py` | 新增 |

---

## P1-3: 明确产品模式与单用户 Docker Compose

### 状态

- 实验性草案，暂停作为交付目标。
- 三种部署模式已正式定义并实现配置管理（`core/deployment_mode.py`）。
- Docker Compose 配置已创建，Web 使用 nginx 服务静态导出，API 使用 uvicorn。
- 部署模式已集成到 `service-info` API 响应中。
- 安全验证函数已创建，但尚未接入 API 启动阻断。
- 完整部署文档已编写（`docs/deployment-modes.md`）。
- API 镜像 Python 版本、静态 Web API 地址和端口绑定仍有阻断问题。
- 完成 P0-3、P1-1、P1-2 后再恢复此项。

### 目标

把 H2OMeta 从"隐式单用户桌面应用"升级为"显式多模式产品"，为后续多用户版本奠定基础。

### 三种产品模式

| 模式 | 部署方式 | 认证 | 凭据存储 | 网络暴露 |
|------|----------|------|----------|----------|
| `desktop` | 本地安装 | 无（单用户） | OS keyring | 仅 localhost |
| `server-single-user` | Docker Compose | 无或简单 token | 环境变量 | 仅内网 |
| `server-multi-user` | Docker Compose / K8s | 登录 + RBAC | 加密数据库 | 可公网 |

### 具体工作

1. ✅ 正式定义三种模式的配置入口和边界（`core/deployment_mode.py`）。
2. 🟡 Docker Compose 版本明确标记为"单用户可信内网部署"，尚未完成镜像验收。
3. 🟡 已提供网络安全验证函数，尚未接入启动阻断和默认 localhost 端口绑定。
4. ✅ 部署模式集成到 API `service-info` 响应。
5. ✅ 完整部署文档和反向代理配置示例。

### 恢复条件

- `Dockerfile.api` Python 版本与 `pyproject.toml` 一致。
- Web 镜像使用同源 `/api`，或在构建阶段正确注入浏览器可访问的 API 地址。
- Compose 默认仅发布到 `127.0.0.1`，公网暴露必须显式选择并通过安全校验。
- Docker Desktop/Linux daemon 环境完成 build、up、health、UI E2E 和持久化验收。
- 增加非 root 用户、secret 挂载、资源限制和最小权限配置。

### 涉及文件

| 文件 | 变更类型 |
|------|----------|
| `core/deployment_mode.py` | 新增：部署模式配置管理 |
| `Dockerfile.api` | 新增：API 容器镜像 |
| `Dockerfile.web` | 新增：Web 容器镜像（nginx 静态服务） |
| `docker-compose.yml` | 新增：单用户服务器编排 |
| `.env.example` | 新增：环境变量模板 |
| `.dockerignore` | 新增：Docker 构建排除规则 |
| `docs/deployment-modes.md` | 新增：部署模式完整文档 |
| `apps/api/system_service.py` | 修改：集成部署模式到 service-info |
| `tests/test_deployment_mode.py` | 新增：部署模式测试（15 个） |

---

## P2: 产物生命周期

### 现状

- `artifact_storage.py`（242 行）schema 支持 `storage_backend/storage_uri`，但实现只有本地文件系统。
- 没有 GC、配额或校验和复核。

### 具体工作

1. 产物保留策略和磁盘配额。
2. 引用计数或基于 lineage 的安全 GC。
3. 校验和后台复核。
4. 导出运行证据包。
5. 后续增加 S3/MinIO adapter，不作为当前必需依赖。

---

## 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-06-12 | 不先扩 Docker | 执行并发与调度是当前最明显的能力瓶颈 |
| 2026-06-12 | Reconciler 优先于并发 | 先保证单任务可靠恢复，再开放并发 |
| 2026-06-12 | Playwright 先于并发 | 有了端到端验收才能安全验证并发改动 |
| 2026-06-12 | 不急着做 Kubernetes | 没有明确规模需求，Slurm 优先于 K8s |
| 2026-06-12 | Docker 不作为硬依赖 | HPC 场景优先 Apptainer |
| 2026-06-13 | Web 容器使用 nginx 而非 Node.js | Next.js 已配置 `output: "export"` 静态导出，nginx 更轻量高效 |
| 2026-06-13 | 单用户模式不强制认证 | 保持与 desktop 模式一致的无认证体验，安全边界由网络层保证 |
| 2026-06-13 | 部署模式通过环境变量配置 | 与 Docker Compose 和 12-Factor App 原则一致，避免配置文件管理复杂度 |
| 2026-06-13 | Docker Compose 暂缓交付 | 先完成任务并发、可观测性和 HPC 执行契约，再验收部署封装 |
| 2026-06-13 | 并发先做 admission 和 slot 模型 | 避免任务已领取却等待资源，以及多线程覆盖 worker 状态 |
| 2026-06-13 | SQLite 并发基础先于多槽位 | WAL 仍只有一个 writer，需要 busy timeout、短事务和压力验收 |
| 2026-06-13 | Slurm 复用官方 Snakemake plugin | 避免重复实现成熟的提交、状态检查和取消逻辑 |
| 2026-06-13 | P0-1 真实 worker SIGKILL Gate 通过 | staging artifact、deploy、systemd_user runner kill/restart、lease generation、candidate adoption、artifact/lineage 证据均已闭环 |
| 2026-06-13 | P0-2 保持进行中 | P0-1 crash recovery 已闭环，但完整 UI 生命周期 Gate 仍需独立验收 |
