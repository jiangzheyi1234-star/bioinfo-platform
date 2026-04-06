# Workspace Desktop UI Unification Documentation

Date: 2026-04-06

## Milestone Status

- [x] 任务专属文档栈建立
- [x] 共享 section header / empty state primitive 落地
- [x] `runs / history / settings` 接入统一标题区与空状态语义
- [x] `workbench` 页头、结果空状态、support card 接入统一语义
- [x] `detection_workspace_sections.tsx` 压回 600 行阈值以内
- [x] 静态验证
- [x] 构建验证

## Decisions

- 共享 primitive 采用轻量组件 + `workspace-*` 样式语义，不改业务 props 结构。
- `workbench` 保持现有数据流，只替换 UI 骨架，不回并到 `detection_workspace_sections.tsx`。
- 旧 `section-header-row / empty-row / panel-placeholder` 允许暂时保留 CSS 定义，但 JSX 使用应被共享 primitive 替换。

## Verification Log

- `2026-04-06` `cd apps/web && npx tsc --noEmit` 通过
- `2026-04-06` `npm --prefix apps/web run build` 通过
- `2026-04-06` `rg -n "section-header-row|empty-row|panel-placeholder" ...` 确认旧语义仅残留在 CSS 定义中，不再出现在本轮目标 JSX 中
- `2026-04-06` `wc -l apps/web/app/components/detection_workspace_sections.tsx` = `551`

## Follow-ups

- 若 `projects / databases` 也要完全并入同一视觉语言，可在本轮后做单独小收口。
- 若后续继续压文件体积，可把 `runs / history / settings` 再拆成相邻 section 模块。
