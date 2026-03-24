# Task 7: 清理 tool.yaml 硬编码 default + 更新 __init__.py

## 目标
清理所有 tool.yaml 中 databases 段的硬编码 default 路径，更新 widgets/__init__.py 导出。

## 修改文件

### 1. tool.yaml 文件（有 databases 段且非空的）

以下文件的 `databases:` 段中有 `default:` 字段需要清理：

```
plugins/taxonomy/kraken2/tool.yaml      — default: "/home/zyserver/project_ssd/common_data/kraken2_standard"
plugins/taxonomy/centrifuge/tool.yaml   — 检查是否有 default
plugins/taxonomy/gtdbtk/tool.yaml       — 检查是否有 default
plugins/taxonomy/metaphlan/tool.yaml    — 检查是否有 default
plugins/taxonomy/bracken/tool.yaml      — 检查是否有 default
plugins/annotation/bakta/tool.yaml      — 检查是否有 default
plugins/annotation/eggnog/tool.yaml     — 检查是否有 default
plugins/amr/rgi/tool.yaml              — 检查是否有 default
plugins/amr/amrfinderplus/tool.yaml    — 检查是否有 default
plugins/blast/blastn/tool.yaml         — 检查是否有 default
plugins/quality/checkm2/tool.yaml      — 检查是否有 default
plugins/quality/busco/tool.yaml        — 检查是否有 default
plugins/quality/gunc/tool.yaml         — 检查是否有 default
plugins/mobile_elements/genomad/tool.yaml — 检查是否有 default
plugins/detection/unknown_sample_detection/tool.yaml — 检查是否有 default
plugins/primer/multiplex_primer_panel/tool.yaml — 检查是否有 default
plugins/primer/primer_design/tool.yaml — 检查是否有 default
```

### 操作
对每个文件：
1. 找到 `databases:` 段
2. 如果有 `default:` 字段且值为硬编码路径（包含 `/home/` 或 `/h2ometa/` 或其他绝对路径），删除该行或改为 `default: ""`
3. 保留 `id`、`param_name`、`required`、`label`、`description`、`scope` 等字段不变

示例：
```yaml
# 改前 (kraken2/tool.yaml)
databases:
  - id: kraken2_standard
    param_name: db
    required: true
    label: "Kraken2 标准数据库"
    description: "..."
    scope: "..."
    default: "/home/zyserver/project_ssd/common_data/kraken2_standard"

# 改后
databases:
  - id: kraken2_standard
    param_name: db
    required: true
    label: "Kraken2 标准数据库"
    description: "..."
    scope: "..."
```

### 2. ui/widgets/__init__.py

添加新组件导出：

```python
try:
    from .database_management_components import (
        DatabaseItemCard, DatabaseInstallDialog,
        DatabaseStatusWorker, DatabaseInstallMonitor,
    )
except Exception:  # pragma: no cover
    DatabaseItemCard = None  # type: ignore
    DatabaseInstallDialog = None  # type: ignore
    DatabaseStatusWorker = None  # type: ignore
    DatabaseInstallMonitor = None  # type: ignore
```

在 `__all__` 中添加：
```python
"DatabaseItemCard", "DatabaseInstallDialog",
"DatabaseStatusWorker", "DatabaseInstallMonitor",
```

可以移除 `DatabasePathsCard` 的导出（或保留为 deprecated）。

## 验证
```bash
# 检查所有 tool.yaml 不含硬编码路径
grep -rn "default:.*\/home\/" plugins/*/tool.yaml plugins/*/*/tool.yaml
grep -rn "default:.*\/h2ometa\/" plugins/*/tool.yaml plugins/*/*/tool.yaml
# 应该无输出

# YAML 语法检查
python -c "
import yaml, glob
for f in glob.glob('plugins/*/*/tool.yaml'):
    yaml.safe_load(open(f))
    print(f'OK: {f}')
"

# import 检查
python -c "from ui.widgets import DatabaseItemCard; print('OK')"
```
