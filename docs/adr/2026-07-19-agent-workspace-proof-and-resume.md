# ADR：Agent 工作区证明与证据化恢复

- 日期：2026-07-19
- 状态：Accepted；按独立、可回滚提交逐步启用
- 前置决策：[Agent 运行授权与原子 execution binding](2026-07-18-agent-run-authorization-and-execution-binding.md)
- Active branch baseline：`codex/remove-first-run-wizard` @
  `69a3fcb491aecd8ab562d1ecf93ed5f3c7370005`

## 决策卡

```text
Decision: Agent-owned WorkflowRun 在每个 Snakemake 进程边界生成 append-only、content-addressed
  workspace proof；生成资产与 Snakemake checkpoint 分开封存，只有 source terminal proof 被
  plan/options/claim/launch 全链路绑定时才允许 Agent resume
Track: Agent-first execution safety track
Why now: input/runtime/lease 已在每次 Popen 前重验，但 resume 仍会复用 mutable workdir；因此当前
  正确地 fail-closed，尚不能兑现可恢复 Agent run
Accepted constraints: 保持同一 WorkflowRun 的 governed failed/canceled -> queued resume；复用
  Snakemake --rerun-incomplete 与既有 RunLedger；普通 run/resume 不查询 workspace proof；不改 v19
  authorization receipt；proof 仅称本地完整性证据，不宣称签名或 SLSA build level
Rejected alternatives: hash 整个 workdir 一次后永久复用；复制/删除 .snakemake；把 mutable path existence
  当恢复证明；放宽 terminal transition guard；创建第二个 run；引入 paused/resuming 影子状态；先移除
  Agent resume blanket gate 再补证明
Proof required: v20 atomic migration、strict hash/ID、immutable storage、relative manifest、symlink/hardlink/
  write-bit/TOCTOU rejection、lease-fenced event、pre_dry_run/pre_run/terminal checkpoint、source terminal
  binding、每次 Popen revalidation、ordinary regression、Windows pytest/ruff 与真实 UI acceptance
```

## 背景

Agent launch gate 已经在 Worker claim 后验证不可变 authorization origin、WorkflowRevision、当前 runtime、
run-private input snapshot、job/attempt/lease，并在 dry-run 与正式执行的每个进程启动前再次验证。尚未覆盖的
缺口是 execution workdir。

初始 generated workflow 会在 attempt workdir 写入：

- `run-config.json`；
- `workflow/Snakefile`；
- `workflow/envs/**`；
- rule script/module assets。

Snakemake 随后在同一目录维护 `.snakemake/**`。现有 ordinary resume 为新 attempt 复用 source attempt 的
workdir，并使用 `--rerun-incomplete`。这对普通 WorkflowRun 是已有、受测试保护的语义；但对 Agent run，
只证明目录、config 和 `.snakemake` 存在，不足以证明启动时使用的 definition 与 checkpoint 仍是被授权的
那一份。因此 Agent resume 目前必须保持 `AGENT_RUN_LAUNCH_GATE_FAILED: resume_workspace`。

## 官方实践映射

Snakemake 官方文档明确说明：

- `--directory` 定义相对 input/output 的工作目录；`.snakemake` 默认也位于该工作目录；
- `--rerun-incomplete` 只重跑被 metadata 识别为 incomplete 的 job；
- `--cleanup-metadata` 会删除版本与 incomplete 标记；`--drop-metadata` 会使 provenance 报告为空或不完整；
- rerun 判断还依赖 input、params、rule code 与 software environment 等 execution metadata。

因此 `.snakemake` 不是可忽略缓存，也不是可与生成资产混成一个永远不变的目录 hash。H2OMeta 必须允许
它在一个受权进程内演化，同时在进程边界把其精确状态重新封存；Agent 路径继续禁止
`--ignore-incomplete`、metadata cleanup/drop 等绕过。

SLSA Build Provenance v1.2 将外部参数、resolved dependencies、builder identity、invocation metadata 与
subject 分开，并要求下游验证不受信的 external parameters。in-toto 则以 layout、authorized functionary 和
记录 command/materials/products 的 link metadata形成可验证步骤链。H2OMeta 借用两项设计原则：

1. definition、resolved inputs/runtime 与 invocation identity 分字段绑定，不用一个模糊“workspace hash”；
2. 每个执行边界产生链接到上一份证据的 append-only proof，验证者拒绝缺失或意外字段。

当前 proof 由本地 SQLite immutable trigger、hash chain 与 lease fence保护，没有独立签名或受隔离 builder，
所以不得称为 SLSA attestation、in-toto link 或达到某个 SLSA level。

Temporal 的安全部署指南要求长生命周期执行固定兼容的 Worker code，或显式 versioning，并在新 Worker 接收
任务前对已有 history 做 replay verification。对应到 H2OMeta：queued/resumed Agent run 不能静默采用升级后的
WorkflowRevision/runtime/workspace；必须在 Popen 前验证绑定证据。这里只借用原则，不引入 Temporal。

## 工作区拆分

### A. Immutable generation bundle

封存 `run-config.json + workflow/**`。Manifest：

```text
relativePath, size, sha256
```

要求：

- relative path 使用 `/`、稳定排序且无重复；拒绝绝对路径、`..`、空段与控制字符；
- durable v1 同时拒绝 Windows ADS、尾随点/空格、DOS device name 与大小写路径别名；
- 每个成员是 managed workdir 内的普通文件；拒绝 symlink、reparse point、hardlink、目录逃逸；
- 使用 stat/read/stat 与目录双扫描捕获读取中的变化；
- 生成完成后清除写位，并在每次 Popen 前重算 manifest；
- `run-config.json`、Snakefile、env 与 script/module assets 全部必须在 manifest 中；
- 不在 durable payload 中保存绝对路径。

### B. Mutable Snakemake checkpoint

`.snakemake/**` 在受权 Snakemake 子进程中合法变化。它在三个边界封存：

```text
pre_dry_run -> pre_run -> terminal
```

- initial `pre_dry_run` 要求 checkpoint 为空；
- resume `pre_dry_run` 要求当前 checkpoint 精确匹配 source attempt 的 terminal proof；
- dry-run 正常返回且 lease 仍有效后写 `pre_run` proof；
- 正式进程退出、输出处理完成且 lease 仍有效后写 `terminal` proof；
- 任一进程开始前，launch guard 同时重验 authorization、lease/cancel、generation bundle 与当前 checkpoint；
- 失败/取消也应尽可能产生 terminal checkpoint，但 stale lease 永远不能写 proof。

Checkpoint manifest 同样只保存 relative path、size、sha256。运行日志、结果 artifacts 与 run-private input
snapshot 不混入 `.snakemake` manifest；它们分别由既有 event/artifact/input evidence 管理。

## Durable contract

Schema v20 新增 `agent_workspace_proofs`。核心字段：

```text
workspace_proof_id, contract_version, run_id, authorization_id,
attempt_id, lease_generation, source_attempt_id,
process_boundary, process_ordinal,
workflow_revision_id, workflow_revision_content_hash,
workflow_revision_manifest_hash, run_spec_hash,
input_snapshot_hash, tool_assets_hash,
runtime_lock_hash, runtime_proof_hash,
immutable_manifest_json, immutable_manifest_hash,
snakemake_manifest_json, snakemake_manifest_hash,
previous_proof_hash, event_id, created_at, proof_hash
```

约束：

- `UNIQUE(attempt_id, lease_generation, process_ordinal)`；
- `UNIQUE(proof_hash)` 与 `UNIQUE(event_id)`；
- run/authorization/attempt/source-attempt/WorkflowRevision 使用 `ON DELETE RESTRICT`；
- update/delete trigger 一律拒绝；
- fresh、migration 与 current readiness 都精确验证列、CHECK、UNIQUE、index、trigger 与 FK 签名；
- proof hash 包含全部语义字段、event identity 与 timestamp；ID 从 proof hash确定性派生；
- insert-side exact replay 仅在当前 live lease、claimed job 与 chain head 仍全等时返回原 proof；历史读取使用
  独立 resolve/fetch primitive；同一 attempt/lease/ordinal 的不同 payload fail closed；
- 首次 append 在同一 writer transaction 中验证 authorization receipt、WorkflowRevision、run、attempt、
  未过期 active lease、claimed job execution options，以及 fresh/resume/successor proof chain；
- proof 与 path-free run event 在同一 `BEGIN IMMEDIATE` 中写入；
- stale attempt/lease 不得留下 proof 或 event。

V20 首个提交只建立严格 contract、精确 migration/readiness 与 connection-scoped guarded storage，不接入
executor，也不移除现有 Agent resume gate。这使迁移可独立验证、回滚与推送。

## Authority 绑定

每份 proof 必须绑定：

- authorization ID 与 receipt 内的 runSpec/runtime hashes；
- content-addressed WorkflowRevision ID、content hash 与 manifest hash；
- run-private input materialization event/manifest 的 canonical hash；
- generated tool/env/script/Snakefile assets 的 canonical hash；
- 当前 attempt ID、lease generation、process boundary 与 ordinal；
- 上一份 proof hash；resume 的 source attempt ID/generation 必须来自 claimed job 的持久化 `resumeScope`，
  且第一份 proof 必须链接该 source attempt 的 terminal proof。

不修改 `agent-run-authorization.v1`。Workspace proof 是 authorization 后的执行证据，通过
`authorization_id` 引用原批准事实。

## Resume contract

现有 governed run resume 继续在一个事务中把同一 terminal run 从 `failed/canceled` 重开为 `queued`，清理
terminal timestamps/error，写 command/event，并给同一 job 存 canonical execution options。普通
`publish_status` 的 terminal immutable guard保持不变；测试和调用方不得绕过 `request_run_resume()` 只改 job。

Agent resume 分阶段增加：

1. plan 要求 source attempt 有 terminal workspace proof；
2. public plan 只暴露 proof present/hash prefix/count 等安全摘要，不暴露 path/manifest digest细节；
3. execution options 写完整 `sourceWorkspaceProofHash`；
4. claim preflight 在当前 target lease 下重读 source attempt/proof/workdir并全等验证；
5. executor 用 source terminal proof建立 target `pre_dry_run` proof；
6. 每次 Popen guard 重验当前 proof；完成全部步骤后才删除 blanket `resume_workspace` 拒绝。

Agent run 缺 proof、proof 漂移、source attempt 不匹配、旧 lease 未释放、source process 未确认退出或工作区 bytes
变化时全部 fail closed。不得退回 ordinary resume，也不得自动创建新 WorkflowRevision 或新 run。

## 非目标

- 将 DAG 恢复为主创作界面；
- 删除 Snakemake 内部 DAG/metadata；
- 把 cancel+resume 宣称为真正 pause；
- 复制或修复未知 `.snakemake` 状态；
- 支持任意 caller path、外部 workspace 或 symlink tree；
- 改写 v19 authorization、WorkflowRevision 或旧 proof；
- 引入第二套 run lifecycle 或执行引擎；
- 声称 cryptographic signature、remote attestation 或完整可重现环境。

## 分阶段交付

1. v20 strict proof contract、schema、migration、storage；
2. generated bundle manifest、只读封存与首次 Popen guard；
3. `pre_dry_run/pre_run/terminal` Snakemake checkpoint chain；
4. Agent resume plan/options/claim 绑定 source terminal proof；
5. proof-gated Agent resume 正向路径与真实浏览器验收；
6. 每阶段独立 pytest/ruff、精确 commit、push、fetch SHA 校验。

## 参考

- [Snakemake command line interface](https://snakemake.readthedocs.io/en/stable/executing/cli.html)
- [Snakemake FAQ：working directory、locking 与 rerun metadata](https://snakemake.readthedocs.io/en/stable/project_info/faq.html)
- [SLSA Build Provenance v1.2](https://slsa.dev/spec/v1.2/build-provenance)
- [in-toto getting started](https://in-toto.io/docs/getting-started/)
- [Temporal safe deployments](https://docs.temporal.io/develop/safe-deployments)
