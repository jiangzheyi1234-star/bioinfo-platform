# Task 6: settings_page 适配 + tool_bridge_service 路径解析

## 目标
1. settings_page 适配新的 databases config 格式
2. tool_bridge_service 的 build_database_paths() 接入新的路径解析逻辑

## 修改文件
- `ui/pages/settings_page.py`
- `core/execution/tool_bridge_service.py`

## 依赖（需先完成）
- Task 2: config.py 新格式
- Task 3: DatabaseService

---

## Part A: settings_page.py 适配

### 问题
settings_page 中的 `_apply_schema_to_components()` 和 `_collect_schema_from_components()` 直接操作旧格式的 databases dict。需要适配新的 `{db_root, overrides}` 格式。

### 改动

#### 1. 移除 DatabasePathsCard
DatabasePathsCard 的功能已被 DatabasePage 取代。在 settings_page 中：

```python
# _init_cards() 中删除:
# self.db_card = DatabasePathsCard()
# self.db_card.request_save.connect(self.save_config)
# self.scroll_layout.addWidget(self.db_card)
```

或者保留一个简化版，只显示一行提示"数据库管理已移至独立页面"+ 跳转按钮。

#### 2. _apply_schema_to_components()
删除 databases 相关的硬编码 fallback（line ~128-133）：
```python
# 删除这些行:
# databases = dict(databases) if isinstance(databases, dict) else {}
# if not str(databases.get("kraken2", "") or "").strip():
#     databases["kraken2"] = "/home/zyserver/..."
# ...
# self.db_card.set_values(databases)
```

#### 3. _collect_schema_from_components()
删除 `db_values = self.db_card.get_values()` 和 `"databases": db_values`。

databases 段直接从 config 读取（不经过 UI 组件），因为数据库配置现在在 DatabasePage 管理：
```python
"databases": current.get("databases", {"db_root": "", "overrides": {}}),
```

#### 4. set_global_lock()
删除 `self.db_card.set_external_lock(locked)` 行。

#### 5. import
删除 `DatabasePathsCard` 的 import。

---

## Part B: tool_bridge_service.py 路径解析

### 问题
`build_database_paths()` (line ~1235) 当前从 `config.databases` 的扁平 key 做模糊匹配。需要改为：
1. 优先 overrides
2. 其次 db_root + databases.yaml 的 install_path
3. 兜底旧格式

### 改动

#### 1. 注入 DatabaseService
在 `ToolBridgeService.__init__()` 或通过 ServiceLocator 获取 DatabaseService 实例：

```python
from core.data.database_service import DatabaseService

class ToolBridgeService:
    def __init__(self, ...):
        ...
        self._database_service = DatabaseService()
```

#### 2. 重写 build_database_paths()

```python
def build_database_paths(self, tool_id: str, descriptor: dict | None = None) -> dict:
    from config import get_config
    cfg = get_config()
    db_cfg = cfg.get("databases", {})
    db_root = db_cfg.get("db_root", "")
    overrides = db_cfg.get("overrides", {})

    desc = descriptor or self._plugin_registry.get_descriptor(tool_id)
    if not desc:
        return {}

    db_decls = desc.get("databases", [])
    if not db_decls:
        return {}

    paths = {}
    for decl in db_decls:
        param_name = decl.get("param_name", decl.get("name", ""))
        db_id = decl.get("id", "")
        if not param_name:
            continue

        # 优先级 1: config overrides
        if db_id in overrides and overrides[db_id]:
            paths[param_name] = overrides[db_id]
            logger.debug("数据库 %s: 使用 override 路径 %s", db_id, overrides[db_id])
            continue

        # 优先级 2: db_root + databases.yaml install_path
        if db_root and self._database_service:
            resolved = self._database_service.get_resolved_path(db_id, db_root)
            if resolved:
                paths[param_name] = resolved
                logger.debug("数据库 %s: 使用 db_root 路径 %s", db_id, resolved)
                continue

        # 优先级 3: 旧格式兜底（过渡期）
        for legacy_key in (db_id, param_name):
            legacy_val = db_cfg.get(legacy_key)
            if legacy_val and isinstance(legacy_val, str):
                paths[param_name] = legacy_val
                logger.debug("数据库 %s: 使用旧格式路径 %s", db_id, legacy_val)
                break

    return paths
```

#### 3. 保留 extract_database_paths() 和 validate_required_databases()
这两个方法不需要改动，它们处理的是用户执行参数覆盖和必需校验，逻辑独立。

## 参考文件
- `core/execution/tool_bridge_service.py` — `build_database_paths()` (line ~1235), `extract_database_paths()` (line ~1372), `validate_required_databases()` (line ~1389)
- `ui/pages/settings_page.py` — 完整文件（258 行）
- `config.py` — Task 2 修改后的版本

## 验证
```bash
# 测试路径解析
pytest tests/test_tool_bridge_service.py -v -k "database"

# UI 冒烟测试（确保 settings_page 不崩溃）
QT_QPA_PLATFORM=offscreen pytest tests/test_ui_smoke.py -v
```

测试用例：
1. build_database_paths 使用 override 路径
2. build_database_paths 使用 db_root + install_path
3. build_database_paths 旧格式兜底
4. settings_page 无 DatabasePathsCard 不崩溃
