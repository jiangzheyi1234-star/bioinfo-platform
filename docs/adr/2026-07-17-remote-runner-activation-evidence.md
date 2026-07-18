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
| `generationId` | 一组不可变 config/profile/unit/release 内容、credential-free config digest 与密钥化配置完整性证据 | 证明运行内容 |
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

Runner-side 自观察先以独立的 dormant contract 落地，不修改 protocol v5、owner v1、runtime-state 或
现有启动入口。`runner-systemd-self-observation.v1` 严格保留 cgroup v2 `0::PATH`、cgroup v1
`name=systemd` 或 hybrid 中的候选路径；它不按 basename 宣称 membership。cgroup namespace 可能让
`/proc/self/cgroup` 显示相对路径，因此 controller 必须先确定 systemd 实际管理的 hierarchy，再要求完整
`ControlGroup` 与该 hierarchy 的候选路径精确相等，才能进入后续验证。`SYSTEMD_EXEC_PID` 从 systemd
v248 才提供：存在时必须规范且等于 self PID，缺失不能作为 v232 基线的失败原因。

本阶段有意不发布 `runner-activation-process-binding.v1`。Generation 的 keyed config-blob integrity tag、
credential-free runtime-config fingerprint 与现有 owner 的 persisted/effective fingerprints 具有不同语义；
共享内容计算器现在只定义算法；在 publisher/startup 从可信 snapshot 实际重算前把两组 digest 一起封装，
仍只能证明两份声明被关联，不能证明 runner 实际加载了该 generation。Binding v1 必须等 generation
config/profile/unit/release 的实际字节均由生产路径重算后再定义，并同时
精确关联 controller `FragmentPath`、template fingerprint 与对应的 cgroup hierarchy。当前也不生成可启动
template、不把 capability 写入 v5 descriptor；generation-aware startup、runtime-state reference、
`READY=1` 与 protocol v6 必须在后续端到端接线阶段一起完成。

## Generation 内容身份

原始 artifact digest 与逻辑配置 fingerprint 是两种不同证据。Profile、systemd template 与 release
archive 使用 `sha256(exact bytes)`；读取时不转换换行、BOM 或 Unicode。Secret-bearing `runner.json`
不发布无键 raw SHA-256：generation 只记录 `configBlobIntegrityKeyId` 与
`configBlobIntegrityTag=hmac-sha256:...`。Tag 覆盖 schema domain、key ID、八字节大端内容长度和实际
canonical config bytes；独立 32-byte integrity key 不进入 generation、journal 或日志。Tag 可以公开，
key 必须由后续版本化 keyring 独立保存。Key 缺失、未知或验证失败进入 `recovery_required`，不得退回
raw SHA，也不得静默生成新 key 后继续。

旧 `configFingerprint` 只存在于尚未被 protocol v5、生产存储或远端 mutation 消费的 dormant v1
contract。本决策在首次发布前直接将其替换为 key ID + HMAC tag，并让 exact-field validator 拒绝旧字段；
不添加双读、fallback 或静默迁移分支。

公开的 `runtimeConfigFingerprint` 由 exact `RemoteRunnerConfig` 字段集减去 `token`、
`artifact_s3_access_key`、`artifact_s3_secret_key` 后计算；actor、roles、端口、路径、worker policy、
storage endpoint/bucket/region/prefix 与 protocol expectation 都保留。当前 SQLite-only 约束下
`database_url` 必须为空，不能把带拓扑和凭据双重语义的 URL 整体删除后仍宣称 runtime identity 完整。
配置字节采用仓库自有 deterministic JSON（固定字段、sorted keys、compact UTF-8、单一尾 LF），不把
Python `json.dumps` 错称为 RFC 8785/JCS。

内容计算器只接受已经通过生产语义校验的 effective config；它的 exact field/type envelope 不替代 path、
protocol、role、URL 或 environment policy。Publisher 必须拒绝把 userinfo、签名 query、明文密码等塞进
本应公开的 endpoint/path/source 字段，并禁止未进入 effective config 的 ambient override。Profile builder
只接受 canonical absolute POSIX conda path 和无 userinfo/query/fragment 的 `https` 或本地 `file`
wrapper prefix；动态 YAML scalar 使用确定性双引号，拒绝 host `PathLike` 转换以及 C1/NEL/LS/PS 注入。
Publisher 还必须证明 `file` wrapper 位于 generation-owned、由 release digest 覆盖的只读树中；仅有 profile
bytes digest 不证明 wrapper 源内容不可变。

`tokenGenerationId` 与 integrity key ID 都是随机 opaque 128-bit ID，不从 token、key 或 digest 推导。
Token rotation 必须保持 integrity key ID 和所有 credential-free runtime identity 不变，同时创建新的
generation ID、token generation ID 与 config-blob tag；tag 变化只证明 blob 变化，publisher 后续还必须
验证 operation-specific exact diff。Integrity key rotation 是独立的 reseal/repair，不得冒充 token
rotation。只要 retained rollback generation 仍引用旧 key ID，远端 private integrity-key store 就不得 prune
对应 key。

### 版本化 credential identity

现有 production path 的 `runner://<serverId>` 是一个可变 OS-keyring slot：`set_password` 会覆盖旧 token，
普通 upgrade 也会隐式生成新 token。它既不能按 generation 找回 rollback credential，也把 active selector
与 secret identity 混成同一个名字。后续接线必须删除这种固定 ref 语义，不增加双读或旧 ref fallback。

本阶段只增加 dormant pure contract，定义不可变 installation record、版本化 token locator 与远端
config-integrity-key descriptor，不调用 OS keyring、不写远端文件，也不改变 generation、transition 或
protocol v5。`runnerInstallationId` 是随机 opaque 128-bit ID，与 canonical runner root 绑定；它不包含
`serverId`、hostname、IP、SSH alias、machine-id 或时间戳。复制 installation record 会得到相同 fingerprint，
所以它不证明物理主机或 SSH host identity，也不授权跨主机自动 adoption。跨主机 restore 默认创建新的
installation/token/key IDs 并显式 re-enrol；若未来需要保留旧 generation，必须另有 host-key registry 与受审计
的 secret export/import 流程。

控制端 token locator 使用 exact
`h2ometa-runner-token:v2:<runnerInstallationId>:<tokenGenerationId>`，OS-keyring service namespace 也独立
版本化。Locator 只含非 secret opaque ID，但仍按 internal sensitive metadata 处理；diagnostics、audit 与
公开结果只允许 domain-separated locator fingerprint 及 provider/purpose/version，不输出 raw locator。Token
material 永不进入 locator、generation、descriptor、journal、异常或日志。远端 integrity descriptor 只声明
`remote-private-file`、`config-blob-integrity`、key ID、`hmac-sha256`、32-byte 长度与从 trusted runner root
逐字派生的
`shared/activation/secrets/config-integrity/<configBlobIntegrityKeyId>.key`。Descriptor fingerprint 只证明
这份 locator record；它不证明 material 存在、owner/mode/nlink、非 symlink、实际 bytes 或 HMAC 验证成功。

面向 generation 的高层 binding 必须一次核对 installation root、generation fingerprint、token locator、
integrity descriptor 以及 installation/generation/token/key 四类 ID 分离。当前 binding 仍是 dormant record
validation，不是 transition evidence；future generation-aware transition 才能消费它。实际 store 阶段必须在
全局 activation gate 下实现 create-or-verify。已接受的 dormant store 设计在每次 key operation 中，从经过
重证的 `activation` capability 动态打开或创建私有
`secrets/config-integrity/.staging` scope；这三个目录不属于 enrollment 固定 skeleton，也不成为 session
长期保留的 fd。Final 名固定为 `<configBlobIntegrityKeyId>.key`，deterministic pending 名固定为
`.staging/<configBlobIntegrityKeyId>.pending`；两者只允许当前 UID、regular、精确 `0600`、`nlink == 1`、
同 activation device，内容必须恰为 32 raw bytes。不存在 final 时返回 typed `absent`，不会顺便生成 key；
material 只能由显式 create-or-verify 输入提供，store 不自动生成、轮换、prune 或导入导出。

Pending 与 final 均使用 no-replace publication；精确重试只在固定长度检查后用 `hmac.compare_digest` 接受相同
bytes，不同 material 是永久冲突。任一 rename 后错误、directory `fsync` 错误或 post-proof 失败都进入
`outcome_unknown`；reconcile 必须丢弃旧 session，在 fresh session 中重新取得 global gate、重证 canonical
root/layout，再检查 deterministic pending/final，不能从异常或旧 fd 猜测提交结果。Observation 不输出 material、
raw key ID、路径或 tag。该切片保持 protocol v5、bootstrap、rotation、generation publisher、transition 和
`prepared` 全部不接线；当前实现只提供这一 dormant storage primitive，不宣称可供生产消费。Python keyring 公共 API
没有 CAS/no-replace 事务，Windows `CredWrite` 和 Secret Service 的 replace 语义也会覆盖同名 credential，
因此底层 `set_password` 不能单独证明 immutable storage。

`0700`/`0600`、nofollow 与 link-count proof 不抵抗 root 或恶意同 UID 进程；后者能够读取或改写同一私有
namespace，生产强化需要独立 service UID 或外部 custody boundary。Python 也不能证明 immutable `bytes`、
allocator/HMAC 临时副本已擦除；mutable buffer 只能 best-effort overwrite。Windows 测试只证明 orchestration
与状态机；Linux CI 必须不可跳过地覆盖真实 nofollow/open、owner/mode/nlink/device、deterministic pending、
no-replace、file/directory `fsync`、crash/unknown 后 fresh-session reconcile 以及 typed `absent`。

相同 `generationId` 在所有 operation 中都必须对应逐字段完全相同的 generation record。Repair 可以用新的
activation 重启同一 generation；若 reseal、key rotation 或任何内容证据改变，必须创建新的 generation
ID，不能覆盖原路径或复用原 ID。当前 transition contract 只可立即拒绝与上一 committed target 的冲突；
publisher 必须以 no-replace generation directory 和 append-only `generationId -> generationFingerprint`
registry 检查完整历史，关闭 `A -> B -> A'` 的隔代复用，之后才能授权远端 mutation。

本阶段先以 dormant pure contract 定义该 registry，不修改 protocol v5、bootstrap、rotation 或远端文件。
每条 registration 嵌入完整的 normalized generation，并冗余保存 `generationId` 与重新计算的
`generationFingerprint`；连续 revision 和前一 registration fingerprint 把它们组成 append-only chain。
Registry 是由可信 no-replace registration journal 重建的 canonical read model，不是独立信任根，也不证明
generation directory 已发布。Planner 对已登记且逐字段完全相同的 generation 返回 no-op，只表示该 ID
不需要再次登记；同 ID 的任何漂移永久失败。

Registry 的状态只有 `unseen -> permanently reserved exact mapping`，不加入 `published`、`retired` 或可被误用
为 activation evidence 的布尔状态。Registration durable 后、generation directory 发布前崩溃会留下安全的
reserved orphan；恢复必须先从权威 journal 重建完整 registry，再用同一 generation 精确重试，不能把游离
registration 参数或陈旧 read model 当作历史。Registry 永不 prune；generation/release/key retention 另由
仍可 rollback 的 committed generation reachability 决定。

生产 publisher 的固定顺序必须是：先按固定 extraction policy durable no-replace 发布 installed release tree
及其 canonical tree manifest，再 durable 创建或精确 reconcile generation 所需的 versioned integrity key；之后
在私有 staging 中从实际 bytes 重算并验证所有 generation evidence，durable no-replace 写 registration、
fsync 并从 journal 重读，随后 no-replace 发布 generation directory、重新核验实际 bytes，最后才写 durable
`prepared`。Archive SHA 只标识压缩包 bytes，不能替代 installed-tree identity；任一步失败或结果未知都
不能进入 service mutation。

本阶段把这一顺序的信任根落成真实 Linux storage primitive，而不是继续增加纯 record。
`activation_storage_root.py`、`activation_storage_layout.py`、`activation_storage_filesystem.py` 与
`activation_storage_session.py` 从 validated installation 的 canonical runner root 出发，逐组件以 directory fd、
`O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` 打开固定路径；从 `/` 到 runner root 的完整祖先链都必须由 root
或当前 UID 拥有且不得 group/world writable。Session 保留 runner parent、root、`shared`、shared-level global
lock、`activation`、activation-level `.staging`、`generation-registrations` 与 journal `.staging` capabilities。
每次权威读写前后不仅从 `/` 独立重开 root，还逐级比较 parent pathname 与 retained child fd 的 dev/inode，
并重新验证 owner/mode/device/filesystem magic，拒绝 detached tree 上的第二把锁或第二本 journal。即使一次
journal read 先发现 payload conflict，也必须完成 post-layout proof，避免把 detached journal 错报为 canonical
corruption。

`activation_installation_storage.py` 以 `shared` 下两个固定 phase name 完成单调绑定。在读写任何 enrollment
record mutation 或权威 phase classification 前，session 先创建或打开永不移除的
`shared/global-activation.lock` 并持有 `flock`；missing-gate guard 只能只读检查 phase/activation 名是否存在，
该稳定 lock 的 O_EXCL 则封住 stale virgin-check writer 的 ABA。锁内只接受三种状态：neither record 且无 activation tree 的 virgin、
intent-only 的 recoverable bootstrap、final-only 的 authoritative root；both 或 neither+activation 都 fail
closed。Virgin 状态在任何 activation directory 创建前，以 no-replace CAS 发布
`installation-enrollment-intent.json`，原子选定唯一 installation identity。只有与 intent 逐字节相同的
installation 才能从 crash 幂等补齐固定 skeleton。

重新证明完整 root → shared → gate → activation → staging/journal pathname-to-fd chain 后，还必须证明
pre-final authority 是精确空白 skeleton；任何 registration、unknown entry 或 staging orphan 都不能被领养。
证明成立后，以同目录 `renameat2(RENAME_NOREPLACE)` 把已验证 intent inode 原子晋级为
`installation-enrollment.json`，随后 fsync `shared`、证明 final inode 未变且 intent 已消失，并再次证明空白
skeleton 与完整 layout。Final-only 后任何缺失 activation child 或 stable gate 都 fail closed，不能自动重建；
final 缺失但 canonical activation 仍存在也不能退化成 virgin。
若 root/同 UID 删除 final 和整个 activation namespace，则即使空 stable gate 仍存在，本地也无法与 virgin
区分；此 destructive reset 不在本地 threat model 内。生产接线必须让 controller monotonic enrollment witness
在“曾 enrolled、现报 local virgin”时停止，只有显式受审计 reset 才能重新初始化。

活动 phase 的 bytes 只能是现有 installation v1 canonical JSON 加单个 LF；intent/final 必须为当前 UID、
regular、`0600`、`nlink == 1`、同 device，且二者在合法状态中永不共存。同 root 的不同 installation record
永久冲突。Intent/final phase 只建立本地 root bootstrap authority：它不证明物理
主机、SSH host key，也不是 activation `prepared` evidence。生产启用前，控制端仍必须单独持久化
installation fingerprint 与已信任 SSH host-key fingerprint、endpoint 和受审计 enrollment event 的关系。

runner root 与 `shared` 受 owner/mode 约束，所有 activation private directories 必须为当前 UID、同一 device、
精确 `0700`；已有目录也总是 `fsync(child)` 再 `fsync(parent)`，补齐前一进程可能留下的 mkdir durability
window。`/proc/self/mountinfo` 的最深唯一 mount、`st_dev` major:minor 与 `fstatfs` magic 必须互相一致，首版
只接受精确 `ext4` 或 `xfs`；OverlayFS、NFS、tmpfs、CIFS、FUSE、歧义或未知 mount 均 fail closed，且没有
override。

稳定 `shared/global-activation.lock` 是当前 root 下所有 enrollment 与 activation mutation 共用的唯一 gate：
文件必须为当前 UID、regular、`0600`、`nlink == 1`，以 nonblocking `flock` 持有到 session 最后关闭，永不
unlink。任一 phase record 或 activation entry 已存在时，缺失 gate 都不能重建。
本阶段尚未把 v5 bootstrap/rotation/uninstall 接到这个 gate；在接线前，旧 version-scoped install lock
不能被描述成等价的全局授权。

Registration journal 使用固定 20 位 revision 文件名与随机 128-bit 私有 staging 名。写入顺序为
`O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`、精确 `0600`、完整 write loop、file `fsync`、staging
directory `fsync`、`renameat2(RENAME_NOREPLACE)`、source/destination directory `fsync`、nofollow 重开并
逐字节复核。`EEXIST` 只有在 final 的 regular/UID/mode/nlink/size、canonical bytes、revision、predecessor
以及完整 journal prefix 全都精确时才接受；任何明确不支持的 flag/跨设备错误都 fail closed，其他 rename
结果、rename 后的任一失败，或 publication 已返回后 canonical root/journal 无法再次证明，都进入
`outcome_unknown`，不能推断“没有提交”。Reconcile 必须重新取得全局
gate，补齐两个 directory `fsync`，再从全部 immutable revision 文件重建 registry；缺失是 typed non-success，
同 ID 漂移是永久 conflict。`.staging` orphan 不参与 registry，未知 journal entry 则直接拒绝。

返回对象刻意命名为 append observation，只含 `created | reconciled_exact | already_registered_exact`、
installation fingerprint、registration revision/fingerprint 与完整 registry head revision/fingerprint；它不是 generation publication
receipt，也不能被 transition 当成 `prepared`。当前 generation v1 只有 release archive SHA，尚无 installed
release-tree manifest identity；在该缺口和 versioned key material 实际 owner/mode/nlink/bytes 证明补齐前，
generation directory publisher 与 production wiring 都是 stop condition。

下一最小切片只定义 dormant 的 `h2ometa.runner-installed-release-tree-manifest.v1` 纯合同，不改
generation v1，也不实现解包、filesystem walk、publisher 或远端 mutation。合同用固定 materialization policy、
只读 root/entry mode、严格递增的 canonical printable-ASCII relative POSIX path，以及显式
directory/file/symlink/internal-hardlink 语义构造 tree content fingerprint；完整 manifest 再使用独立 domain
产生 manifest fingerprint。Archive SHA、installation/path、source/platform、provenance 与 publication receipt
继续是不同证据，不能被塞入 tree digest 后宣称本地安装已证明。自洽 manifest 只证明 record identity，
不证明它来自实际 tree。

当前 `runner_lifetime_launcher._prepare_bundled_runtime()` 会在首次启动时于 release tree 内运行
`conda-unpack` 并写 `.h2ometa-conda-unpacked`；relocation 还可能把绝对 runtime prefix 写入实际文件。因此
“在 staging fixup 后 rename 到 post-fixup digest path”可能固化 staging prefix，而“发布后再 fixup”会立即
破坏 tree identity。conda-pack 官方文档明确：默认 archive 在目标位置执行 `conda-unpack` 后不能再次搬迁；
`--dest-prefix` 则在打包时绑定精确 absolute destination，并且不会生成 `conda-unpack`，所以它也不是可在任意
digest path 解包的通用方案。

当前推荐 publisher 方向是先选择并保留 opaque、永不复用的真实 final path，在该确切路径完成 extraction、
relocation、实际 bytes verification、只读 chmod、canonical manifest 构造以及 file/directory `fsync`；最后以
位于 release tree 之外的 durable no-replace marker 提交。Marker 前该目录不具 authority，marker 后不得再写。
Publisher 仍是明确 P0 stop condition；实现可以与 versioned key store 并行，但 generation publisher 必须等待
二者都完成。无论最终选该方向还是 relocation-free artifact，都必须移除 startup-time `conda-unpack` 与对
mutable `current/runtime` 的执行依赖后，才可进入 production wiring。

2026-07-18 的发布路径复核发现，启动期写入不只来自 relocation。`process_pid_file.py` 仍把
`runner.pid` 放在 installed release root，`run.py`、`check_service.sh` 与 `stop_service.sh` 会创建或删除它；systemd
unit 和后台启动脚本仍通过可变的 `current` 选择 executable path。因此“删除 `conda-unpack` 调用”本身不能证明
tree immutable 或 startup zero-write。PID、owner、socket、日志和 runtime state 必须全部进入
`shared/runtime` 等 dynamic namespace，unit 最终必须直接绑定已经权威验证的 exact real release path；
`current` 只能作为 committed 后的诊断投影，不能授权执行。

本轮 architecture-track 的下一实现切片是 dormant publication foundation，而不是修补 legacy shell deploy：

- 每次发布使用 128-bit lowercase hex `publicationId`，唯一派生
  `release-objects/<publicationId>`；调用方不能提供 descendant path，已用 ID 永不重用；
- tree 外的 exact intent 绑定 installation fingerprint、artifact version/platform、archive SHA/size、内嵌
  `bootstrap_manifest.json` 的 semantic fingerprint、provenance fingerprint，以及固定
  materialization/extraction/relocation policy；
- external manifest 与最终 receipt 分别 durable no-replace 保存；receipt 冗余校验 intent fingerprint，并绑定
  actual tree content/manifest fingerprint 与本地 root dev/inode。Intent、manifest 或自洽 receipt 单独存在都
  不是 `prepared`，marker/receipt 后仍需完整 tree reproof；
- 固定 namespace 为 runner root 下 `release-objects` 与
  `shared/activation/release-publications/{.staging,intents,manifests,markers}`，全部由已持有 global gate 的
  activation session 锚定；dynamic tree entry 只允许使用固定 `openat2` resolve policy 打开；
- `openat2` 必须同时使用 `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
  RESOLVE_NO_XDEV`。后者明确覆盖 bind mount；`ENOSYS`、不支持的 ABI/flag 或 `EXDEV` 都 fail closed，不得退回
  path check + `openat`。Required Ubuntu CI 会创建真实 bind mount，并要求该 child open 精确返回 `EXDEV`；
- 每个 unique file、每层 directory 与两个 external record parent 都要按顺序 `fsync`。Linux 的文件 `fsync`
  不保证 containing directory entry 已持久化，所以任何省略父目录 `fsync` 的 marker 都不能成为 authority。

该 foundation 不解包 archive、不执行 artifact 内代码、不运行 relocation、不创建 marker，也不修改 protocol v5、
bootstrap、generation 或 systemd。安全 extractor 仍必须预扫并拒绝 duplicate/prefix collision、special file、
symlink/hardlink escape、容量炸弹与未政策化 metadata；relocation 必须在 final path 完成且证明没有存活后代或
遗留 writable fd。Fresh session 绝不能领养 markerless partial tree：它只能被标为 abandoned 并由新的
publication ID 重试。Marker rename 后结果未知则只能通过 external records 与完整实际 tree 的 exact reproof
化解。

2026-07-18 的 exhaustive archive 专项研究进一步固定了下一层边界：Python `tarfile` 只能用作未来 inspector
的 bounded parser/regular-payload reader，authority publisher 永不调用 `extract`、`extractall`、
`shutil.unpack_archive` 或 shell `tar`。PEP 706 与 Python 文档明确说明 filter 不覆盖 DoS，异常还可能留下 partial
tree；GNU tar 与 libarchive 也把 absolute/dotdot、symlink、overwrite 和可信空目录作为独立控制面。

首个 dormant archive contract 因此只描述 inspector 应产出的 normalized record：它精确绑定 compressed archive
SHA/size、inspector 实测的 decompressed tar-stream bytes、`tar+gzip`、extraction policy、member/byte summary，以及
有序的 directory/file/symlink/hardlink 图。它封闭 printable-ASCII path、显式 parent、duplicate/prefix collision、
source mode、regular content SHA、内部 link graph、aggregate canonical member bytes、完整 canonical manifest bytes、
raw stream 绝对上限和基于 raw stream 的 compression ratio。Tar header、padding、PAX/GNU long-name 因此不能再以
tiny payload 绕过容量政策。Graph 复用不产生 fingerprint 的纯 release-tree entry validator，不为临时校验构造并
散列第二份大 manifest。

Record 还内嵌从固定 regular member `bootstrap_manifest.json` 解析出的 exact normalized semantic object、raw-content
SHA-256 与 domain-separated fingerprint。共享 core contract 将 raw JSON 限为 1 MiB，拒绝 duplicate key、non-finite
number 与非法 UTF-8，并封闭 service/version/platform、bundled runtime 与 runner protocol；startup preflight 和未来
inspector 共用既有 `h2ometa.remote-runner.startup.bootstrap-manifest.v1` domain。Publication intent 升级为 v2：
保留独立 `bootstrapManifestFingerprint`，另设 `archiveInspectionManifestFingerprint`；binding 同时比较两者、
version、platform、archive digest/size 与 policy，不再重载一个字段表示两份文档。Raw UID/GID、mtime、PAX、
sparse、device、xattr/ACL/capability 等不能由调用方在 normalized record 中自证；未来真实 inspector 必须先从
held archive fd 拒绝任何非政策 raw metadata，再构造该 record。自洽 record 仍不是 archive observation、tree
authority 或 `prepared`。

Extraction policy v1 的 raw envelope 现固定为 POSIX.1-1988 USTAR，header 必须使用 exact USTAR magic/version；
UID、GID 与 tar mtime 必须为零，uname/gname 必须为空，devmajor/devminor 必须为零。允许的 semantic member
仍只有 regular file、directory、symlink 与 hardlink；GNU `L`/`K` long-name/long-link、PAX local/global header、
GNU sparse、device、FIFO 及任何 special/unknown type 全部拒绝。USTAR 表达不了的 path 或 numeric field 必须让
builder 失败，不能退回 GNU/PAX extension。Raw name normalization 只允许 directory member 精确移除一个末尾
`/`，再应用既有的单个 root header 与单次前导 `./` 规则；重复 slash 或二次清理仍是 hard failure。
mode、UID、GID、size 与 mtime 必须使用固定宽度、前导零 octal digit 与末尾 NUL；inactive
devmajor/devminor 必须全 NUL。Checksum 必须精确使用六位 octal、NUL、space，regular typeflag 必须精确为
`0`，不接受数值等价的空格编码或 legacy NUL typeflag。

Gzip envelope 同样封闭：只接受一个 member、zero MTIME 且 `FLG == 0`；FEXTRA、FNAME、FCOMMENT、FHCRC、
reserved FLG、第二个 concatenated member 以及 gzip member 后任意 trailing bytes 全部拒绝。Inspector 必须读到
compressed EOF 并验证 CRC/ISIZE，不能把 gzip parser 停止位置当作 archive EOF。

成功 inspection 返回的 held-FD capability 是 single-owner、不可 copy/deepcopy/pickle 的进程内对象；所有状态转换
由同一把锁串行化。`F_DUPFD_CLOEXEC` 返回后，主线程只在“duplicate → owner”交接期临时延迟 SIGINT，并立即把
descriptor 交给 CPython 3.12+ 原生 `_io.FileIO(closefd=True)`；非主线程不会执行 Python signal handler。
Capability、外层失败清理与 `_io.FileIO` deallocator 共享同一个 owner。CPython 的 C 实现在释放 GIL 调用
`close(2)` 前先把 owner 内部 fd 设为 `-1`，因此关闭异常或 `KeyboardInterrupt` 不会留下可再次关闭的旧 fd 编号；
不再用 Python close-state 或 per-thread `pthread_sigmask` 冒充原子所有权。
它不向后续阶段泄露 owned FD，只提供在锁内前后重证的 positional read。Descriptor 一旦被采纳，任何失败在分类前都必须再次重证；storage drift/不可用
强于 archive rejection，而 cleanup failure 绝不能把 with-body 的 `outcome_unknown` 降级。公开固定错误同时清空
exception cause/context，不能从异常对象取回 errno、path 或 raw policy detail。

Archive graph 现在还导出唯一的 runtime-only pre-relocation materialization projection。它只能从完整重验的
archive manifest 派生，按 canonical path 排序，并为每个 lexicographically first canonical file 增加
`payloadSourcePath`；该字段精确指向保存 bytes 的 raw USTAR regular member。每个 raw regular payload 恰好被
消费一次，directory、symlink 与 hardlink 的该字段为空。若 raw file `z-file` 的 hardlink alias 在排序上更早，
alias 成为 canonical file、从 `z-file` 消费 payload，而 `z-file` 成为指回 alias 的 hardlink。投影去掉
`payloadSourcePath` 后复用既有 tree-content fingerprint domain，但这只是逻辑 source-tree identity，不是文件系统
observation、portable plan、receipt、marker 或 authority；`payloadSourcePath` 本身也不进入 tree identity。

该区分对 conda relocation 是硬边界：final-path relocation 可以合法改变部分 regular file 的 bytes 与 size，
因此 archive content hash 不能直接冒充 final-tree hash。未来 portable relocation evidence 必须同时绑定 archive
inspection manifest、这份确定性 source projection、relocation 的精确 pre/post observation 与 seal 后 fresh-walk
final tree。该 evidence 和 receipt vNext 未完成前，不得创建 authority marker、宣称 `prepared` 或接入 production。

旧 0.1.1 bundle 的只读采样含 1,175 个 symlink 与 3 个 hardlink，因此简单拒绝全部 link 会破坏真实 conda
环境；安全策略改为完整内部图解析。Raw archive hardlink 可指向任意 regular primary；进入 installed-tree 合同前，
每个 inode-alias group 都重写为 lexicographically first path 是唯一 canonical file，其余路径 hardlink 到它，从而
避免同一实际 tree 有两份 identity。该旧包还含 242 个非政策 mode 与 legacy
`.h2ometa-conda-unpacked`，只能作为 link-topology 样本。当前声明的 0.1.5 包也尚未通过：conda-pack 0.9.1
生成的 `runtime/bin/conda_unpack_progress.py` 是 `0600`；bootstrap JSON 还含 legacy `build` object，缺少 required
`runnerProtocol`/`runnerProtocolFingerprint`。仓库内的 artifact builder 现已在打包前把 non-executable file
确定性规范化为 `0644`、executable file 与 directory 规范化为 `0755`，并输出 exact current bootstrap contract。
它还以 `umask 077` 构建，使用固定 USTAR、name sort、zero owner/group/mtime 和 `gzip -n` 的单 member pipeline；
`set -o pipefail` 保证 USTAR path 超限或 tar 失败不会产出成功结果。0.1.5 以及所有在该 envelope policy 前生成的
已发布 archive 都必须由当前 builder 重建，不能 grandfather 为验收候选。Raw-name 兼容只允许忽略一个 root
`.`/`./` header，并从 member name/hardlink target 精确移除一次前导 `./`；directory name 另可精确移除一个
末尾 `/`。禁止 `strip("./")`、重复 prefix/slash 清除或改写 symlink target。

Materializer 仍必须先 reserve 永不复用的 real final path，在该 path 内逐 member fd-relative 创建，最后创建
link，原地完成 conda relocation，然后 seal/fsync/fresh-walk/marker-last。本轮仍不接 bootstrap 或 generation。

首个 fd-relative 实现切片只共享 release-tree entry component validator，并增加 dormant dynamic-directory
`openat2` contract boundary。它固定使用 directory-only flags 与
`RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV`；只有 `EAGAIN`
允许最多三次完全相同的调用，`ENOSYS`、`EINVAL`、`E2BIG`、`EOPNOTSUPP`、`EXDEV`、`ELOOP`、
`ENOTDIR` 与 `EINTR` 均立即失败，绝不回退到 path check、`open` 或 `openat`。

Contract suite 通过 injected syscall boundary 证明 validation、call shape、retry budget、post-open check 与
no-fallback；required Ubuntu activation-storage job 另以真实 syscall 证明 dynamic child identity、
non-inheritance、final-symlink fail-closed refusal 与 bind-mount `EXDEV`。受支持 kernel 可能由
`RESOLVE_NO_SYMLINKS` 返回 `ELOOP`，也可能由组合的 `O_DIRECTORY | O_NOFOLLOW` 检查返回 `ENOTDIR`；
两者均未打开 target。这只构成 required CI platform 的 kernel evidence，不外推到未经测试的
architecture、kernel、mount 或 production runner host。

Required-platform 验收证据为 GitHub Actions
[run 29624601618](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29624601618) 的
`python / activation-storage-linux` job，source 为
`21034548deac586e5935cf8a46fbc5c7fe295ed4`：Ubuntu 24.04 / Linux 6.17 x86_64 上 574 passed、
6 skipped。首次 run 还暴露并推动了 partial key-layout cleanup 与 archive ancestor-replacement fixture
的独立修复；上述成功 job 已包含两项修正。

该 Python 入口刻意命名为 `raw_fd`，不构成 production capability。`O_CLOEXEC` 只防 `execve` 继承，
不能回收当前进程内在 syscall/return handoff 被异步异常遗弃的 descriptor；CPython `_io.FileIO` 又会拒绝
directory fd，因此 archive regular-file 的 native-owner/SIGINT 证明不能套用。Materializer 若要 retained
directory capability，必须先实现“同一次 C-level 调用完成 openat2→native owner 且 deallocator 负责 close”，
或者把全部目录操作限制在关闭后才返回的同步 SIGINT-deferred stack scope。当前 raw-fd 入口不接 startup、
publication 或 generation authorization。

这份 journal 路径只解析 installation 派生的固定组件，不接受调用方提供的任意 descendant path。后续
release-tree/generation directory publisher 若需要解析动态嵌套路径，必须以经过目标 architecture 与 kernel
证明的 `openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV)`
或受控构建的窄 native helper 实现；不得在 `openat2`/ABI 不可用时退回 path check + rename。

Windows 测试只证明 canonical journal orchestration、错误分类与故障状态机，不冒充 Linux syscall 证据。
CI 新增不可跳过的 Ubuntu activation-storage job，在 `$RUNNER_TEMP` 记录 mount 信息并真实运行 global gate、
`renameat2`、EEXIST exact、file/directory `fsync` 与 rename 后 crash-reconcile；`ci-green` 对该 job 只接受
`success`，不接受 `skipped`。这仍不是硬件撒谎、真实断电或生产远端 mount 的证明；production enablement
前还必须在 exact runner mount 上做 release acceptance，必要时另用受控 block-device fault test。

当前 transition v1 不消费这份 dormant registry，因此不能宣称 generation 已获得 registry authorization。
后续 generation-aware protocol/transition 版本必须同时绑定启动前完整 registry fingerprint、target 的精确
registration fingerprint 与启动前 Invocation ledger fingerprint；三者都必须来自全局 gate 下对可信 journal
的重读，不能由调用方提供一个内部自洽但可能截断的 prefix。

HMAC 解决 evidence 泄露后的低熵 secret 离线猜测 oracle，不宣称抵抗同 UID 或 root compromise，也不
防 rollback replay；后者仍由 append-only journal、ledger 与 activation gate 负责。Release archive 的
raw digest 也不自动证明解包执行树；未来 release publisher 无论采用 relocation-free directory publication
还是 final-path marker commit，都必须以严格 tree manifest 对实际文件逐项重证。

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

1. 旧 generation 的 config HMAC、profile/unit/release fingerprints 全部匹配；
2. 它以一个新的唯一 unit 和新的 `InvocationID` 启动；
3. systemd `MainPID`、procfs incarnation、cgroup 与 owner record 一致；
4. 使用旧 generation 对应 credential 完成认证 ready；
5. lifecycle guard 由本次 activation 的精确 owner 释放。

任何一项未知都让失败 activation 保持 `recovery_required`，不得以布尔值或 `current` 指针宣称恢复成功。
后续 rollback 的成功事实属于新的 committed activation，不改写原失败链的历史终态。

## 文件与选择器

目标布局是 generation 与 transaction 分离：

```text
~/.h2ometa/runner/shared/
  global-activation.lock
  installation-enrollment-intent.json  # 与 final 互斥的 phase name
  installation-enrollment.json
  activation/
    .staging/
    generation-registrations/
      .staging/
      <revision>.json
    generation-registry.json  # registrations 重建出的 canonical read model
    secrets/                  # key operation 按需建立，不属于 enrollment skeleton
      config-integrity/
        .staging/<configBlobIntegrityKeyId>.pending
        <configBlobIntegrityKeyId>.key
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

目录在写入 secret-bearing config 前必须为 `0700`，配置文件为 `0600`。完整 config 使用独立 key 的
HMAC 绑定实际 canonical bytes；credential-free runtime-config fingerprint 由严格字段分区后的规范
payload 计算，使 token rotation 无法夹带端口、路径或 runtime policy 变化。Generation 只有在所有文件、
tag、digest 和 protocol preflight 验证成功后才可成为候选。`current.json`/`current` 只在 durable
`COMMITTED` 后更新，供诊断、UI 和人工导航使用；运行时不把它当信任根。

单个本地文件的发布继续使用临时文件、fsync、rename 与父目录 fsync；这只保证该文件的替换语义，
不扩张为跨文件或 systemd 的原子性声明。`flock` 只提供同一主机、同一稳定本地文件系统上的协作互斥，
不是分布式 fencing 或对恶意同 UID 进程的隔离。

## 分阶段落地

1. 先稳定 generation/transition/systemd observation、Invocation reservation ledger 的严格契约、canonical
   fingerprint 与状态机；保持 protocol v5 和所有旧 production mutation 路径不变。
2. 先持有永不移除的 `shared/global-activation.lock`，再以 intent no-replace CAS 选定 installation；相同
   identity 可从 intent-only 崩溃态幂等补齐精确空白 skeleton。完整 root/child capability proof 后将 intent
   inode 原子晋级为 final-only；final 后不重建缺失 child/gate。此阶段只提供 dormant authority primitive。
3. 先定义 pinned materialization policy 与 installed release-tree 纯 identity contract；它不构成 storage
   observation、publisher receipt 或 `prepared` evidence。
4. 并行推进两个独立依赖：(a) 消除 startup-time relocation/write，以 opaque 永不复用真实 final path 加树外
   no-replace marker（或经证明的 relocation-free artifact）实现 installed release-tree publisher；(b) 按 dynamic
   scoped directories、deterministic pending 与 fresh-session reconcile 实现 dormant versioned config-integrity
   key material store。二者都未完成前不得发布 generation。
5. 只有 tree identity、key material、registration history 与 generation 实际 bytes 全部可重证后，才实现
   verified immutable generation publisher 和 durable `prepared` receipt。
6. 再实现 transition 与 Invocation reservation journals、unique unit start/stop、systemd 权威核验和完整
   crash-reconcile fault matrix。
7. Runner 捕获 activation 与 systemd 自观察，owner/runtime state 加入 end-to-end binding；全部前置证据被
   startup 消费后才整体升级 protocol v6，并为 unit 加入对应 restart-preventing exit status。
8. 最后把 bootstrap、token rotation、rollback、stop、prune、uninstall 全部接到同一 lifecycle gate，删除
   广泛 `pkill`、in-place config mutation 和其他 legacy branch 后才可重新启用 staging deploy。
9. Linux CI 证明真实 user-systemd；存在 cgroup v2 时额外核验 `cgroup.events populated=0`，存在 pidfd 时
   增强 exact liveness，但二者均不是最低兼容依赖。

## 非目标

- 本阶段不宣称抗 root 或同 UID compromise；更强隔离需要独立 service user 与 root-owned release/unit。
- 不用 PIDFile、进程名或监听端口替代 activation 身份。
- 不把 `sd_notify`、pidfd 或 cgroup 当作 API token。
- 不在契约未被生产路径消费前提前发布 protocol v6 capability。
- 不把 background-process 模式描述为具备 systemd 等价证据；其支持策略在接线阶段单独决策并明确失败面。

## 官方依据

- [本阶段 activation storage trust-root 深度研究与完整来源](../research/2026-07-17-runner-activation-storage-trust-root.md)
- [systemd.exec：`INVOCATION_ID` 与 v232 边界](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [systemd D-Bus API：`InvocationID`、`MainPID`、`ControlGroup` 与 unit jobs](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html)
- [systemd.service：`Type=notify`、MainPID 与 watchdog](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd.kill：`KillMode=control-group`](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html)
- [sd_notify：READY 归属与通知语义](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
- [Linux pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)
- [Linux open/openat(2)：`O_EXCL`、`O_NOFOLLOW` 与 dirfd](https://man7.org/linux/man-pages/man2/open.2.html)
- [Linux openat2(2)：受限路径解析与 Linux 5.6 边界](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [Linux rename/renameat2(2)](https://man7.org/linux/man-pages/man2/rename.2.html)
- [Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux write(2)：partial write 与延迟错误](https://man7.org/linux/man-pages/man2/write.2.html)
- [Linux close(2)：close 非 durability proof 且不可盲目 retry](https://man7.org/linux/man-pages/man2/close.2.html)
- [CPython 3.12 `_io.FileIO`：先失效内部 fd，再释放 GIL 执行 close](https://github.com/python/cpython/blob/v3.12.10/Modules/_io/fileio.c)
- [Python signal：handler 只在主线程执行](https://docs.python.org/3/library/signal.html)
- [Linux getrandom(2)：内核 CSPRNG 初始化与阻塞语义](https://man7.org/linux/man-pages/man2/getrandom.2.html)
- [Linux statfs/fstatfs(2)：filesystem magic](https://man7.org/linux/man-pages/man2/statfs.2.html)
- [Linux proc mountinfo(5)：mount ID、device 与 filesystem type](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)
- [Linux ext4 journal：metadata transaction 与 data modes](https://docs.kernel.org/filesystems/ext4/journal.html)
- [Linux XFS delayed logging：异步 transaction 与 fsync](https://docs.kernel.org/filesystems/xfs/xfs-delayed-logging-design.html)
- [Linux OverlayFS：copy-up、rename 与 fsync modes](https://docs.kernel.org/filesystems/overlayfs.html)
- [in-toto ResourceDescriptor：artifact content digest](https://github.com/in-toto/attestation/blob/main/spec/v1/resource_descriptor.md)
- [SLSA build provenance：subject、resolved dependencies 与 external parameters](https://slsa.dev/spec/v1.2/build-provenance)
- [RFC 8785：JCS 的 I-JSON、number 与 property ordering 约束](https://www.rfc-editor.org/rfc/rfc8785.html)
- [RFC 5869：HKDF extract/expand 与 context separation](https://www.rfc-editor.org/rfc/rfc5869.html)
- [NIST SP 800-108r1：HMAC KDF 与 FixedInfo domain separation](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-108r1.pdf)
- [Python secrets：OS CSPRNG 与 compare_digest](https://docs.python.org/3/library/secrets.html)
- [conda-pack：目标端 `conda-unpack` 与执行后不可再次搬迁](https://conda.github.io/conda-pack/)
- [conda-pack CLI：`--dest-prefix` 精确路径绑定且不生成 `conda-unpack`](https://conda.github.io/conda-pack/cli.html)
- [conda-pack 0.9.1 source：generated text file mode](https://github.com/conda/conda-pack/blob/0.9.1/conda_pack/core.py)
- [Python tarfile：extraction filter 与 installed-tree 差异](https://docs.python.org/3/library/tarfile.html)
- [PEP 706：tarfile extraction filter 的政策边界](https://peps.python.org/pep-0706/)
- [POSIX pax archive semantics](https://pubs.opengroup.org/onlinepubs/9699919799/utilities/pax.html)
- [GNU tar manual 与 archive security guidance](https://www.gnu.org/software/tar/manual/tar.html)
- [libarchive extraction option boundaries](https://github.com/libarchive/libarchive/blob/master/libarchive/archive_read_extract.3)
- [Linux `openat2`：beneath、nofollow、no-magiclink 与 no-xdev resolve policy](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [Linux `fsync`：文件与 containing directory 的独立持久化边界](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [systemd credentials：unit-scoped credential custody](https://systemd.io/CREDENTIALS/)
- [Python keyring：get/set/delete 公共 API 与错误语义](https://keyring.readthedocs.io/en/latest/)
- [Windows CredWrite：同名 credential 的替换语义](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credwritew)
- [Secret Service：CreateItem 的显式 replace 语义](https://specifications.freedesktop.org/secret-service/latest-single/)
- [Apple Keychain：secret 与公开 searchable attributes](https://developer.apple.com/documentation/security/keychain-items)
- [systemd.unit：fragment、drop-in 与 load path 组合语义](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
- [systemctl：`cat` 读取磁盘 backing files，不代表 manager 已加载状态](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html)
- [Nix profiles：不可变 generation 与原子 selector](https://nix.dev/manual/nix/latest/package-management/profiles)
- [OSTree atomic upgrades：先构建 deployment，再切换 selector](https://ostreedev.github.io/ostree/atomic-upgrades/)
