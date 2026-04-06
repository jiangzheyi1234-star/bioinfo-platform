# Workspace Desktop UI Unification Prompt

Date: 2026-04-06

## Goal

统一 `runs / history / settings / workbench` 四个一级页面的标题区、卡片层级、空状态和表单节奏，把内容区继续收成一致的桌面工作台风格。

## Required Direction

- 优先抽共享 UI primitive，而不是在各页面重复 header / empty / card / form 结构。
- `detection_workspace_sections.tsx` 只保留页面编排与薄包装，不继续堆重结构。
- `workbench` 保持独立业务数据流，只统一 UI 骨架和信息节奏。
- 统一结果必须兼容现有桌面侧栏 + 内容区壳层，不改一级导航语义。

## Non-Goals

- 不新增后端接口。
- 不修改执行、SSH、历史归档的数据流语义。
- 不把 `projects / databases` 扩成这轮主改造范围。

## Hard Constraints

- 失败必须显式暴露，禁止 silent fallback。
- 本轮不执行 `pytest`。
- 对 dirty worktree 只做任务相关文件修改，不回退其他未完成变更。
