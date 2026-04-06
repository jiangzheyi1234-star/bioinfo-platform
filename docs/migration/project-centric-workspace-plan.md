# Project-Centric Workspace Plan

Date: 2026-04-06

## Overview

将桌面 Web 主入口从 `projects / runs / history / workbench` 的一级功能导航，切到 `project -> task -> workspace` 的对象型工作区。

## Decisions

- `Task` 是正式领域对象，不是 execution 的 UI 包装。
- 左侧栏固定为项目列表、任务工具栏、任务列表三段。
- 右侧主区是单任务工作区。
- `results` 是项目级独立页面。
- `settings` 保持全局页。
- 旧 execution 通过显式迁移进入 `Imported history` 任务，不做 silent fallback。

## Delivered

- 项目库新增 `tasks` 表。
- `executions` 新增 `task_id` 归属。
- API 新增任务列表、创建、读取、更新、任务执行历史、项目结果聚合。
- Web 新增 `/projects` 项目任务工作区。
- Web 新增 `/results` 项目级结果页。
- `runs / history / databases / samples / workbench` 页面收口为重定向入口。

## Validation

- `python3 -m py_compile apps/api/main.py apps/api/models.py core/app_runtime/service.py core/app_runtime/workbench_runtime_ops.py core/data/project_manager.py core/data/execution_query_service.py core/execution/tool_engine.py core/execution/tool_bridge_execution_ops.py core/execution/tool_bridge_execution_orchestrator.py`
- `cd apps/web && npx tsc --noEmit`
- `npm --prefix apps/web run build`
