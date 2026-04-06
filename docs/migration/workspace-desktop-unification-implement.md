# Workspace Desktop UI Unification Implement

Date: 2026-04-06

## Execution Rules

- 以 `docs/migration/workspace-desktop-unification-plan.md` 为执行事实源。
- 共享 UI primitive 先落地，再分页面接入，最后做残留清理。
- 每完成一个 milestone，先执行静态验证；失败先修复，不带失败进入下一步。
- `detection_workspace_sections.tsx` 不允许因这轮统一化继续膨胀成新的大文件。

## Current Phase

1. 建立任务文档栈
2. 落地共享标题区 / 空状态 / 表单节奏
3. 接入 `runs / history / settings / workbench`
4. 清理旧 class 残留并更新文档

## Validation Commands

- `cd apps/web && npx tsc --noEmit`
- `npm --prefix apps/web run build`

## Repair Notes

- 若共享 primitive 引入命名冲突，优先调整 import alias，不回退统一方向。
- 若样式统一影响未在本轮范围内页面，优先收窄到 `workspace-*` 语义类。
