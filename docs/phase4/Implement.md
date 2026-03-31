# Phase 4 Implementation Guide

## Working Rules

- 只实现 `docs/phase4/Plan.md` 中定义的 milestone。
- 先核对基线，再改视觉系统；不要跳过 Milestone 0。
- 每完成一个 milestone，立即运行该 milestone 对应验证。
- 验证失败先修复，不允许带着失败进入下一 milestone。
- 全程持续更新 `docs/phase4/Documentation.md`。
- 所有结论优先用可观测行为表述，而不是文件清单或 class 清单。

## Change Strategy

1. 先盘点再收口：
   先盘点 typography、spacing、state、card、button 的漂移，再定义统一 token 映射。
2. 先 token 化再替换：
   先建立统一视觉 token 与语义，再逐步替换具体样式。
3. CSS 优先：
   优先修改 `ui/pages/detection_page_assets/styles_galaxy.css`。
4. HTML 轻调：
   只有在无法通过 CSS 达到目标时，才轻调 `ui/pages/detection_page_assets/index_galaxy.html`。
5. 行为不动：
   不重写 execution 旅程，不重写 typed result 语义，不把视觉问题变成行为改造。

## Required Inventory Before Editing

开始视觉改动前，至少盘点以下内容并记录到 `Documentation.md`：

- typography scale 在 history、hero、summary、result card 是否漂移
- spacing scale 在主卡、侧卡、toolbar、summary card 是否漂移
- state token 是否存在多套颜色/强调逻辑
- card tier 是否混用多个阴影、圆角、边框强度体系
- button system 是否存在主次按钮规则不一致
- inline styles 是否在破坏设计系统

## Preferred Edit Order

建议按以下顺序实施：

1. 根级 token 收口
2. 状态 token 收口
3. card tier / button system 收口
4. hero / summary / history 统一状态语言
5. primary viewer 与 secondary panels 层级重排
6. 清理破坏设计系统的 inline styles
7. 补充或更新 UI smoke 护栏

## Explicit Non-Goals

以下内容不在 Phase 4 范围内，不要改：

- `ToolEngine.execute()`
- SSH / `SSHService.run()`
- `JobDispatcher`
- execution 状态枚举
- 持久化状态
- 结果协议
- bridge API
- `tool.yaml`
- artifact manifest
- backend 抽象
- Nextflow / agent / server 重做

## Validation Discipline

- 基线核对后先跑结果工作台定向测试，再开始视觉改动。
- 每个 milestone 完成后立刻执行对应验证。
- 若改动触及 smoke 假定的 DOM 结构或关键文案，必须同步更新护栏，且只更新 Phase 4 必需部分。
- 最终提交前至少复跑：
  - `pytest tests/test_ui_smoke.py tests/test_single_tool_results.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`

## Documentation Discipline

`docs/phase4/Documentation.md` 必须持续更新，至少记录：

- 当前正在执行哪个 milestone
- 为什么做出当前决策
- 跑了哪些验证
- 失败点是什么
- 如何修复
- 是否已复验通过
- 还有哪些明确延后但不应现在扩 scope 的问题
