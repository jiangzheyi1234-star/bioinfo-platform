# 病原检测页版本切换指南

## 快速切换

### 使用 Web 版本（推荐）
在 `ui/main_window.py` 第 29 行：
```python
USE_WEB_DETECTION = True
```

### 使用原生 Qt 版本
在 `ui/main_window.py` 第 29 行：
```python
USE_WEB_DETECTION = False
```

## 版本对比

| 特性 | 原生 Qt 版本 | Web 版本 |
|------|-------------|----------|
| 文件 | `detection_page.py` | `detection_page_web.py` |
| 布局引擎 | QGridLayout | CSS Grid |
| 响应式 | 部分支持 | 完美支持 |
| 卡片填满 | 困难 | 自动 |
| 内存占用 | 低 | +50-80MB |
| 开发效率 | 低 | 高 |
| 调试工具 | Qt Inspector | 浏览器开发者工具 |

## 依赖要求

### 原生 Qt 版本
```bash
pip install PyQt6
```

### Web 版本
```bash
pip install PyQt6 PyQt6-WebEngine
```

## 故障排除

### Web 版本无法启动
1. 检查 PyQt6-WebEngine 是否安装：
   ```bash
   python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; print('OK')"
   ```

2. 检查 HTML 文件是否存在：
   ```bash
   ls ui/pages/detection_page_assets/index.html
   ```

3. 查看日志输出：
   ```bash
   python -m ui.main 2>&1 | grep -i "detection\|web"
   ```

### 回退到原生版本
如果 Web 版本出现问题，立即切换回原生版本：
```python
USE_WEB_DETECTION = False
```

## 测试方法

### 测试 Web 版本
```bash
python test_web_detection.py
```

### 测试原生版本
```bash
python -m ui.main
# 在主窗口中切换到"病原检测"页面
```

## 性能对比

### 启动时间
- 原生版本：< 0.5 秒
- Web 版本：1-2 秒（首次加载 Chromium 内核）

### 内存占用
- 原生版本：~50MB
- Web 版本：~100-130MB

### 响应速度
- 原生版本：即时
- Web 版本：即时（加载后）

## 推荐使用场景

### 使用 Web 版本
- 需要完美的响应式布局
- 需要快速迭代 UI 设计
- 内存和体积不是限制因素

### 使用原生版本
- 需要最小化内存占用
- 需要最快的启动速度
- 不需要复杂的响应式布局
