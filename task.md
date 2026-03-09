# 工具环境管理功能 — 实施计划

## 目标
在 Settings 页的 `LinuxSettingsCard` 中实现完整的"检测 + 安装"闭环：
1. **一键检测** — SSH 查询 `conda env list`，对比每个工具的 `conda_env` 字段（✅ 已实现）
2. **点击安装** — 检测到 ❌ 的工具，每行显示"安装"按钮，点击后弹出进度对话框执行 `conda create`
3. **数据库提示** — 对需要数据库的工具，安装环境后自动提示填写数据库路径

---

## 工具环境与数据库对照表（来自各 tool.yaml）

| 工具       | conda_env      | 需要数据库 | 数据库 ID          | 大小      |
|------------|----------------|-----------|-------------------|-----------|
| fastp      | fastp_env      | 否        | —                 | —         |
| hostile    | hostile_env    | 否（内置） | —                 | —         |
| kraken2    | kraken2_env    | 是        | kraken2_standard  | ~50 GB    |
| megahit    | megahit_env    | 否        | —                 | —         |
| metaspades | metaspades_env | 否        | —                 | —         |
| metabat2   | metabat2_env   | 否        | —                 | —         |
| maxbin2    | maxbin2_env    | 否        | —                 | —         |
| concoct    | concoct_env    | 否        | —                 | —         |
| das_tool   | dastool_env    | 否        | —                 | —         |
| checkm2    | checkm2_env    | 是        | checkm2_db        | ~3.5 GB   |
| busco      | busco_env      | 否（内置） | —                 | —         |
| gtdbtk     | gtdbtk_env     | 是        | gtdb_r220         | ~110 GB   |
| prokka     | prokka_env     | 否        | —                 | —         |
| bakta      | bakta_env      | 是        | bakta_db          | ~35 GB    |
| eggnog     | eggnog_env     | 是        | eggnog_db         | ~45 GB    |
| blastn     | blastn_env     | 是        | blast_nt/core_nt  | ~350 GB   |

---

## 安装命令（将写入各 tool.yaml 的 install_cmd 字段）

| conda_env      | install_cmd                                                                 |
|----------------|-----------------------------------------------------------------------------|
| fastp_env      | `conda create -n fastp_env -c bioconda -c conda-forge fastp -y`             |
| hostile_env    | `conda create -n hostile_env -c bioconda -c conda-forge hostile -y`         |
| kraken2_env    | `conda create -n kraken2_env -c bioconda -c conda-forge kraken2 -y`         |
| megahit_env    | `conda create -n megahit_env -c bioconda -c conda-forge megahit -y`         |
| metaspades_env | `conda create -n metaspades_env -c bioconda -c conda-forge spades -y`       |
| metabat2_env   | `conda create -n metabat2_env -c bioconda -c conda-forge metabat2 -y`       |
| maxbin2_env    | `conda create -n maxbin2_env -c bioconda -c conda-forge maxbin2 -y`         |
| concoct_env    | `conda create -n concoct_env -c bioconda -c conda-forge concoct -y`         |
| dastool_env    | `conda create -n dastool_env -c bioconda -c conda-forge das_tool -y`        |
| checkm2_env    | `conda create -n checkm2_env -c bioconda -c conda-forge checkm2 -y`         |
| busco_env      | `conda create -n busco_env -c bioconda -c conda-forge busco -y`             |
| gtdbtk_env     | `conda create -n gtdbtk_env -c bioconda -c conda-forge gtdbtk -y`           |
| prokka_env     | `conda create -n prokka_env -c bioconda -c conda-forge prokka -y`           |
| bakta_env      | `conda create -n bakta_env -c bioconda -c conda-forge bakta -y`             |
| eggnog_env     | `conda create -n eggnog_env -c bioconda -c conda-forge eggnog-mapper -y`    |
| blastn_env     | `conda create -n blastn_env -c bioconda -c conda-forge blast -y`            |

---

## 实施步骤（按顺序执行）

### 步骤 1：为 16 个 tool.yaml 添加 install_cmd 字段 [ ]
在每个 tool.yaml 的 `conda_env` 字段下方添加 `install_cmd`：
```yaml
conda_env: fastp_env
install_cmd: "conda create -n fastp_env -c bioconda -c conda-forge fastp -y"
```
安装命令跟着插件定义走，UI 层不硬编码。

### 步骤 2：改造 LinuxSettingsCard 工具列表行布局 [ ]
**文件**：`ui/widgets/linux_settings_card.py`
- 每行布局从 `[工具名][环境名][状态]` 改为 `[工具名][环境名][状态][安装按钮]`
- 安装按钮初始隐藏；`_on_tool_checked()` 时：❌ → 显示"安装"，✅ → 隐藏
- 点击安装按钮 → 调用 `_on_install_click(tool_id)`

### 步骤 3：实现 EnvInstallDialog [ ]
**定义在** `linux_settings_card.py`（避免新建文件）：
```
┌─ 安装工具环境 ──────────────────────────────┐
│ 工具:     Kraken2 (kraken2_env)              │
│ 命令:     conda create -n kraken2_env ...    │
│ 需要数据库: 是（kraken2_standard, ~50 GB）    │
│                                              │
│ 安装输出（实时滚动）:                         │
│  > Collecting package metadata...            │
│  > Solving environment...                    │
│                                              │
│  [取消]                    [开始安装]         │
└──────────────────────────────────────────────┘
```
- `QDialog` + 只读 `QTextEdit` 显示实时输出
- 安装完成：按钮变为"关闭"，输出末尾加"✅ 安装成功"
- 若工具有数据库依赖：底部黄色提示条 "请在设置页填写 xxx 数据库路径"

### 步骤 4：实现 EnvInstallWorker [ ]
**定义在** `linux_settings_card.py`：
```python
class EnvInstallWorker(QObject):
    output_line = pyqtSignal(str)   # 每行输出
    finished = pyqtSignal(bool)     # True=成功
    error = pyqtSignal(str)
```
`run()` 流程：
1. `client.exec_command(install_cmd, timeout=600)`
2. 循环 `stdout.readline()` → emit `output_line`
3. `stdout.channel.recv_exit_status()` → emit `finished(rc == 0)`

### 步骤 5：安装完成后重新检测 + 数据库提示 [ ]
`EnvInstallDialog` 关闭后：
- 调用 `LinuxSettingsCard._on_batch_check()` 重新检测全部工具
- 若工具有 `databases` 声明：弹出 `QMessageBox` 提示跳转到数据库配置

---

## 文件改动汇总

| 文件 | 改动 |
|------|------|
| `plugins/*/tool.yaml`（16个） | 添加 `install_cmd` 字段 |
| `ui/widgets/linux_settings_card.py` | 行布局加安装按钮；新增 `EnvInstallWorker`、`EnvInstallDialog` |

---

## 验收标准

1. 一键检测后，❌ 的工具行右侧出现"安装"按钮
2. 点击"安装"弹出对话框，显示工具名/命令/数据库信息
3. 点击"开始安装"，SSH 执行 `conda create`，输出实时滚动
4. 安装完成后自动重新检测，该工具变为 ✅
5. 需要数据库的工具安装后显示黄色提示条

---

## 进度

- [x] 调研：读取所有 tool.yaml 确认字段和安装命令
- [x] 步骤 1：16 个 tool.yaml 添加 install_cmd ✅
- [x] 步骤 2：linux_settings_card 行布局改造（加安装按钮）✅
- [x] 步骤 3：EnvInstallDialog 实现（确认+实时输出）✅
- [x] 步骤 4：EnvInstallWorker 实现（SSH 流式输出）✅
- [x] 步骤 5：安装后重新检测 + 数据库提示 ✅

**全部完成（2026-03-09）**
