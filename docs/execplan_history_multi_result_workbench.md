# History 多结果工作台 ExecPlan

## Goal

为检测页 `history -> 查看结果` 建立可恢复、可验证的多结果工作台轻量方案：同页保留多个 history 结果入口，支持切换、固定、关闭、清理未固定结果，同时保持现有 Result Shell 渲染协议不变。

## Background

- 本任务执行节奏参考 OpenAI 官方文章《[Run long horizon tasks with Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)》中的循环：`Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat`
- 当前检测页结果工作台已具备统一的 Result Shell registry / overrides，但 history 结果仍会因为 temporary 清理策略而互相覆盖
- `app_galaxy.js` 已明显超过 600 行，本轮新增状态与清理逻辑必须提取到相邻模块，不继续堆积在主文件

## Constraints

- 仅修改 QWebEngine 前端资产与必要测试
- 不修改 SSH、线程、远程执行流水线、执行状态枚举或 Python bridge 协议
- 禁止 silent fallback；若依赖的前端状态模块缺失，页面应显式抛错
- 继续复用 Result Shell 的 registry / contract / blocks，不为不同工具分叉 UI

## Stage 0

- 新建本 ExecPlan，作为本任务的唯一事实源
- 新增前端状态模块，承接 `resultKey`、`openKeys`、`pinnedKeys`、`activeKey`、`entitiesByKey`
- 默认保留最近 `6` 个未固定结果；`pinned` 结果不计入该上限

## Stage 1

- `resultKey` 使用 `baseFeatureId::executionId`
- history 打开的结果进入独立 sidebar 入口，不再覆盖同类旧结果
- sidebar 历史结果入口支持：
  - 激活切换
  - 固定 / 取消固定
  - 关闭单个结果
  - 清理全部未固定结果
- integrated 主视图区继续单实例渲染 active result
- workflow feature 保持原行为；history result 作为 temporary feature 注入并由状态层驱动生命周期

## Stage 2 (Planned, not implemented in this round)

- 将 integrated 固定 DOM 渲染逐步抽成 `ResultPanel(scoped root)`
- 拆出 `results/` 子模块承接 panel renderers 与布局模式切换
- 规划支持 `tabs/stack -> split -> accordion/virtualized list`
- 如后续强对比场景需要，再评估新增批量结果接口

## Verification

- 运行 detection UI smoke 测试，确认多结果工作台相关断言通过
- 运行新增状态层纯函数测试，覆盖：
  - `resultKey` 构造
  - 最近 N 清理
  - pin 优先级
  - close 后 active 迁移
- 手工回归检查：
  - 打开单个 history 结果
  - 连续打开多个 history 结果并切换
  - pin 后继续打开新结果，已固定结果不被清掉
  - 关闭当前 active 结果后自动选中合理的下一个结果
  - 清理未固定结果不影响 pinned 项

## Rollback

- 删除 `results/open_results_state.js` 引用与相关 sidebar controls
- 恢复检测页 history 结果入口为单 temporary feature 模式
- 保留本 ExecPlan 文档，记录回滚原因与后续重新切入点
