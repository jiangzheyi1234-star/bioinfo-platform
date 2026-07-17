# ADR: Remote Runner 可恢复激活与 systemd 身份

Status: Accepted

Date: 2026-07-17

## 背景

Remote Runner 已经具备版本化 release、协议自证明、procfs incarnation、跨 `exec` 的 `flock`
生命周期栅栏，以及不可变 process-owner 记录。这些证据可以证明一个协作进程如何启动，却不能证明：

- 当前响应者属于哪一次部署激活；
- systemd 正在管理的 `MainPID` 是否就是该 owner；
- config、profile、unit 与 release 是否来自同一个候选；
- 中断后的 bootstrap 应继续提交、回滚，还是保持人工修复；
- stop 是否会在检查后误杀一次新的重启。

当前 bootstrap 还会在候选验证前停止服务，并分别修改 config、profile、`current` 和 systemd unit。
Token rotation、manual stop、prune 与 uninstall 也没有共享同一个远程激活栅栏。因此，现状不能诚实地称为
原子激活或可证明回滚。

## Decision Card

```text
Decision: 将部署建模为可崩溃恢复的激活状态机；每次激活和 systemd unit 实例都有永不复用的 ID，
  运行时绑定确切不可变 release，current 只在提交后作为读模型更新。
Track: architecture-track
Baseline: origin/main cb9266b6e2d32193f657d3de002b0aff14524f3d;
  branch codex/remove-first-run-wizard at 88e1a7f4c1646ccd68b71cd54686ba4923370d86
Why now: 分散 mutation、按版本锁和固定 unit 无法阻止 mixed activation、并发 token rotation 或 stop TOCTOU。
Accepted constraints: protocol v5 保持不变直到端到端 binding 完成；systemd 托管最低版本为 232；
  shared/runtime 与 journal 位于稳定本地 Linux 文件系统；staging deploy 继续 fail-closed。
Rejected alternatives: current 作为 ExecStart 信任根；固定 unit + PID/pgrep/pkill；就地修改 token/config；
  MainPID、cgroup 或 READY=1 单独授权；要求 pidfd、cgroup v2、openat2 或 systemd v257 才能部署；
  把多个 pathname 与 systemd manager 状态称作单次 POSIX 原子提交。
Ownership split: core/contracts 定义 generation、transition 与 systemd observation；remote runner 发布自观察；
  control plane 负责权威 systemd 查询、全局栅栏、journal、验证与恢复。
Proof required: Windows contract/runner tests 与 Ruff；Linux CI 真实 user-systemd 的 start/restart/stop、
  InvocationID/MainPID/cgroup 对照，以及 restart-preventing exit status 证明。
Stop conditions: 无法证明 exact activation、旧 invocation 已停止或 rollback 已重新通过认证 ready 时，
  保持 lifecycle guard 并进入 recovery_required。
Cleanup: 删除研究缓存与测试产物；保留用户文件和已提交 release evidence。
```

## 决策

激活不是跨文件系统与 systemd manager 的“瞬间原子操作”。H2OMeta 将其定义为 append-only、
可恢复、可核验的状态转换。三种身份必须分开：

| 身份 | 生命周期 | 用途 |
| --- | --- | --- |
| `generationId` | 一组不可变 config/profile/unit/release 内容与 credential-free config digest | 证明运行内容 |
| `activationId` | 一次 install/upgrade/rotation/repair 尝试 | 证明控制面操作与 journal |
| `InvocationID` | systemd 每次 runtime cycle | 证明具体服务实例 |

Generation 可以被新的 repair 或 rollback 激活，但旧 `activationId` 和旧 `InvocationID` 永远不复用。
Rollback 是一次新的前向激活：用新的 `activationId` 启动上一 generation，并重新完成 systemd、owner、
认证 health 与 guard-release 验证。只切回 symlink 不构成 rollback success。

全局 no-reuse 不能只比较相邻两次 activation。Controller 必须在可信 no-replace journal 中维护完整的
Invocation reservation ledger：每条 reservation 绑定 activation、generation、unit、target fingerprint、
首次观察该 InvocationID 的 transition fingerprint，以及前一 reservation fingerprint。新 activation 的
所有 transition 都绑定启动前完整 ledger 的 canonical fingerprint，并拒绝 ledger 中任一历史
InvocationID；这覆盖 `A(X) -> B(Y) -> C(X)` 与没有 previous lineage 的 repair。Previous/failed
lineage 不能只做 ID membership 检查，还必须把 ledger entry 的 activation、generation、unit、target 与该
chain 首个带 InvocationID 的 transition 逐项对照。

## systemd 托管身份

托管模式使用静态 template unit 和唯一实例名：

```text
h2ometa-remote@<activationId>.service
```

实例必须直接执行候选 generation 所绑定的不可变 release，不能通过可变 `current` 找到代码。目标 unit
使用 `Type=notify`、`NotifyAccess=main`、`KillMode=control-group` 与 `SendSIGKILL=yes`。Main process
只能在 artifact、config、owner、listener 全部就绪后发送 `READY=1`；READY 是启动排序门，不是独立的
身份或健康证明。

Runner 从环境读取 `$INVOCATION_ID` 并从 `/proc/self/cgroup` 记录自观察。控制器必须从 systemd
D-Bus 或等价的严格 `systemctl show` 查询取得权威 `InvocationID`、`MainPID`、`ControlGroup`、
`FragmentPath`、`ActiveState`、`SubState` 与 `NeedDaemonReload`，再与 activation、release digest、
process incarnation 和不可变 owner 交叉核对。

Controller observation 还必须证明 template 已加载、没有 drop-in，并核对 `Type=notify`、
`NotifyAccess=main`、`KillMode=control-group`、`SendSIGKILL=yes`、无 `PIDFile`、restart policy 与
restart-preventing statuses。Template 文件本身的 fingerprint 属于 generation；`NeedDaemonReload=no`
和空 drop-in 列表把该文件证据连接到 systemd 的有效配置。

`MainPID` 会复用，cgroup 路径会随 unit 名复用，`INVOCATION_ID` 也不是 secret；任何一个字段都不能
单独授权 mutation。唯一 unit 实例使 stop 可以针对不会被新 activation 复用的对象调用 `StopUnit` 并
等待 job 完成，避免固定 unit 在“检查旧 invocation”和“停止”之间重启的 TOCTOU。

## 激活状态机

首版 contract 使用细粒度 transition 记录每个可观察提交点：

```text
prepared -> guarded -> stopping -> stopped -> promoting -> promoted
         -> starting -> verifying -> candidate_verified -> committing -> committed

prepared | guarded -> aborted
任意非终态 -> recovery_required

recovery_required
  -> 新建 rollback activationId
  -> 以上一 committed generation 为 target 重新走完整正常链
  -> committed
```

每个 transition 都包含递增 revision 和前一 transition fingerprint。Upgrade、rotation 与 rollback 的
genesis 还必须绑定上一 target 的 committed transition fingerprint；rollback 另行绑定失败 activation 的
`recovery_required` transition fingerprint。Controller 不能只提交一条形似终态的记录：它必须从可信、
no-replace journal 载入从 revision 1 到终态的完整 per-activation chain，契约会重新验证连续 hash、target、
lineage shape、InvocationID 与终态证据，再接受该 chain head。任意 target 结构体本身不能冒充“上一已提交
版本”。记录必须 no-replace 发布，且 journal 不保存明文 token、Authorization header 或可逆 credential。
`committed`、`aborted` 与 `recovery_required` 是该 activation 的终态；后续修复或 rollback 创建新的
activation。

`candidate_verified`、`committing` 与 `committed` transition 必须嵌入 systemd observation、process owner、
authenticated readiness、Invocation reservation 与复合 activation verification 的 fingerprints；
`committed` 还必须绑定精确的 lifecycle-guard release evidence。一旦 chain 观察到 `InvocationID`，后续
所有记录（包括 `recovery_required`）都必须继承同一值，不能通过终态置空来绕过 reuse 检查。Controller
在首次观察 transition 后 append reservation，并在进入 `candidate_verified` 前让 evidence 绑定该
reservation。完整 chain 验证必须接收 reservation 实体，证明它是 prior ledger head 的唯一下一条，并让
其 canonical fingerprint 与 verified/committed evidence 完全相等；controller 必须从 no-replace journal
重新读取该实体后再验证，任意内存构造的 SHA 占位符不构成登记。若 crash
留下未登记的 observation，reconcile 必须先补齐或保持 gate，不能开始下一 activation。
Hash chain 只证明所给记录的顺序，不能替代可信 no-replace journal 的来源保证或这些终态证据。

`aborted` 只允许在尚未产生 live mutation时使用；若已获取 guard，还必须绑定 owner-matched guard-release
evidence。一个 rollback activation 的 `committed` 必须证明：

1. 旧 generation 的 config/profile/unit/release fingerprints 全部匹配；
2. 它以一个新的唯一 unit 和新的 `InvocationID` 启动；
3. systemd `MainPID`、procfs incarnation、cgroup 与 owner record 一致；
4. 使用旧 generation 对应 credential 完成认证 ready；
5. lifecycle guard 由本次 activation 的精确 owner 释放。

任何一项未知都让失败 activation 保持 `recovery_required`，不得以布尔值或 `current` 指针宣称恢复成功。
后续 rollback 的成功事实属于新的 committed activation，不改写原失败链的历史终态。

## 文件与选择器

目标布局是 generation 与 transaction 分离：

```text
~/.h2ometa/runner/shared/activation/
  generations/<generationId>/
    runner.json
    profile.v9+.yaml
    generation.json
  transactions/<activationId>/
    transitions/<revision>.json
  invocation-reservations/<revision>.json
  invocation-ledger.json  # reservations 重建出的 canonical read model
  current.json
```

目录在写入 secret-bearing config 前必须为 `0700`，配置文件为 `0600`。完整 config fingerprint 绑定
实际字节；独立的 credential-free runtime-config fingerprint 必须由移除 credential 后的规范 payload
计算，使 token rotation 无法夹带端口、路径或 runtime policy 变化。Generation 只有在所有文件、
digest 和 protocol preflight 验证成功后才可成为候选。`current.json`/`current` 只在 durable
`COMMITTED` 后更新，供诊断、UI 和人工导航使用；运行时不把它当信任根。

单个本地文件的发布继续使用临时文件、fsync、rename 与父目录 fsync；这只保证该文件的替换语义，
不扩张为跨文件或 systemd 的原子性声明。`flock` 只提供同一主机、同一稳定本地文件系统上的协作互斥，
不是分布式 fencing 或对恶意同 UID 进程的隔离。

## 分阶段落地

1. 定义 generation/transition/systemd observation、Invocation reservation ledger 的严格契约、canonical
   fingerprint 与状态机；不改变 protocol v5，也不启用远端 mutation。
2. Runner 捕获 activation 与 systemd 自观察，owner/runtime state 加入 end-to-end binding，随后整体升级
   protocol v6；unit 加入对应 restart-preventing exit status。
3. 控制面加入所有 lifecycle mutation 共用的全局 activation gate、durable journal、unique unit start/stop、
   systemd 权威核验和故障注入测试。
4. Bootstrap 与 token rotation 改为 generation 发布；stop/prune/uninstall 必须通过同一 gate。旧的广泛
   `pkill` 与 in-place config mutation 删除后，才可重新启用 staging deploy。
5. Linux CI 证明真实 user-systemd；存在 cgroup v2 时额外核验 `cgroup.events populated=0`，存在 pidfd 时
   增强 exact liveness，但二者均不是最低兼容依赖。

## 非目标

- 本阶段不宣称抗 root 或同 UID compromise；更强隔离需要独立 service user 与 root-owned release/unit。
- 不用 PIDFile、进程名或监听端口替代 activation 身份。
- 不把 `sd_notify`、pidfd 或 cgroup 当作 API token。
- 不在契约未被生产路径消费前提前发布 protocol v6 capability。
- 不把 background-process 模式描述为具备 systemd 等价证据；其支持策略在接线阶段单独决策并明确失败面。

## 官方依据

- [systemd.exec：`INVOCATION_ID` 与 v232 边界](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [systemd D-Bus API：`InvocationID`、`MainPID`、`ControlGroup` 与 unit jobs](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html)
- [systemd.service：`Type=notify`、MainPID 与 watchdog](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd.kill：`KillMode=control-group`](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html)
- [sd_notify：READY 归属与通知语义](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
- [Linux pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)
- [Linux rename/renameat2(2)](https://man7.org/linux/man-pages/man2/rename.2.html)
- [Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Nix profiles：不可变 generation 与原子 selector](https://nix.dev/manual/nix/latest/package-management/profiles)
- [OSTree atomic upgrades：先构建 deployment，再切换 selector](https://ostreedev.github.io/ostree/atomic-upgrades/)
