# Test Spec — SSH 远程终端面板 v1

## Source of truth
- PRD: `.omx/plans/prd-ssh-terminal-panel.md`

## Verification goal
证明工作台新增的 SSH 远程终端面板满足本轮范围：连接成功后可用、右上角打开、内容区底部固定面板展示、采用上下分屏 + 可拖动横向分隔线、接入 xterm.js、直接在终端区域内部输入，并且在 SSH 断开时进入明确的断线态而不是直接消失，同时视觉效果与用户截图中的终端入口/底部终端区一致。

## Scope checks
1. 终端入口位于右上角工具区
2. 终端以内容区底部固定面板形式出现
3. 仅在 SSH 成功连接后可用
4. v1 不包含本地终端、多 tab、快捷命令、文件管理、端口转发、安装联动
5. 视觉布局接近用户截图：右上角小图标触发、内容区底部横向终端区域
6. 终端打开后为上下分屏布局，而不是浮层抽屉
7. 终端内容区使用 xterm.js，而不是“输出区 + 独立输入框”的假终端结构
8. 终端 IO 主路径使用 websocket，而不是 HTTP 轮询输出
9. 终端支持选区复制与粘贴

## UI state checks
1. 未连接状态：
   - 按钮禁用
   - 有“请先连接远端服务器”类提示
2. 已连接状态：
   - 按钮启用
   - 点击可显示内容区底部固定终端面板
3. 面板状态：
   - 可手动关闭/隐藏
   - 是内容区布局的一部分，而不是浮层抽屉
   - 不是右侧窄栏，而是底部横向终端区
4. 分隔线状态：
   - 主工作区与终端区之间存在横向 handle
   - 用户可拖拽改变终端高度
   - 拖拽后布局稳定、不抖动

## Terminal interaction checks
1. 打开 drawer 时可以成功创建远程终端 session
2. 输入 `pwd` 可以得到输出
3. 输入 `whoami` 可以得到输出
4. 输入 `echo hello` 可以得到输出
5. 长输出命令（如 `ls -la`）可正常显示并滚动
6. 输入直接在终端缓冲区中进行，而不是下方独立表单输入栏
7. 选中文本后 `Ctrl/Cmd+C` 可复制
8. `Ctrl/Cmd+V` 或右键粘贴可把文本送入远端终端

## Session lifecycle checks
1. 打开 drawer 时创建 session
2. 关闭 drawer 时 session 被清理
3. 重新打开 drawer 会创建新 session
4. 不依赖“每条命令新起一次 run(cmd)”伪装成终端
5. websocket 断流但 SSH 仍存活时，前端会自动重连同一 session

## Disconnect behavior checks
1. SSH 断开时：
   - 固定终端面板仍保持可见
   - 历史输出不丢失
   - 输入区禁用
   - 显示断线文案
2. 断开后不允许继续发送输入
3. 重新连接 SSH 后：
   - 不自动恢复旧 session
   - 需要用户手动重新创建终端会话

## Layout restoration checks
1. 终端关闭后，页面恢复为单层主工作区
2. 再次打开后，可重新回到上下分屏布局

## Error handling checks
1. session 创建失败时有明确错误提示
2. 输出读取失败时不会让 UI 卡死
3. SSH 状态变化时终端状态同步更新

## Brownfield integration checks
1. 终端功能挂接在当前 `ssh-shell.tsx` 的 SSH 壳层语义中
2. SSH 连接主流程（connect/disconnect/dialog）保持不回归
3. 不新增与现有 Python SSH 主路径割裂的第二套 SSH 连接模型

## Completion gate
仅当以下全部成立时，本阶段才算完成：
- 用户能在产品内打开当前 SSH 连接对应的远程终端
- 终端能完成基本命令交互
- 断开 SSH 时终端行为符合“保留输出、禁用输入、不断然消失”的冻结规则
- v1 非目标没有被偷偷扩展进来
