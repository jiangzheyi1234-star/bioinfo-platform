# Persistent Agent Notes
## ⚠️ 最高优先级
失败必须大声抛出，禁止 silent fallback，禁止保留已删除字段的任何兜底引用。

## 测试约定

1. `pytest` 统一由用户自行测试，Codex 不负责继续在当前 agent 环境内执行或兜底 `pytest`。
2. Codex 不得为了“跑过测试”而删除测试、弱化断言，或修改产品代码去迎合错误测试环境。


## ExecPlans

- 复杂特性、跨文件重构、长时程任务默认使用 `ExecPlan` 工作流：
  `Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat`。
- 执行前必须先读取对应计划文档；若仓库内已有任务专属计划文档，则该文档优先作为唯一执行事实来源。
- 任务完成后应清理过期的阶段性计划/记忆文档，避免残留失效入口。
- ExecPlan 必须保持自包含、活文档、可恢复；每完成一个 milestone 立即运行对应验证，失败先修复，不允许带着失败进入下一 milestone。

## Large File Refactor Preference（必须遵守）

- 当目标文件已超过 600 行时，新增功能、复杂分支、结果构建、远程调用、数据解析，优先提取到相邻新模块；原文件只保留门面、绑定点和薄包装。
- 禁止在超 600 行文件中继续直接堆积重逻辑，除非用户明确要求只做局部热修且拆分会显著放大风险。

## Web 前端基线（必须遵守）

- Web 前端默认技术路线：**shadcn/ui + Tailwind CSS**。
- 以后实现 UI 时，优先复用 shadcn/ui 现成组件、Tailwind 原子类与设计 token，禁止无必要重复造轮子。
- 未经用户明确要求，不要自建一套新的基础按钮、输入框、弹层、侧边栏、表单控件或样式工具层。
- 做前端页面/组件前，先判断能否直接用 shadcn/ui 组件组合完成；只有在 shadcn/ui 无法覆盖时，才允许做薄封装或局部扩展。
- 新增前端样式优先放在 Tailwind class 与 shadcn/ui 组件组合层，避免重新回到手写大块自定义 UI 基础设施。
- 默认不保留独立的大块自定义 `.css` 文件；若不是 Tailwind/shadcn 必需入口或用户明确要求，发现旧 CSS 文件可直接清理。
- 以后前端实现优先采用 Tailwind utility class、shadcn/ui 组件组合，以及必要的 token/config 调整，而不是继续维护历史遗留 CSS。
- 图标库统一使用 **`lucide-react`**；未经用户明确要求，不再混用 `@heroicons/react`、emoji 或其他图标体系。
- 新前端组件若需要图标，默认先从 `lucide-react` 选型，保持 stroke、尺寸、语义风格一致。

## 用户偏好

- **提交**：必须给 commit hash + 标题 + 变更摘要 + 文件清单。
- **本地权限错误**：直接提权继续，不反复重试。
- **Windows UTF-8**：设 `WSL_UTF8=1` + `PYTHONUTF8=1`，参考 `scripts/codex_wsl_utf8_doctor.ps1`。

## 当前任务状态
