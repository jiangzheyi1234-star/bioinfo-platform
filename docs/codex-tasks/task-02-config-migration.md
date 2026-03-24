# Task 2: config.py 数据库配置结构升级

## 目标
将 config.py 中 databases 段从扁平 key-value 改为结构化格式（db_root + overrides），支持旧格式自动迁移。

## 修改文件
`config.py`

## 背景
当前 config.json 的 databases 段是扁平格式：
```json
"databases": {
    "kraken2": "/home/zyserver/project_ssd/common_data/kraken2_standard",
    "checkm2": "",
    "gtdbtk": "",
    "blast_nt": "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt",
    "centrifuge": "/home/zyserver/project/lcy_project/my_database/hpvc"
}
```

需要改为：
```json
"databases": {
    "db_root": "",
    "overrides": {}
}
```

## 具体改动

### 1. `default_settings_schema()` (line ~54)
databases 段改为：
```python
"databases": {
    "db_root": "",           # 远端基础路径，如 /data/databases
    "overrides": {},         # 手动指定的路径覆盖 {db_id: absolute_path}
},
```

### 2. `_is_v2_schema()` (line ~99)
兼容新旧两种 databases 格式。当前检查 `isinstance(data.get("databases"), dict)` 已经兼容，无需改动。但要确保新格式也通过校验。

### 3. `normalize_config()` (line ~144)
增加旧格式迁移逻辑。在 `schema[section].update(section_data)` 之前，检测 databases 是否为旧扁平格式：

```python
# 在处理 databases section 时
section_data = data.get("databases")
if isinstance(section_data, dict):
    # 检测旧格式：有非 db_root/overrides 的 key 就是旧格式
    old_keys = {k for k in section_data if k not in ("db_root", "overrides")}
    if old_keys:
        # 迁移：非空值转为 overrides
        overrides = {k: v for k, v in section_data.items()
                     if k not in ("db_root", "overrides") and v}
        schema["databases"] = {
            "db_root": section_data.get("db_root", ""),
            "overrides": overrides,
        }
    else:
        schema["databases"].update(section_data)
```

### 4. `get_database_path(key)` (line ~203)
重写，删除所有硬编码 fallback：

```python
def get_database_path(key: str, default: str = "") -> str:
    config = get_config()
    databases = config.get("databases", {})
    # 优先级 1: overrides
    overrides = databases.get("overrides", {})
    if key in overrides and overrides[key]:
        return str(overrides[key])
    # 优先级 2: db_root + databases.yaml 的 install_path
    # （这里只返回 db_root，具体拼接由 DatabaseService 负责）
    db_root = databases.get("db_root", "")
    if db_root:
        return db_root  # 调用方会拼接 install_path
    return default
```

注意：删除原来的 centrifuge 和 blast_nt 硬编码 fallback 路径。

### 5. `migrate_legacy_config()` (line ~112)
不需要改动，这个函数处理的是 v1 → v2 的迁移，databases 段会被 normalize_config 处理。

### 6. `sync_default_from_schema()` (line ~223)
适配新格式。`databases` 不再有 `blast_nt` 等扁平 key：
```python
# 改前
"remote_db": str(databases.get("blast_nt") or blast["db_path"]),
# 改后
overrides = databases.get("overrides", {})
"remote_db": str(overrides.get("blast_nt") or blast["db_path"]),
```

## 约束
- 不引入新依赖
- 保持线程安全（已有的 `_CONFIG_CACHE_LOCK` 机制不变）
- 旧格式 config.json 加载后自动迁移，不报错

## 验证
```python
# 测试旧格式迁移
old_config = {
    "version": 2,
    "ssh": {...}, "linux": {...},
    "databases": {"kraken2": "/some/path", "checkm2": "", "blast_nt": "/other/path"},
    "blast": {...}, "ncbi": {...}, "runtime": {...}
}
result = normalize_config(old_config)
assert result["databases"]["db_root"] == ""
assert result["databases"]["overrides"] == {"kraken2": "/some/path", "blast_nt": "/other/path"}
assert "checkm2" not in result["databases"]["overrides"]  # 空值不迁移

# 测试新格式不变
new_config = {
    "version": 2,
    "ssh": {...}, "linux": {...},
    "databases": {"db_root": "/data/db", "overrides": {"kraken2": "/custom"}},
    "blast": {...}, "ncbi": {...}, "runtime": {...}
}
result = normalize_config(new_config)
assert result["databases"]["db_root"] == "/data/db"
assert result["databases"]["overrides"]["kraken2"] == "/custom"
```
