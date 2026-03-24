# Task 3: 新建 core/data/database_service.py

## 目标
创建数据库管理核心服务，提供 registry 加载、状态检测、安装命令生成、后台安装、进度解析、完整性校验功能。

## 新建文件
`core/data/database_service.py`（~400 行）

如果 `core/data/` 目录不存在，需要创建并添加 `__init__.py`。

## 架构约束
- Core 层模块，只允许 `PyQt6.QtCore`，禁止 QtWidgets/QtGui
- 实际上本模块不需要任何 Qt 依赖，纯 Python 即可
- 通过 `ssh_run_fn` 回调解耦 SSH 实现（与 `core/environment/env_installer.py` 一致）

## 依赖
- `SshRunFn` 类型来自 `core/environment/env_detector.py`：`Callable[[str, int], Tuple[int, str, str]]`
- `databases.yaml` 路径：`plugins/databases.yaml`（Task 1 已改为相对路径 + category）
- `yaml` 标准库
- `jinja2` 用于渲染 install_cmd 模板

## 数据结构

```python
from enum import Enum
from dataclasses import dataclass, field

class DatabaseStatus(Enum):
    NOT_INSTALLED = "not_installed"
    INCOMPLETE = "incomplete"
    READY = "ready"
    INSTALLING = "installing"
    UNKNOWN = "unknown"

@dataclass
class DatabaseInfo:
    db_id: str
    name: str
    description: str
    category: str           # reads / mag / annotation / amr / other
    install_path: str       # 相对路径
    size_mb: int
    tools: list[str] = field(default_factory=list)
    mirrors: list[dict] = field(default_factory=list)
    integrity_check: dict = field(default_factory=dict)
    install_cmd: str = ""
    env_var: str = ""
    builtin: bool = False

@dataclass
class DatabaseCheckResult:
    db_id: str
    status: DatabaseStatus
    message: str = ""
```

## DatabaseService 类 API

```python
class DatabaseService:
    INSTALL_BASE = "~/.h2ometa/db_installs"

    def __init__(self, databases_yaml_path: str = ""):
        """加载 databases.yaml registry。默认路径为 plugins/databases.yaml（相对于项目根目录）。"""

    def list_all(self) -> list[DatabaseInfo]:
        """返回所有非 builtin 数据库。"""

    def list_by_category(self) -> dict[str, list[DatabaseInfo]]:
        """按 category 分组返回。key 为 category 名，value 为该分类下的数据库列表。"""

    def get_info(self, db_id: str) -> DatabaseInfo | None:
        """根据 db_id 获取数据库信息。"""

    def get_resolved_path(self, db_id: str, db_root: str) -> str:
        """返回 db_root + "/" + install_path。builtin 返回空字符串。"""

    def check_status(self, ssh_run_fn, db_id: str, db_root: str) -> DatabaseCheckResult:
        """SSH 检测单个数据库状态。"""

    def check_all(self, ssh_run_fn, db_root: str) -> list[DatabaseCheckResult]:
        """批量检测所有非 builtin 数据库状态。"""

    def generate_install_commands(self, db_id: str, db_root: str, mirror_index: int = 0) -> list[str]:
        """生成安装命令序列（供 UI 预览和执行）。"""

    def submit_install(self, ssh_run_fn, db_id: str, db_root: str,
                       conda_exe: str = "", mirror_index: int = 0) -> dict:
        """通过 screen 后台启动安装。返回 {"job_id", "task_dir"}。"""

    def check_install_status(self, ssh_run_fn, task_dir: str) -> dict:
        """读取安装任务状态。返回 {"status": "RUNNING"/"DONE"/"FAILED", "exit_code": str}。"""

    def read_install_log(self, ssh_run_fn, task_dir: str, tail: int = 50) -> str:
        """tail task.log。"""

    def parse_progress(self, log_text: str) -> dict:
        """从 wget 日志解析下载进度。"""

    def verify_integrity(self, ssh_run_fn, db_id: str, db_root: str) -> DatabaseCheckResult:
        """安装后校验完整性。"""
```

## 关键实现细节

### check_status()
```python
def check_status(self, ssh_run_fn, db_id, db_root):
    info = self.get_info(db_id)
    if not info or info.builtin:
        return DatabaseCheckResult(db_id, DatabaseStatus.UNKNOWN)

    db_path = self.get_resolved_path(db_id, db_root)
    if not db_path:
        return DatabaseCheckResult(db_id, DatabaseStatus.NOT_INSTALLED, "db_root 未设置")

    # 检查 .install_ok 标记文件
    status_file = info.integrity_check.get("status_file", ".install_ok")
    if status_file:
        rc, _, _ = ssh_run_fn(f'test -f "{db_path}/{status_file}"', 10)
        if rc != 0:
            return DatabaseCheckResult(db_id, DatabaseStatus.NOT_INSTALLED)

    # 检查 key_files
    key_files = info.integrity_check.get("key_files", [])
    for kf in key_files:
        rc, _, _ = ssh_run_fn(f'test -e "{db_path}/{kf}"', 10)
        if rc != 0:
            return DatabaseCheckResult(db_id, DatabaseStatus.INCOMPLETE, f"缺少: {kf}")

    return DatabaseCheckResult(db_id, DatabaseStatus.READY)
```

### generate_install_commands()
```python
def generate_install_commands(self, db_id, db_root, mirror_index=0):
    info = self.get_info(db_id)
    db_path = self.get_resolved_path(db_id, db_root)
    commands = [f'mkdir -p "{db_path}"']

    if info.install_cmd:
        # 渲染 Jinja2 模板
        from jinja2 import Template
        rendered = Template(info.install_cmd).render(db_path=db_path)
        commands.append(rendered)
    elif info.mirrors:
        mirror = info.mirrors[mirror_index] if mirror_index < len(info.mirrors) else info.mirrors[0]
        url = mirror["url"]
        commands.append(f'cd "{db_path}"')
        commands.append(f'wget -c --progress=dot:giga "{url}" -O archive.tar.gz')
        commands.append('tar xzf archive.tar.gz')
        commands.append('rm -f archive.tar.gz')

    commands.append(f'touch "{db_path}/.install_ok"')
    return commands
```

### parse_progress()
解析 wget `--progress=dot:giga` 格式的输出。该格式每行末尾有百分比：
```
     0K .......... .......... .......... ..........  0% 1.2M 3h22m
 50000K .......... .......... .......... .......... 50% 2.1M 1h41m
```

```python
import re

def parse_progress(self, log_text: str) -> dict:
    """从 wget dot:giga 日志解析进度。"""
    result = {}
    # 匹配最后一个百分比行
    matches = re.findall(r'(\d+)%\s+([\d.]+[KMG]?/s)?\s*([\dhms]+)?', log_text)
    if matches:
        last = matches[-1]
        result["percent"] = int(last[0])
        if last[1]:
            result["speed"] = last[1]
        if last[2]:
            result["eta"] = last[2]
    return result
```

### submit_install()
复用 `core/environment/env_installer.py` 的 screen 模式。参考该文件的 `_INSTALL_WRAPPER` 模板和 `EnvInstaller.submit()` 方法。

关键点：
- 任务目录：`~/.h2ometa/db_installs/{db_id}/`
- 脚本写入：base64 编码通过 SSH 写入 `install.sh`
- screen 启动：`screen -dmS h2o_dbinstall_{db_id} bash install.sh`
- 状态文件：status.txt（RUNNING/DONE/FAILED）、heartbeat.txt、task.log、exit_code.txt
- 包装脚本需要 trap EXIT 写状态

包装脚本模板（简化版，参考 env_installer.py 的 `_INSTALL_WRAPPER`）：
```bash
#!/bin/bash
set -euo pipefail
TASK_DIR="{task_dir}"
STATUS_FILE="$TASK_DIR/status.txt"
LOG_FILE="$TASK_DIR/task.log"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"

echo "RUNNING" > "$STATUS_FILE"

_heartbeat() { while true; do date +%s > "$HEARTBEAT_FILE"; sleep 30; done; }
_heartbeat &
HB_PID=$!

_cleanup() {
    local ec=$?
    kill $HB_PID 2>/dev/null || true
    echo "$ec" > "$EXIT_CODE_FILE"
    if [ "$ec" -eq 0 ]; then echo "DONE" > "$STATUS_FILE"; else echo "FAILED" > "$STATUS_FILE"; fi
}
trap _cleanup EXIT

exec > "$LOG_FILE" 2>&1

{commands}
```

## 参考文件
- `core/environment/env_installer.py` — screen 模式的完整实现，直接参考其 submit/check_status/read_log/is_session_alive/cleanup 方法
- `core/environment/env_detector.py` — `SshRunFn` 类型定义（line 18）
- `plugins/databases.yaml` — 数据源（Task 1 修改后的版本）

## 验证
```bash
# 单元测试（mock ssh_run_fn）
pytest tests/test_database_service.py -v
```

测试用例：
1. `test_load_registry` — 加载 databases.yaml，验证所有条目解析正确
2. `test_list_by_category` — 分组正确
3. `test_get_resolved_path` — db_root + install_path 拼接正确
4. `test_check_status_ready` — mock ssh 返回 rc=0，状态为 READY
5. `test_check_status_not_installed` — mock ssh 返回 rc=1，状态为 NOT_INSTALLED
6. `test_generate_install_commands_mirror` — 生成 wget 命令序列
7. `test_generate_install_commands_install_cmd` — 渲染 Jinja2 模板
8. `test_parse_progress` — 解析 wget 输出百分比
