# Workspace Desktop UI Unification Plan

Date: 2026-04-06

## Overview

目标是把 `runs / history / settings / workbench` 四个一级页面继续收敛成一致的桌面工作台风格，统一标题区、卡片层级、空状态和表单节奏，并继续压薄 `apps/web/app/components/detection_workspace_sections.tsx`，让它只保留页面编排和薄包装，不再继续堆叠页面内重结构。

## Current Facts

- 外层导航壳已经统一，四页入口都经由 `DetectionWorkspace` + `DetectionWorkspaceShell`。
- 页面内结构仍然分裂：
  - `runs / history / settings` 直接在 `detection_workspace_sections.tsx` 中各自定义 header、empty、card、form 节奏。
  - `workbench` 走独立的 `workbench_*` 组件和样式语义，标题区、空状态、卡片密度与前三页不一致。
- `apps/web/app/components/detection_workspace_sections.tsx` 当前 559 行，虽然未超过 600 行硬阈值，但已经接近上限；继续叠加统一逻辑会把它推回高风险区。

## Architecture Decisions

- 共享 UI 节奏优先抽成相邻的小组件/样式语义，而不是在每个 section 内复制 header/card/empty/form 结构。
- `detection_workspace_sections.tsx` 只保留页面级 section 入口；可复用的标题区、空状态、面板卡片、表单分组应提取到相邻模块。
- `workbench` 不并回 `detection_workspace_sections.tsx`，而是在现有 `workbench_*` 模块内对齐同一套桌面工作台语义，保持职责边界清晰。
- 样式统一优先通过已有 `globals.css` 中的共享 class 扩展完成；只有在复用受限时才新增更具体的工作台 class。

## Target UI Contract

- 标题区：统一为“标题 + 一句说明 + 右侧动作/统计”的双栏头部，不再混用裸 `row` 和散落 badge。
- 卡片：统一使用相同边框、留白、卡片内间距和标题层级，列表卡片与配置卡片保持同一视觉密度。
- 空状态：统一使用同一占位容器语义，包含标识、说明文案和必要时的引导动作，不再混用 `empty-row`、`panel-placeholder`、纯 `muted` 文本。
- 表单节奏：统一 label、字段块、分组卡片和 actions 区的垂直间距，避免 settings / runs / workbench 各自一套输入节奏。

## Task List

### Phase 1: Shared Workspace Primitives

#### Task 1: 提取共享标题区与空状态骨架

**Description:** 新增相邻共享组件或轻量封装，承接 section title、description、actions、meta/badge、placeholder mark 与空状态容器，作为四页统一骨架。

**Acceptance criteria:**
- [ ] 存在可复用的标题区骨架，能够覆盖 `runs / history / settings / workbench` 的顶部结构。
- [ ] 存在统一空状态骨架，替代当前混用的 `empty-row`、`panel-placeholder`、纯文本空提示。
- [ ] 共享骨架不引入业务状态 fallback；缺少数据时直接显示明确空状态。

**Verification:**
- [ ] 代码检查：四页至少各有一处接入共享标题区或空状态骨架。
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`

**Dependencies:** None

**Files likely touched:**
- `apps/web/app/components/detection_workspace_sections.tsx`
- `apps/web/app/components/workbench_panel_sections.tsx`
- `apps/web/app/components/workbench_panel_support.tsx`
- `apps/web/app/components/` 下新增相邻共享工作台组件文件
- `apps/web/app/globals.css`

**Estimated scope:** Medium

#### Task 2: 提取共享卡片/表单分组节奏

**Description:** 把表单分组、面板卡片、动作区、字段块的共性从现有 section 内抽出来，统一 spacing、标题层级和按钮区节奏。

**Acceptance criteria:**
- [ ] `runs` 工具配置、`settings` SSH 表单、`workbench` trace/config 区至少复用一套统一表单分组语义。
- [ ] 公共卡片 class 或封装能覆盖“列表卡片”和“配置卡片”两类主场景。
- [ ] `detection_workspace_sections.tsx` 不因统一化而继续增长，净结果应保持不高于当前体量并向薄包装方向收敛。

**Verification:**
- [ ] 代码检查：共享卡片/表单语义已落地，重复标题和 padding 片段明显减少。
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`

**Dependencies:** Task 1

**Files likely touched:**
- `apps/web/app/components/detection_workspace_sections.tsx`
- `apps/web/app/components/workbench_panel_support.tsx`
- `apps/web/app/components/` 下新增相邻共享工作台组件文件
- `apps/web/app/globals.css`

**Estimated scope:** Medium

### Checkpoint: Foundation

- [ ] 四页已经开始共享同一套 header / empty / form 语义。
- [ ] `detection_workspace_sections.tsx` 没有继续膨胀。
- [ ] `cd apps/web && npx tsc --noEmit`

### Phase 2: Four-Page Alignment

#### Task 3: 统一 runs 与 history 的目录/列表页节奏

**Description:** 对齐 `runs` 和 `history` 的页面头部、搜索区、列表卡片、空状态和动作按钮，让“查找 -> 选择/查看 -> 执行动作”的桌面工作台节奏一致。

**Acceptance criteria:**
- [ ] `runs` 的左目录与右配置区拥有统一的 section 头部和空状态表达。
- [ ] `history` 的搜索区、列表卡片、空状态和刷新动作与 `runs` 的密度和标题层级一致。
- [ ] 搜索输入和列表容器在桌面布局下保持相同边界与留白节奏。

**Verification:**
- [ ] 手工审查 JSX：`RunsSection` 与 `HistorySection` 的 header/card/empty 结构已收敛。
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`

**Dependencies:** Task 2

**Files likely touched:**
- `apps/web/app/components/detection_workspace_sections.tsx`
- `apps/web/app/globals.css`

**Estimated scope:** Small

#### Task 4: 统一 settings 的操作表单节奏

**Description:** 把 `settings` 页收成与 `runs` 同一工作台语言：顶部信息区、SSH 操作卡片、JSON 编辑卡片、右侧摘要/预览卡片之间的标题与留白节奏统一。

**Acceptance criteria:**
- [ ] SSH 连接区、JSON Patch 区、摘要区都接入统一标题骨架。
- [ ] 字段块、actions、状态条与 `runs/workbench` 的表单间距一致。
- [ ] 右侧摘要/预览不再显得像另一套页面，而是同一工作台内的辅助面板。

**Verification:**
- [ ] 手工审查 JSX/CSS：settings 三块区域的标题和 spacing 已对齐共享语义。
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`

**Dependencies:** Task 2

**Files likely touched:**
- `apps/web/app/components/detection_workspace_sections.tsx`
- `apps/web/app/globals.css`

**Estimated scope:** Small

#### Task 5: 统一 workbench 的标题区、空状态和支持面板

**Description:** 在不破坏 `workbench` 独立职责的前提下，把其页头、结果空状态、执行追踪卡片、数据库路径卡片收成与另外三页一致的桌面工作台风格。

**Acceptance criteria:**
- [ ] `workbench` 页头与其他页面使用相同的标题层级和动作区节奏。
- [ ] 结果区空状态与其他页面空状态语义统一。
- [ ] `workbench` 的 support/trace 卡片与 `runs/settings` 的表单卡片共享同一视觉密度。

**Verification:**
- [ ] 手工审查 JSX：`workbench_panel_sections.tsx` 与 `workbench_panel_support.tsx` 已接入共享骨架或共享样式语义。
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`

**Dependencies:** Task 2

**Files likely touched:**
- `apps/web/app/components/workbench_panel_sections.tsx`
- `apps/web/app/components/workbench_panel_support.tsx`
- `apps/web/app/globals.css`

**Estimated scope:** Medium

### Checkpoint: Cross-Page Parity

- [ ] `runs / history / settings / workbench` 四页的标题区、卡片留白、空状态语义、表单节奏已经肉眼一致。
- [ ] `detection_workspace_sections.tsx` 只保留 section 入口与组装逻辑。
- [ ] `cd apps/web && npx tsc --noEmit`
- [ ] `npm --prefix apps/web run build`

### Phase 3: Refactor Cleanup

#### Task 6: 压薄 detection_workspace_sections.tsx 并清理样式残留

**Description:** 把已经共享化的 header/empty/form/card 结构从 `detection_workspace_sections.tsx` 中继续剥离，清理未再使用的旧 class 和重复样式片段。

**Acceptance criteria:**
- [ ] `detection_workspace_sections.tsx` 只保留页面级 props、数据映射和 section 编排。
- [ ] 未再使用的旧 class、重复 placeholder/spacing 样式被删除。
- [ ] 没有保留已删除结构的 silent fallback 引用。

**Verification:**
- [ ] `rg -n \"panel-placeholder|empty-row|section-header-row\" apps/web/app/components apps/web/app/globals.css`
- [ ] 静态检查：`cd apps/web && npx tsc --noEmit`
- [ ] 构建检查：`npm --prefix apps/web run build`

**Dependencies:** Task 3, Task 4, Task 5

**Files likely touched:**
- `apps/web/app/components/detection_workspace_sections.tsx`
- `apps/web/app/components/workbench_panel_sections.tsx`
- `apps/web/app/components/workbench_panel_support.tsx`
- `apps/web/app/globals.css`
- `apps/web/app/components/` 下共享工作台组件文件

**Estimated scope:** Medium

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 统一样式时误伤 `projects` / `databases` 等未在本轮范围内页面 | Medium | 共享样式以新增 class 或受控替换为主，不做大面积全局覆写 |
| `workbench` 结构复杂，直接并入通用 section 会导致职责混乱 | High | 只统一 UI 骨架与语义，不改变 `workbench` 的数据流和独立模块边界 |
| 为了视觉统一反而把 `detection_workspace_sections.tsx` 继续做大 | High | 先抽共享组件，再回填四页；禁止把新骨架直接内联回原文件 |
| 样式统一后移动端或窄屏桌面布局退化 | Medium | 每个阶段都检查现有 responsive 断点，不只看宽屏桌面 |

## Open Questions

- `projects / databases` 是否要在同一轮同步收口成完全一致的标题区和卡片节奏，还是保持当前“本轮先做四页”的边界。
- `workbench` 是否需要把页头 meta 统计也改成和 shell `context-strip` 同语义，还是仅统一内容区标题。

## Recommended Execution Order

1. 先做共享标题区、空状态、表单卡片骨架。
2. 再分别接入 `runs / history / settings / workbench`。
3. 最后压薄 `detection_workspace_sections.tsx` 并删除旧样式残留。
