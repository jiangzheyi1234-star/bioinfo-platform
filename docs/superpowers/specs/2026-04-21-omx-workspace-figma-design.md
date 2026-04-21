# H2OMeta / OMX 对齐版 Figma 稿（v1）

**Status:** draft  
**Date:** 2026-04-21  
**Scope:** Workspace Shell / Home / Runs List / Run Detail（优先页）  
**Primary Goal:** 产出一份可直接在 Figma 落稿的前端设计稿，并与 OMX / 本地后端 / 远端 runner 的 v1 合同对齐。

> 设计权威来源：
>
> - `docs/ui-scheme-v1.1.md`
> - `docs/frontend-best-practices.md`
> - `docs/frontend-plan-v1.md`
> - `docs/backend-contract-v1.md`
>
> 本文档是上述文档在 **Figma 落稿层** 的收敛版。

---

## 1. 设计基调

H2OMeta 是 **科学工作台**，不是 dashboard wall，也不是运维控制台。

关键词：

- restrained
- stable
- precise
- low-noise
- object-driven

视觉总原则：

1. **Hover 为王**：静态态尽量安静，反馈主要由 hover / active 承担
2. **字重代替颜色**：优先用字号 / 字重 / 明度建立层级
3. **留白代替线条**：能靠 spacing 分区，就不加 divider
4. **对象页优先**：路由决定主上下文，tabs 只做对象内部切换

---

## 2. Figma 文件结构

建议 Figma 页面：

1. `00 Foundations`
2. `01 Shell`
3. `02 Home`
4. `03 Runs List`
5. `04 Run Detail`
6. `05 Servers / Results (Future)`

建议 Frame baseline：

- Desktop: `1440 x 960`

基础 layout token：

- Sidebar width: `228`
- Top tabs bar: `44`
- Content horizontal padding: `24`
- Section gap: `20`
- Inner block gap: `12 / 16 / 20`
- Main content max width: `1164`

---

## 3. Foundations

### 3.1 颜色

- App Background: `#FBFBFA`
- Sidebar Background: `#F7F7F5`
- Content Background: `#FFFFFF`
- Divider / Hairline: `#E5E7EB`
- Primary Text: `#0F172A`
- Secondary Text: `#64748B`
- Quiet Hover Fill: `#EEF2F5`
- Quiet Active Fill: `#E5EAF0`

状态色要求：

- 低饱和，不发光，不做大面积铺底
- 只用于圆点、少量 badge、迷你状态 cue

建议：

- Running Dot: `#7C9AB8`
- Completed Dot: `#7A9B7E`
- Failed Dot: `#B07A7A`
- Queued Dot: `#A0A7B4`

### 3.2 字体层级

- Page Title: `24 / Semibold`
- Section Title: `18 / Semibold`
- Block Title: `15 / Medium`
- Body: `14 / Regular`
- Secondary Body: `13 / Regular`
- Meta / Caption: `12 / Medium`
- Tiny System Label: `11 / Semibold`

### 3.3 圆角与描边

- Small radius: `8`
- Standard radius: `10`
- Large radius: `12`
- 边框默认只在输入框、对话框、必要 table header 中使用

### 3.4 Hover 规则

以下组件 hover 必须明确设计：

- Sidebar nav item
- Top tab
- List row
- Summary strip meta item（若可点击）
- Ghost button
- Terminal trigger

静态态目标：**近似无框、无重底色、无视觉噪音**

---

## 4. 组件清单

### 4.1 Sidebar / Shell

#### A. Connection Block

位置：Sidebar 顶部

结构：

- `Link2` icon
- Title: `Connection`
- Subtitle:
  - connected: `user@host:port`
  - disconnected: `未连接远端服务器`
- 右上角 overflow actions（仅 connected 时显示）

视觉：

- 无强卡片边框
- hover 时才出现很浅背景
- connected icon 用低饱和蓝灰，不用亮蓝

#### B. Sidebar Nav Item

结构：

- icon + label

状态：

- default：透明
- hover：极浅灰底
- active：更稳定的浅灰底 + 更深字色

#### C. Top Tab

角色：轻量浏览器式上下文保持，不作为主 IA

状态：

- default：与 tabs bar 融合
- hover：极浅背景
- active：白底 / 轻边界 / 更深文字

#### D. Terminal Trigger

位置：右下角优先

结构：

- Lucide `Terminal`
- 可选 1 个小状态点

状态语义：

- disconnected：灰点
- idle connected：蓝灰点
- running：柔和蓝点
- error：暗红点

### 4.2 Page-level

#### E. Page Header

固定结构：

- Left:
  - breadcrumb
  - page title
  - optional description / object context
- Right:
  - actions

按钮规则：

- 默认 `Ghost / Secondary`
- 只允许 1 个 `Primary`
- 只有真正推进主流程的动作使用 Primary（如 `New Run`）

#### F. Summary Strip

位置：Page Header 下方

结构：

- 横向平铺 3–5 个 meta cells
- 每个 cell：
  - tiny label
  - 1 行 value

视觉：

- 极浅灰底
- 无边框
- 小字
- 不做高卡片感

#### G. Status Badge

结构：

- 小圆点 + 文字

视觉：

- 无发光
- 胶囊非常轻
- 文字颜色比圆点深一级

#### H. Empty State

结构：

- 极淡线框示意图
- 短标题
- 一行解释
- 1 个主 CTA

语气：

- 冷静
- 清楚
- 不卖萌

### 4.3 Dense Data

#### I. Filter Bar

元素：

- Search
- Status filter
- Stage filter
- Server / Project filter（按页决定）
- Sort

视觉：

- 轻量单行布局
- 优先输入框 + dropdown
- 不使用重 toolbar

#### J. List Row / Table Row

默认：

- 白底
- 无显性边框
- 用行高和列距维持秩序

hover：

- 浅灰 hover fill

选中：

- 比 hover 稍明确

---

## 5. 页面一：Workspace Shell / Home

### 5.1 目的

Home 不是大屏仪表盘，而是工作入口页。

承担：

- Recent Runs
- Server Readiness Summary
- Recent Results
- Quick Actions

### 5.2 画板结构

#### Shell 外层

- 左：Sidebar
- 上：Tabs bar
- 右：Content
- 右下：Terminal trigger
- 底部：terminal dock（展开态单独一帧）

#### Content 区布局

1. Page header
2. Quick summary row
3. Two-column body

建议：

- 左列 `2fr`
- 右列 `1fr`

### 5.3 Home 组件编排

#### 顶部 Header

- Breadcrumb：`Workspace`
- Title：`Home`
- Description：一句简短工作台说明
- Right actions：
  - `Refresh`（Ghost）
  - `New Run`（Primary）

#### Summary Row

4 个 meta：

- Connected Server
- Runner Ready
- Running Runs
- New Results Today

#### 左列

1. `Recent Runs`
   - 5~7 行列表
   - 每行包含：
     - runId
     - pipeline
     - status badge
     - stage
     - lastUpdatedAt

2. `Recent Results`
   - 4~5 行
   - 每行包含：
     - result title
     - source run
     - artifact count
     - produced time

#### 右列

1. `Server Readiness`
   - server identity
   - ready / live / startup
   - `reasonCode` 露出位
   - actions:
     - Inspect
     - Bootstrap
     - Rotate token

2. `Quick Actions`
   - New Run
   - Open Terminal
   - Manage Server

### 5.4 后端对齐

Home 中的卡片必须能映射到后端能力：

- Server Readiness ← `GET /api/v1/servers/{serverId}/health`
- Recent Runs ← `GET /api/v1/runs/{runId}` 聚合视图
- Recent Results ← `GET /api/v1/runs/{runId}/results` 或本地聚合结果索引
- Quick Actions ← 本地后端管理动作

视觉强调点：

- `reasonCode` 要露出，但不做红色大警报块
- `requestId` 不放在 Home 主视图

---

## 6. 页面二：Runs List

### 6.1 目的

这是最高信息密度页，用来检验整套列表规则是否成立。

### 6.2 页面结构

1. Breadcrumb
2. Page header
3. Filter bar
4. Runs table / list

### 6.3 Header

- Breadcrumb：`Runs`
- Title：`Runs`
- Description：围绕运行状态、阶段与追踪
- Actions：
  - `Export`（Ghost，可后置）
  - `New Run`（Primary）

### 6.4 Summary Strip

建议 5 项：

- Total Runs
- Running
- Failed
- Completed Today
- Connected Server

### 6.5 Filter Bar

控件：

- Search by `runId / pipeline / requestId`
- Status
- Stage
- Server
- Project
- Updated time

### 6.6 List 列定义

按 `docs/frontend-plan-v1.md` 和 backend contract：

- Run
  - `runId`
- Server
  - `serverId` / server label
- Project
  - `projectId` / project label
- Pipeline
  - `pipelineId`
- Status
  - `status`
- Stage
  - `stage`
- State
  - `stateVersion`
- Updated
  - `lastUpdatedAt`

次要信息可折叠进一列副文本：

- `message`
- `requestId`

### 6.7 行视觉规则

- 行高建议 `56–64`
- 不做粗边框栅格
- 通过：
  - 左对齐文本
  - 固定列距
  - 字重层次
  - hover fill
  来维持秩序

### 6.8 行点击后行为

点击整行进入 `Run Detail`

可在 hover 时显示右侧轻量 affordance：

- `Open`
- 或极淡箭头图标

### 6.9 Empty State

标题：

- `暂无 Run`

说明：

- `连接服务器并创建一次新的 Run 后，这里会显示执行进度与结果入口。`

按钮：

- `New Run`

### 6.10 后端对齐

Runs List 必须显式兼容以下字段：

- `status`
- `stage`
- `stateVersion`
- `message`
- `lastUpdatedAt`
- `requestId`

注意：

- `progress` 可以为 `null`
- UI 不承诺精确百分比
- `stateVersion` 是重要可观测字段，应露出

---

## 7. 页面三：Run Detail

### 7.1 目的

Run Detail 是对象页范式样板，必须把：

- breadcrumb
- summary strip
- inner tabs
- logs / events / outputs / spec

组织得清楚且不吵。

### 7.2 顶部结构

#### Header

- Breadcrumb：
  - `Projects / {projectName} / Runs / {runId}`
  - 或简化为 `Runs / {runId}`
- Title：
  - `Run {runId}`
- Subtitle：
  - source project / server
- Right actions：
  - `Copy requestId`
  - `Open in Results`（有结果时）
  - `Refresh`

#### Summary Strip

5 个 meta：

- Pipeline
- Stage
- State Version
- Started / Finished
- Request ID

必要时第 6 项：

- Result Dir

### 7.3 Tabs

按 canonical plan：

- Overview
- Events
- Logs
- Outputs
- Spec

Tabs 规则：

- 只做对象内部 sibling views
- active tab 明确但轻
- 不做粗下划线主导视觉

### 7.4 Tab: Overview

包含：

1. Status block
   - status badge
   - message
   - lastUpdatedAt

2. Last error block（仅错误时显示）
   - `code`
   - `message`
   - `scope`
   - `requestId`
   - `at`

3. Source / runtime context
   - serverId
   - pipelineId
   - pipelineVersion
   - runSpecVersion

设计要求：

- 错误区域用轻微强调，不做“报错大红板”

### 7.5 Tab: Events

形式：

- timeline / event list

字段：

- `eventType`
- `fromStatus`
- `toStatus`
- `stage`
- `stateVersion`
- `message`
- `requestId`
- `createdAt`

视觉：

- 事件节点很轻
- 重点是时间顺序和状态变迁

### 7.6 Tab: Logs

布局：

- 顶部工具条：
  - `stdout / stderr` switch
  - refresh
  - copy
- 下方内容区：
  - 浅底或白底日志面板

原则：

- 它不是“主黑终端”
- 不应抢走页面主视觉
- 真正的终端仍由 bottom dock 承担

后端对齐：

- `GET /api/v1/runs/{runId}/logs?stream=stdout|stderr&cursor=...`
- cursor 按 stream 独立

### 7.7 Tab: Outputs

作用：

- 承接 `GET /api/v1/runs/{runId}/results`

列表字段：

- artifact name / path
- kind
- size
- mimeType
- createdAt

每行动作：

- Preview
- Download

### 7.8 Tab: Spec

内容：

- `runSpec` structured view
- raw JSON view

布局：

- 左：key facts summary
- 下：formatted JSON

目标：

- 让用户确认是“结构化执行”，不是随意 shell 命令

### 7.9 后端对齐

Run Detail 要严格映射：

- `GET /api/v1/runs/{runId}`
- `GET /api/v1/runs/{runId}/events`
- `GET /api/v1/runs/{runId}/logs`
- `GET /api/v1/runs/{runId}/results`

关键字段必须在界面上有明确位置：

- `runId`
- `status`
- `stage`
- `stateVersion`
- `message`
- `startedAt`
- `finishedAt`
- `lastUpdatedAt`
- `resultDir`
- `lastError`
- `requestId`

---

## 8. OMX / 本地后端对齐策略

### 8.1 信息架构对齐

前端所有“主数据”都只来自 **local backend**，不设计前端直连 remote runner 的 UI 暗示。

因此文案与交互上应强调：

- `Server`
- `Connection`
- `Bootstrap`
- `Ready`
- `Run`
- `Results`

而不是暴露过多远端内部服务术语。

### 8.2 Server Readiness 的 UI 落点

必须有位置承接：

- startup
- live
- ready
- `reasonCode`

建议在：

- Home 右列
- Server detail 顶部 summary

呈现方式：

- 轻量状态条目
- `reasonCode` 用次级文本露出
- 需要操作时才显示 Ghost action

### 8.3 Request ID 的 UI 落点

后端规定 requestId 是可支持排障的人类可见 key。

因此：

- Runs List：放在次要信息中，可搜索
- Run Detail：放入 summary strip，并可复制
- Error UI：必须露出 `requestId`

### 8.4 Structured Error 对齐

所有错误 UI 至少保留：

- title
- detail
- code
- requestId

避免：

- 只显示“请求失败”
- 把结构化错误压平为普通 toast

### 8.5 Async 语义对齐

由于 `POST /runs` 是 async long-task：

- 提交后 UI 不应模拟同步完成
- 应直接跳转 / 引导进入 Run Detail
- Run Detail 用 polling 展示状态推进

### 8.6 SQLite Authority 对齐

UI 上不把日志文件、结果文件当作状态真相来源。

设计上：

- 状态以 run state / events 为主
- artifacts / logs 作为子视图
- 避免让文件视图盖过对象状态本身

---

## 9. Figma 落稿顺序

推荐按下面顺序出图：

1. `01 Shell`
   - sidebar
   - tabs
   - terminal trigger
   - terminal dock
2. `02 Home`
3. `03 Runs List`
4. `04 Run Detail`

每一步都先出：

- base frame
- spacing
- typography
- hover states
- empty state

再补充：

- badges
- loading
- error
- ready / not ready

---

## 10. Figma 交付定义

本轮 Figma 稿至少应包含：

- 1 个完整 Shell
- 1 个 Home frame
- 1 个 Runs List frame
- 1 个 Run Detail / Overview frame
- 1 个 Run Detail / Logs frame
- 组件库基础件：
  - Sidebar Item
  - Connection Block
  - Top Tab
  - Page Header
  - Summary Strip
  - Status Badge
  - Filter Bar
  - List Row
  - Empty State
  - Terminal Trigger

---

## 11. 直接给设计师 / Figma 执行者的话

这套稿不要追求“看起来设计过度”。

正确方向是：

- 页面安静
- hover 精准
- 信息层级清楚
- 状态露出克制
- 列表经得起高密度
- Run Detail 能承接真实后端字段

如果一块区域已经被留白分开，就不要补分割线。  
如果一个层级已经能靠字重表达，就不要再加颜色。  
如果一个动作不是主流程推进按钮，就不要给 Primary。

这就是 H2OMeta / OMX 对齐版的 v1 Figma 稿标准。
