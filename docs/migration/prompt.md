# H2OMeta New-Architecture Cutover Prompt

## Goal

完成新架构彻底切割，使 `Tauri + Next.js + FastAPI + core runtime` 成为唯一可信运行路径，并把工作台继续收敛为稳定的 Notion 风左侧边栏应用。

## Hard Constraints

- 失败必须大声抛出，禁止 silent fallback。
- SSH 访问必须复用 `core/remote/ssh_service.py`，远程命令只允许走 `SSHService.run(cmd, timeout)`。
- 旧配置兼容彻底切断：只接受 v2 schema，旧格式直接报错。
- 旧 workflow alias 彻底切断：新请求只接受新 workflow/tool 名称。
- 不删除任何仍被 runtime/API 使用的桥接层，例如 `core/qt_compat.py`。
- 桌面端结构优先按新信息架构重组，不做旧 PyQt6 页面逐像素翻译。

## Deliverables

- 新架构 cutover 契约文档：只允许新 schema / 新 workflow / 新入口。
- 旧配置兼容删除。
- 旧 workflow alias 删除。
- SSH 生命周期 API 与设置页 SSH 面板继续保留为新架构正式接口。
- 清晰的左侧边栏壳层与页面结构。
- 文档与实际迁移状态一致。

## Done When

- `npm --prefix apps/web run build` 通过。
- 旧配置输入被明确拒绝。
- 旧 workflow alias 提交被明确拒绝。
- Windows 下桌面壳可继续构建和启动。
- `scripts/m6_windows_regression.ps1` 继续通过。
- 新端可直接完成 SSH 配置与连接管理闭环。
- 仓库不再保留旧兼容行为，只保留新 runtime 必需桥接。
