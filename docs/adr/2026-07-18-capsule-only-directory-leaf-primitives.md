# ADR：Capsule-only 目录叶原语

- 日期：2026-07-18
- 状态：Accepted for dormant proof only
- 关联研究：[Capsule-only directory leaf primitives 深度研究](../research/2026-07-18-capsule-only-directory-leaf-primitives.md)
- Production baseline：`origin/main` @ `cb9266b6e2d32193f657d3de002b0aff14524f3d`
- Active branch baseline：`codex/remove-first-run-wizard` @ `5880b2e43c4385c84e69ed656b076c2814816f9f`

## 决策卡

```text
Decision: 在 quarantined production wheel 与独立 identity 的 proof wheel 中增加 _mkdir_child 与 _fsync_directory 两个 capsule-only 目录叶原语
Track: architecture-track
Baseline: origin/main @ cb9266b6e2d32193f657d3de002b0aff14524f3d; active branch @ 5880b2e43c4385c84e69ed656b076c2814816f9f
Why now: retained directory fd owner 已获 required Ubuntu job 证明，但 materializer 仍缺少不泄露 fd 的 mutation leaf
Accepted constraints: Linux x86-64；CPython 3.12 Limited API；无 raw fd、path、callback 参数、主动 application callback、fallback、root seed 或 runtime consumer；只允许已记录的 CPython signal-dispatch point
Rejected alternatives: 完整 materializer、Python raw-fd bridge、openat fallback、EEXIST adopt、同 ID cleanup/retry、当前阶段的 file/link/marker
Ownership split: integrator 负责 baseline/commit/push；scout 只读审查 source split、CPython ownership 与 Linux syscall 语义
Proof required: Windows contract/validator；Ubuntu build + abi3audit + standard-GIL CPython 3.12/3.13/3.14 functional behavior matrix
Stop conditions: apps/core 出现 consumer；需要 production root seed；需要 file/link/marker；source >=800；wheel 被 upload/bundle；required native job 未成功
Cleanup: 删除本阶段 .firecrawl/capsule-leaf-research 与 pytest/cache/build 临时物；不触碰 unrelated user files
```

## 背景

当前 native extension 已能在一次 C 调用内完成
`openat2 -> capsule owner`，并以 destructor 回收 descriptor。Production module
没有 root seed，proof module 才能从测试 fd 建立初始 capability；两个 wheel 均不进入 remote-runner
source-copy、bundle、startup 或 release asset。

Python 的 `activation_release_materialization_io.py` 仍是刻意命名的 `raw_fd` proof，不能成为 retained
production capability。Archive inspector 虽然持有 regular-file capability，却只提供 positional read；archive
projection 也只是 pre-relocation logical topology，不是 filesystem plan、receipt、marker 或 authority。

因此下一步只证明“如何从一个 live directory capsule 创建并持有一个新 child”和“如何对一个 live directory
执行单次 durability syscall”，不开始完整 extraction。

## 决策

下一 private wheel 版本为 `0.1.1`，production surface 精确变为：

```text
_open_child
_mkdir_child
_fsync_directory
_require_live
_close
```

仍禁止：

- root seed、raw fd、`fileno`、borrow/take；
- 任意 path open、path check、`open`/`openat` fallback；
- Python callback 参数、主动 application callback、iterator、replay；
- unlink、rename、hardlink、symlink、marker；
- archive payload、relocation、receipt、publication 或 generation 接线。

Production 与 proof 继续使用不同 distribution、module、`PyInit_*` 与 capsule name；test hook 不得进入
production binary。两个 wheel 只在 CI `RUNNER_TEMP` 构建、验证、import 后丢弃。

## `_mkdir_child` 不变量

接口固定为：

```text
_mkdir_child(parent_directory_capsule, exact_component) -> directory_capsule
```

调用顺序固定为：

1. 验证 exact capsule 与 exact `str` 单组件；拒绝非 printable ASCII、`/`、`\`、`.`、`..`、首尾空格、
   `.h2ometa-` reserved prefix 与超过 255 bytes。
2. 在 mutation 前重证 parent 的 live fd、device/inode、UID、directory policy 与 CLOEXEC。
3. 在 mutation 前分配 `fd=-1` 的 owner 和 capsule；内存分配失败不得留下目录。
4. 直接调用 Linux x86-64 `SYS_mkdirat(parent_fd, component, 0700)` 一次。该选择用于 closed-binary
   no-fallback 静态审计，而不是声称受支持的 `openat2` kernel 仍会触发旧 glibc fallback；source 必须
   `#if !defined(SYS_mkdirat)` fail build，并 `_Static_assert(SYS_mkdirat == 258)`。`EEXIST` 对 existing
   file、directory 或 symlink 一律失败，绝不 adopt。
5. 用既有 exact `openat2` flags/resolve 重开 child。只有 `EAGAIN` 可按完全相同 shape 总计最多三次调用
   （首次加最多两次 retry）；
   `EINTR`、`ENOSYS`、`EINVAL`、`E2BIG`、`EOPNOTSUPP`、`EXDEV`、`ELOOP`、`ENOTDIR` 均立即失败。
6. syscall 一返回 fd 就立即写入预分配 owner，再进行任何可能失败的检查。
7. 以 descriptor `fchmod(0700)`，随后重证 exact mode、directory、same UID、same device、stable
   device/inode 与 CLOEXEC。
8. `mkdirat` 发出后，每条失败出口都先保存原始结果并重证 parent；fd adoption 后还必须重证 child，且
   identity failure 优先于原始 syscall error。返回成功前同样重证 parent 与 child。

方法不接受或主动调用 application callback，也不释放 GIL或显式调用 `PyErr_CheckSignals`。但
`PyErr_SetFromErrno(EINTR)` 会间接执行 `PyErr_CheckSignals`，因此 errno conversion 前 owner/fd/namespace
状态必须已经一致；signal handler 即使在这里抛异常，也只能得到 owned fd 或 `fd=-1`。

`mkdirat`、`fchmod` 与 close 均不因 `EINTR` retry。创建后任何失败都可能留下 private、markerless orphan；
返回失败时 capsule destructor 只负责 fd leak safety，不删除目录。上层必须把该 opaque ID 标为 abandoned，
不得自动 reopen/adopt、删除后复用或宣称成功。

## `_fsync_directory` 不变量

接口固定为：

```text
_fsync_directory(directory_capsule) -> None
```

调用顺序为 `live proof -> one fsync -> post-proof`。`fsync` 不 retry；post-proof 若失败，identity failure
优先于已保存的 syscall error，否则返回原始 `fsync` 结果。成功只说明该 descriptor 对应 directory 的这次
sync syscall 成功，不说明 containing parent entry、整棵树、block device cache 或 marker 已 durable。

未来 orchestrator 必须自底向上 sync mutated directories，并显式 sync containing parent。Unsupported
directory fsync 是 mount acceptance failure，不允许忽略或降级。

## 为什么不合并成 durable 方法

`_mkdir_child_durable` 曾被认真考虑：它可在一次 C 调用内完成 mkdir、adopt、chmod、child fsync 与 parent
fsync，从而减少两个 Python 调用间的 cancellation window。

本阶段仍选择两个 leaf，因为合并方法也不是 atomic transaction：任意 post-mkdir failure 都会留下 namespace
object，parent fsync failure 也只能 fresh-session reconcile。把它命名为 durable 容易让 caller 将多 syscall
成功误读为 authority。这里明确把不可安全跨 Python 表达的“fd acquisition -> owner”留在 `_mkdir_child`，
把可幂等、可单独证明的 sync 留在 `_fsync_directory`。未来 journal 若证明减少 cancellation point 更重要，
可以另加 native orchestration，但不得改变这两个 leaf 的语义。

## Source split

现有 `activation_release_dir_owner.c` 已 785 行，禁止继续增长。先做纯机械拆分，保持 `0.1.0` binary surface
与行为不变：

- shared internal header：常量、owner/test-state type 与内部 prototype；
- owner/core source：capsule allocation、identity、close、component、openat2；
- module source：Python methods、proof hooks 与 `PyInit_*`；
- directory leaf source：后续 `_mkdir_child`/`_fsync_directory`。

Production/proof setup 必须引用同一组受审 source；`-fvisibility=hidden` 与 validator 继续保证 dynamic export
只有对应 `PyInit_*`。每个 handwritten source 均小于 800 行。

## 分阶段提交与证明

### Commit A：机械拆源

- 不改 wheel 版本与 public surface；
- Windows contract/validator tests 通过；
- Ubuntu 两个 wheel build/import、既有 proof behavior 通过；
- 独立提交并 push 后才进入行为改动。

### Commit B：目录 leaf

- 增加两个方法，版本升到 `0.1.1`；
- validator 精确检查五个 production method，并禁止 `mkdir`/`mkdirat` libc symbol；
- standard-GIL CPython 3.12、3.13、3.14 均运行 ownership、error cleanup、real/injected syscall 与
  SIGINT/`sys.monitoring` return-boundary functional suite，而不只做 import；
- proof-only capsule-creation fault 在 owner allocation 后、namespace mutation 前复用真实 cleanup label，
  断言 `MemoryError`/`NULL`、owner alloc/free 平衡、destructor 未调用且没有 namespace mutation；静态合同同时
  固定 allocation/capsule/mutation 顺序；
- 每个 Python minor 都以 proof-only pending `SIGINT` + injected `EINTR` 覆盖 errno conversion 内部的
  signal dispatch，断言不 retry、handler exception 可取代原 errno、dispatch 前 owner/fd/namespace 一致、
  无 fd leak，并只把 mutation 后残留记为 markerless abandoned；
- production/proof wheel identity 与 init/capsule 隔离保持不变；
- exact component/no-replace、三类 `EEXIST`、direct `SYS_mkdirat`、mode/identity/CLOEXEC、bounded
  `openat2`、single `fsync`、destructor/double-close/fd-reuse 与 no-consumer 合同随行为提交一起通过。

### Commit C：required Linux evidence 记录

- 在 Commit B 已包含全部测试的前提下运行 required Ubuntu job；
- 记录 exact source SHA、runner image、Python matrix、wheel names、validator/abi3audit 与 test count；
- 记录 parent workflow 的真实结论，不把 isolated job success 写成 whole-CI 或 branch acceptance；
- 不修改 native source、tests 或 contract，只追加 Commit B exact SHA 的 evidence；
- 不 upload/bundle wheel，不新增 production wiring。

只记录 required native job 的真实结论。父 workflow 或其他 baseline job 失败时，不把 isolated job success
写成 whole-CI 或 branch acceptance。

## 延后事项

Regular file 需要独立 file capsule、create-only `openat2`、partial-write/offset state、fchmod/fsync 和 relocation
evidence。Hardlink 需要 canonical primary inode binding、alias group 与 `st_nlink` proof。Symlink 必须在完整
graph 验证后 last-create，并以 `readlinkat` 重证 exact target。三者均是后续独立 slice。

Authority 前还必须完成：ACL/xattr policy、trusted-root fresh reopen、full fresh walk、relocation pre/post
evidence、versioned receipt、marker-last、crash reconcile、artifact hash/SBOM/provenance 与 exact production
mount/runtime/glibc acceptance。

## 风险边界

- `0700`/`0555` mode 不能证明没有 named ACL、capability、SELinux label 或其他 xattr。
- Same-UID/root compromise 不在当前 local threat model；global lock 不是 MAC。
- 因此 mkdir 后 open 到的 inode 与刚创建 name 的绑定，只在排除 same-UID/root replacement 的现有 threat
  model 内成立，不得外推为 adversarial namespace proof。
- `RESOLVE_NO_XDEV` 会 fail-loud 拒绝全部 bind mount，可能影响部分部署布局。
- Retained dirfd 在 rename/detach 后仍有效，不等于 final pathname binding。
- CI `fsync`/crash simulation 不等于真实断电与硬件 cache 诚实。
- Markerless orphan 可能累积；未来 reclamation 必须 journaled、quota-bound 且永不复用 opaque ID。
- Stable ABI 不证明 architecture、libc、kernel、filesystem 或 behavior portability。

## 主要依据

- [完整深度研究与全部来源](../research/2026-07-18-capsule-only-directory-leaf-primitives.md)
- [CPython 3.12 Capsules](https://docs.python.org/3.12/c-api/capsule.html)
- [CPython 3.12 Stable ABI](https://docs.python.org/3.12/c-api/stable.html)
- [CPython 3.12 signal](https://docs.python.org/3.12/library/signal.html)
- [Linux mkdirat(2)](https://man7.org/linux/man-pages/man2/mkdir.2.html)
- [Linux openat2(2)](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [Linux fchmod(2)](https://man7.org/linux/man-pages/man2/chmod.2.html)
- [Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux close(2)](https://man7.org/linux/man-pages/man2/close.2.html)
- [Linux ACL](https://man7.org/linux/man-pages/man5/acl.5.html)
- [Linux xattr](https://man7.org/linux/man-pages/man7/xattr.7.html)
