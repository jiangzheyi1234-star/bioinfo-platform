# QWebEngine Design System ExecPlan

## Goal

为 QWebEngine 前端建立一套共享设计系统基础层，先完成工具环境表与安装弹窗试点，再把同一套 token 和组件样式迁移到检测页。

## Background

- 当前仓库已有检测页结果壳规划：`docs/execplan_result_shell_harness.md`
- 本文档是本次前端样式整理的唯一执行事实源
- 设计执行方式参考 Anthropic 2025-11-26 文章：
  [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## Constraints

- 不引入 Vue/React/Tailwind 等新运行时或构建体系
- 不合并两个页面的布局层
- 共享层只负责 token 和基础组件，不接管页面级布局
- 禁止 silent fallback；已删除的 token、类名、inline style 不得保留兜底引用
- 只在 QWebEngine 前端资产中工作，不触碰 SSH、线程、执行状态逻辑

## Shared Tokens

- color
  - `--ui-color-canvas`
  - `--ui-color-panel`
  - `--ui-color-subtle`
  - `--ui-color-elevated`
  - `--ui-color-border`
  - `--ui-color-border-strong`
  - `--ui-color-text`
  - `--ui-color-text-muted`
  - `--ui-color-text-subtle`
  - `--ui-color-accent`
  - `--ui-color-accent-strong`
  - `--ui-color-accent-soft`
  - `--ui-color-success`
  - `--ui-color-success-soft`
  - `--ui-color-warning`
  - `--ui-color-warning-soft`
  - `--ui-color-danger`
  - `--ui-color-danger-soft`
- spacing
  - `--ui-space-1` to `--ui-space-6`
- radius
  - `--ui-radius-sm`
  - `--ui-radius-md`
  - `--ui-radius-lg`
  - `--ui-radius-xl`
  - `--ui-radius-pill`
- shadow
  - `--ui-shadow-sm`
  - `--ui-shadow-md`
  - `--ui-shadow-lg`
- typography
  - `--ui-font-family`
  - `--ui-font-size-caption`
  - `--ui-font-size-body-sm`
  - `--ui-font-size-body`
  - `--ui-font-size-label`
  - `--ui-font-size-title`
  - `--ui-font-size-hero`
- layering
  - `--ui-z-base`
  - `--ui-z-sticky`
  - `--ui-z-overlay`
  - `--ui-z-toast`

## Shared Component API

- `ui-card`
- `ui-button`
- `ui-button--primary`
- `ui-button--secondary`
- `ui-button--success`
- `ui-button--sm`
- `ui-badge`
- `ui-badge--accent`
- `ui-badge--success`
- `ui-badge--warning`
- `ui-badge--danger`
- `ui-table`
- `ui-modal`
- `ui-modal__backdrop`
- `ui-modal__card`
- `ui-notice`
- `ui-notice--success`
- `ui-notice--warning`
- `ui-notice--danger`
- `ui-field`
- `is-hidden`
- `is-disabled`
- `is-loading`

## Page Boundaries

### Shared layer

- `ui/pages/shared_assets/web_tokens.css`
- `ui/pages/shared_assets/web_components.css`

### Tool env pilot

- `ui/pages/settings_page_assets/tool_env_table.html`
- `ui/pages/settings_page_assets/tool_env_table.css`
- `ui/pages/settings_page_assets/tool_env_table.js`
- `ui/pages/settings_page_assets/install_dialog.html`
- `ui/pages/settings_page_assets/install_dialog.css`
- `ui/pages/settings_page_assets/install_dialog.js`

### Detection page

- `ui/pages/detection_page_assets/index_galaxy.html`
- `ui/pages/detection_page_assets/styles_galaxy.css`
- `ui/pages/detection_page_assets/result_shell_theme.css`
- `ui/pages/detection_page_assets/app_galaxy.js`

## Layout Ownership

- `tool_env_table.css` 保留工具环境表布局和局部结构
- `install_dialog.css` 保留安装弹窗布局和局部结构
- `styles_galaxy.css` 只保留检测页布局、检测页结构类、检测页独有视觉补充
- 共享层不合并以上页面布局

## Migration Rules

1. 试点页面迁移完成后，旧基础类不得继续与 `ui-*` 并存
2. 页面专属结构类可以保留
3. JS 不再注入颜色、间距、字体、阴影、圆角、z-index
4. 仅允许保留动态定位类样式，且限制为 `top/left/width/height`

## Inline Style Cleanup Targets

- `tool_env_table.html` 内联 `<style>`
- `index_galaxy.html` 中 `style="display:none;"`
- `install_dialog.js` 中 `.style.display`
- `app_galaxy.js` 中 notice/toast/help tooltip/空状态/只读字段模板的 inline style

## Value Mapping Notes

- 检测页原 `:root` token 作为共享 token 初始来源
- 工具环境表与安装弹窗原硬编码值映射到共享 token
- `result_shell_theme.css` 原 `--report-*` token 不再单独定义，统一改为共享 token

## Completed

- 建立任务专属 ExecPlan
- 新建共享 token 层与共享组件层
- 工具环境表迁移到 `ui-*` 组件类
- 安装弹窗迁移到 `ui-*` 组件类
- 检测页接入共享样式层
- 检测页清理核心 inline style 热点：
  - `index_galaxy.html` 中显隐内联样式
  - `app_galaxy.js` 中 notice 模板
  - `app_galaxy.js` 中 modal 显隐热点
  - `app_galaxy.js` 中输入控件与空状态模板

## In Progress

- 检测页更广范围的基础类进一步统一到 `ui-*`

## Pending

- 如有需要，再单独规划 QWebEngine 与 Qt QSS token 对齐

## Rollback

1. 保留新建共享层文件与 ExecPlan 文档
2. 从 HTML 中移除共享样式引用
3. 回退页面到原有 CSS/JS 绑定方式
4. 若检测页迁移引发回归，优先只保留试点页共享层接入，再缩小检测页接管范围
