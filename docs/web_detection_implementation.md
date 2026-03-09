# 病原检测页 Web 版本实现文档

## 概述

使用 QWebEngineView + HTML/CSS/JavaScript 实现病原检测页的响应式卡片布局，解决原生 Qt 布局系统无法实现完美填满宽度的问题。

## 技术栈

- **后端**: Python + PyQt6 + QWebChannel
- **前端**: HTML + CSS Grid + Vanilla JavaScript
- **通信**: QWebChannel (Python ↔ JavaScript 双向通信)

## 文件结构

```
ui/pages/
├── detection_page.py              # 原生 Qt 版本（保留作为备份）
├── detection_page_web.py          # Web 版本（新实现）
└── detection_page_assets/         # Web 资源
    ├── index.html                 # 主 HTML 模板
    ├── styles.css                 # 样式表（CSS Grid 布局）
    └── app.js                     # JavaScript 逻辑
```

## 核心实现

### 1. Python 端 (detection_page_web.py)

**ToolBridge 类**：Python 与 JavaScript 通信桥接
- `get_tools()`: 返回所有工具列表（JSON 格式）
- `select_tool(tool_id)`: 选择工具
- `run_tool(tool_id, params_json)`: 运行工具
- `tool_selected` 信号: Python → JavaScript 通知

**DetectionPageWeb 类**：主页面容器
- 创建 QWebEngineView
- 设置 QWebChannel 通信
- 加载 HTML 文件

### 2. 前端端 (HTML/CSS/JS)

**HTML (index.html)**：
- 搜索框 + 工具计数
- 卡片网格容器

**CSS (styles.css)**：
- 核心布局：`grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`
- 自动填满宽度，响应式列数调整
- 卡片悬停效果 + 选中状态

**JavaScript (app.js)**：
- QWebChannel 初始化
- 工具列表加载和渲染
- 搜索过滤功能
- 卡片点击交互

## 使用方法

### 1. 安装依赖

```bash
pip install PyQt6-WebEngine
```

### 2. 切换版本

在 `ui/main_window.py` 中修改配置：

```python
USE_WEB_DETECTION = True  # True: Web 版本, False: 原生 Qt 版本
```

### 3. 运行应用

```bash
python -m ui.main
```

## 响应式布局效果

- **窄窗口 (< 600px)**: 1 列卡片
- **中等窗口 (600-1200px)**: 2-3 列卡片
- **宽窗口 (> 1200px)**: 3-4 列卡片

卡片自动填满宽度，无留白，无横向滚动。

## 优势对比

| 特性 | 原生 Qt | Web 版本 |
|------|---------|----------|
| 响应式布局 | ❌ 复杂 | ✅ 一行 CSS |
| 卡片填满 | ❌ 难实现 | ✅ 自动 |
| 开发效率 | ❌ 低 | ✅ 高 |
| 内存占用 | ✅ 低 | ❌ +50MB |
| 打包体积 | ✅ 小 | ❌ +100MB |

## 调试方法

### 1. 启用 Web Inspector

在 `detection_page_web.py` 中添加：

```python
from PyQt6.QtWebEngineCore import QWebEngineSettings

# 启用开发者工具
settings = self.web_view.settings()
settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
```

### 2. 查看控制台日志

在 JavaScript 中使用 `console.log()` 输出调试信息。

## 已知问题

1. **首次加载慢**: QWebEngineView 初始化需要时间（约 1-2 秒）
2. **内存占用**: 增加约 50-80MB（Chromium 内核开销）
3. **打包体积**: 增加约 100MB（WebEngine 库）

## 后续优化

1. **性能优化**：虚拟滚动（只渲染可见卡片）
2. **功能增强**：分类筛选、排序、详情弹窗
3. **样式优化**：暗色主题、动画效果

## 参考资料

- [PyQt6 WebEngine 文档](https://www.riverbankcomputing.com/static/Docs/PyQt6/module_index.html)
- [QWebChannel 文档](https://doc.qt.io/qt-6/qwebchannel.html)
- [CSS Grid 布局](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Grid_Layout)

