# PRD — SSH 远程终端面板 v1

## Metadata
- Source: user-approved `ralplan` discussion on 2026-04-15
- Planning mode: `ralplan --consensus`
- Consensus status: Approved for phased execution
- Context snapshot: `.omx/context/server-nextflow-bootstrap-20260414T172423Z.md`
- Visual reference: user-provided screenshot on 2026-04-15 showing a top-right terminal icon and a full-width bottom terminal dock

## ADR

### Decision
在当前工作台壳层中新增一个 **绑定当前 SSH 连接的远程终端面板**：

- **入口位置**：右上角按钮
- **展现方式**：内容区底部的固定终端面板（嵌入式 dock，而非浮动 drawer）
- **布局机制**：上半部分主工作区 + 下半部分终端区，中间通过一条**可拖动横向分隔线**分割
- **启用条件**：仅在 SSH 成功连接后可用
- **v1 范围**：仅提供纯远程终端能力

### Drivers
1. 用户当前最缺的是“在产品内对远端 Linux 做手动干预/调试”的出口，而不是一开始就做全自动安装。
2. 当前代码中 `apps/web/app/components/ssh-shell.tsx` 已经是 SSH 状态与连接 UI 的中心，适合作为终端入口宿主。
3. 当前桌面层没有现成 terminal / PTY 插件能力，v1 应避免引入一套与现有 Python SSH 主路径割裂的原生终端方案。
4. 用户最新明确说明：追求的不是浮动“抽屉”，而是**嵌在内容区里的固定终端面板**，效果更接近 VS Code/Cursor 的上下分屏终端。

### Alternatives considered
1. **单独 Terminal 页面**
   - 拒绝：打断当前工作流，不如在工作台上下文内就地展开。
2. **本地终端 + 远程终端双模式**
   - 拒绝：当前需求明确只要远程终端，会显著增加复杂度与用户认知负担。
3. **快捷命令注入 / 安装按钮联动一起做**
   - 拒绝：会把“纯终端能力”与后续自动化能力耦合，放大 v1 范围。
4. **断开 SSH 时自动关闭终端 drawer**
   - 拒绝：会丢失现场输出，不利于用户理解断线与排错。

### Why chosen
这个方案最符合当前产品节奏：先补齐“远程手动能力”，为后续 runtime 安装、doctor 修复、日志排查提供产品内出口，同时尽量少改变现有 SSH 连接流程。

### Consequences
- 需要在现有 SSH 连接主路径上新增“交互式终端 session”能力。
- 需要在 Web UI 中新增一个全局但低侵入的 drawer。
- v1 不会覆盖更高阶终端能力（多 tab、文件管理、快捷命令、自动化安装联动）。

### Follow-ups
后续可增量扩展：
- 快捷命令注入
- runtime 安装按钮联动
- 更强的终端仿真能力
- 多 session / 多 tab

## Requirements Summary
在当前 `apps/web` 工作台中增加一个 SSH 远程终端入口：

- 用户连接成功后，可从右上角打开远程终端
- 终端以**内容区底部固定面板**形式出现
- 打开后采用 **上下分屏布局**
- 主工作区与终端区之间有 **可拖动的横向分隔线**
- 终端绑定当前 SSH 会话上下文
- 终端支持基本交互式 shell 输入与输出展示
- 断开 SSH 时，终端不自动消失，而是保留历史输出并进入断线态
- 布局观感应接近截图：**右上角小图标触发，内容区底部横向铺开的固定终端区域，而不是侧栏面板或浮层抽屉**

## Brownfield Evidence
- `apps/web/app/components/ssh-shell.tsx`
  - 当前已负责 SSH 状态拉取、连接/断开动作、连接对话框与顶层壳布局。
- `apps/web/app/components/app_shell.tsx`
  - 当前 Web 壳很薄，适合接入全局 drawer provider。
- `core/remote/ssh_service.py`
  - 当前项目已有 SSH 主路径与单队列执行能力，应优先复用，而不是另起平行 SSH 栈。
- `apps/api/main.py`
  - 当前已有 `/api/v1/ssh/status`、`/api/v1/ssh/connect`、`/api/v1/ssh/disconnect` 等 SSH 生命周期接口，可作为终端启用条件与状态来源。

## In Scope
1. 右上角终端按钮入口
2. 内容区底部固定终端面板 UI
3. 连接成功后启用 / 未连接禁用
4. 上下分屏布局与可拖动横向分隔线
5. 远程终端 session 的创建、输入、输出、关闭
6. SSH 断线态处理
7. 基本错误提示与状态反馈

## Out of Scope / Non-goals
1. 本地终端
2. 多 tab / 多 session UI
3. 快捷命令注入
4. 文件管理 / 端口转发
5. runtime 安装按钮联动
6. 完整 SSH 客户端能力复制
7. 不在本轮同时做多 tab / 文件树 / 端口转发等更大终端生态

## Decision Boundaries
OMX 可以自行决定：
- 终端按钮的具体图标样式
- drawer 的默认高度与最小/最大尺寸
- v1 输出刷新的技术形式（轮询优先即可）
- 断线态文案的具体措辞

OMX 不得自行扩展：
- 本地终端模式
- 多 tab
- 安装/修复快捷按钮
- 文件树/端口转发

## Product Behavior Freeze

### Entry & Availability
- 终端按钮放在**右上角工具区最右侧附近**，视觉上对齐用户截图中的终端图标位置
- 当 `SSHStatus.connected !== true` 时：
  - 按钮禁用
  - tooltip / 文案提示“请先连接远端服务器”
- 当 `SSHStatus.connected === true` 时：
  - 按钮可点击
  - 点击打开 drawer

### Panel Behavior
- 展示位置：内容区底部
- 默认隐藏
- 打开后采用**横向铺开的固定终端面板**，优先贴近截图效果：
  - 作为页面布局的一部分嵌在内容区内
  - 横向覆盖主内容区宽度
  - 不做右侧窄栏
  - 不做独立页面跳转
  - 不做浮动抽屉动画作为主要语义
- 打开后布局切换为：
  - 上：主工作区
  - 中：可拖动横向分隔线
  - 下：终端面板
- 支持用户手动关闭 / 隐藏
- **v1 需要支持拖拽高度**
- 关闭终端面板后恢复为单一主工作区布局

### Terminal Session Behavior
- 打开 drawer 时创建一个远程终端 session
- 输入命令后可看到远端输出
- session 与当前 SSH 连接绑定
- 关闭 drawer 时清理该 session

### Disconnect Behavior
- SSH 断开时：
  - **不自动关闭 drawer**
  - **保留历史输出**
  - **禁用输入**
  - 顶部显示“SSH 已断开，终端会话已结束”
- SSH 恢复后：
  - 不自动恢复旧 session
  - 用户需手动重新打开或创建新终端会话

## Architecture Direction

### Preferred shape
采用 **现有 Python backend 扩展终端 session 管理** 的方式，而不是在 Tauri/Rust 层直接新增独立 SSH/PTY 栈。

### Reason
- 更符合现有 `ssh-shell.tsx -> apps/api -> core/remote/ssh_service.py` 主路径
- 避免出现两套 SSH 连接语义
- 更适合阶段性交付

### Minimal backend capability needed
需要补一组终端 session 能力：
- create terminal session
- read terminal output
- send terminal input
- close terminal session

具体协议形式（轮询 / streaming）v1 可偏保守，优先保证稳定性。

### Preferred UI implementation
前端布局优先采用 **垂直 resizable panel** 思路实现：
- 父容器：内容区整体高度容器
- 上层：主工作区（`flex-1` / 主画布）
- 中层：可拖动横向 handle
- 下层：固定终端面板

实现目标是“像 VS Code/Cursor 那样的内容区内嵌终端”，而不是弹出式抽屉。

### Terminal rendering scope
本轮执行目标改为：
- 在固定底部终端面板中接入 **`xterm.js`**
- 输入直接发生在终端区域内部，而不是单独的表单输入栏
- 终端区与输出共享同一缓冲区语义，尽量贴近 VS Code / Cursor 风格

仍延后的内容：
- 更复杂 addon 组合
- 多 tab
- 完整文件/端口能力

## UX Copy Guidance
- 按钮名称：`终端` / `远程终端`
- drawer 标题：`远程终端 · 当前服务器`
- 断线提示：`SSH 已断开，终端会话已结束`
- 禁用提示：`请先连接远端服务器`
- 视觉参考：**按钮与 dock 布局优先贴近截图，而不是追求传统开发者 IDE 风格终端**

## Implementation Milestones
1. **M1 — Session contract**
   - 明确终端 session 的后端接口与状态机
2. **M2 — Shell UI integration**
   - 在 `ssh-shell.tsx` 中加入按钮与 drawer
3. **M3 — IO loop**
   - 实现输入/输出与历史展示
4. **M4 — Disconnect handling**
   - 实现断线态与 session 终止规则
5. **M5 — Validation**
   - 验证连接、断开、重开、错误处理

## Acceptance Criteria
1. 未连接 SSH 时，右上角终端按钮不可用。
2. 已连接 SSH 时，右上角终端按钮可显示内容区底部固定终端面板。
3. 打开终端面板后，用户可以输入命令并看到远端输出。
4. 输入直接发生在终端区域内部，而不是额外的独立输入表单栏。
5. 打开终端面板后，主内容区与终端区之间存在可拖动横向分隔线。
6. 用户拖动后，终端高度会跟随变化。
7. 关闭终端面板后，页面恢复为无终端的单层主工作区布局。
8. v1 不出现本地终端模式切换。
9. v1 不出现多 tab 终端。
10. v1 不出现快捷命令按钮或安装联动。
11. SSH 断开时，固定终端面板保留历史输出但输入被禁用。
12. SSH 恢复后，不自动恢复旧 session。
13. 终端入口与底部固定面板效果在视觉上能明显对应用户截图所示的“右上角图标 + 底部横向终端区”。

## Risks and Mitigations
1. **风险：交互式终端与现有 SSHService 队列职责冲突**
   - 缓解：将终端 session 明确建模为单独能力，但仍挂在现有 SSH 主路径下管理。
2. **风险：v1 若直接追求高仿真终端，范围失控**
   - 缓解：v1 先只交付“可交互 shell 面板”，不承诺完整终端仿真。
3. **风险：断线恢复语义模糊**
   - 缓解：明确冻结规则：断线保留输出、禁用输入、用户手动新建 session。

## Verification Steps
1. 连接前检查按钮禁用态
2. 连接后检查按钮启用态
3. 打开 drawer，执行 `pwd` / `whoami` / `echo hello`
4. 检查长输出滚动显示
5. 主动断开 SSH，检查：
   - drawer 仍在
   - 历史输出保留
   - 输入禁用
   - 断线提示正确
6. 重新连接 SSH，确认不会自动恢复旧 session
