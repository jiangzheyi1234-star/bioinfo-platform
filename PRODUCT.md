# H2OMeta — 产品需求文档

> 描述软件要做什么，供开发决策参考。技术实现见 ARCHITECTURE.md，开发规则见 CLAUDE.md。
> 最后更新：2026-03-07

---

## 目标用户

**湿实验室研究人员**：会操作测序仪，懂生物学，但不擅长命令行。
核心诉求：上传数据 → 选分析 → 看结果 → 写论文，全程不需要记命令。

**生物信息学分析员**：需要批量处理多样本、自定义参数、追溯历史记录。

---

## 核心使用场景

1. 上传双端 FASTQ → 一键运行读长分析（QC+物种分类）→ 看到物种组成饼图和 QC 报告
2. 上传 FASTQ → 运行 MAG 重建流水线 → 得到注释好的基因组 + 功能注释表
3. 污水样品 → 运行 AMR 分析 → 看到 ARG 热图 + 质粒/整合子携带情况
4. 多个项目并行 → 各自独立数据库 → 导出论文 Methods 段落和参数 CSV

---

## 导航结构与功能需求

### 项目管理页 ✅
- 卡片式项目列表，每个项目显示样本数/任务数/最后活动时间
- 创建项目（名称+描述+本地路径）
- 打开/切换项目（全局状态切换）
- 归档项目（只读，不删数据）
- 导出项目（论文 Methods + 参数 CSV + ZIP 归档）

### 分析工作台 ❌ 未建
当前用硬编码的读长分析页和组装分析页代替，最终目标：
- **向导模式**：选择分析目的（物种鉴定/MAG 重建/AMR 分析）→ 逐步引导参数配置 → 一键提交
- **自由模式**：工具浏览器，按类别（QC/组装/注释/AMR）列出所有可用工具，单独配置运行

### 读长分析页 ⚠️ 跑通但不完整
固定三步流水线：fastp → hostile → kraken2 + bracken
- 样本选择 + FASTQ 导入
- 参数配置面板（每步可展开）
- 实时阶段状态（pending/running/completed/failed）
- **缺失**：结果图表（fastp QC 图、Kraken2 物种饼图）
- **缺失**：Bracken 丰度估算步骤

### 组装分析页 ⚠️ 仅 step1
四步流水线：megahit/metaspades → binning（三工具+DAS_Tool）→ checkm2 → gtdbtk + bakta + eggnog
- **step1（组装）**：有执行逻辑 ✅
- **step2（binning）**：UI 有，无执行逻辑 ❌
- **step3（质量评估）**：UI 有，无执行逻辑 ❌
- **step4（注释）**：UI 有，无执行逻辑 ❌

### AMR 分析页 ❌ 未建（污水研究核心）
专为城市污水/环境样品设计，三步联合分析：
- **ARG 注释**：RGI (CARD) reads 模式（快速）或 contig 模式（精准）
- **MGE 识别**：geNomad（质粒+噬菌体）+ IntegronFinder（整合子）+ ISEScan（IS 元件）
- **结果展示**：ARG 热图（样本×ARG类别）+ 质粒携带 ARG 列表 + 毒力因子表

### 结果浏览页 ❌ 未建
- 可视化图表（matplotlib）：fastp QC 柱状图、Kraken2 物种饼图/堆叠柱状图、ARG 热图
- DAG 流程图：从 SQLite 重建执行历史，显示数据节点和工具节点
- 数据表格：data_items 列表，可筛选 tier（raw/intermediate/result）
- 下载按钮：从远端同步 result 文件到本地

### 病原体检测页 ✅
BLAST 核酸比对，已迁移至 ToolEngine。

### 数据库管理页 ❌ 未建
- 列出所有工具依赖的数据库（kraken2 标准库、checkm2 数据库、CARD 数据库等）
- 显示安装状态（已安装/未安装/需更新）+ 磁盘占用
- 一键安装（优先国内镜像），安装进度实时显示
- 校验完整性（md5/文件数量）

### 系统设置页 ✅
SSH 连接配置（host/port/user/key）、NCBI API Key、远端工作目录。

---

## 标准宏基因组流程与插件覆盖

> 参考 nf-core/mag、EasyMetagenome、MetaflowX（2025）

| 阶段 | 工具 | 插件 |
|------|------|------|
| QC + 接头去除 | fastp | ✅ |
| 宿主去除 | hostile | ✅ |
| 物种分类 | Kraken2 | ✅ |
| 丰度估算 | Bracken | ❌ |
| 物种可视化 | Krona | ❌ |
| 多样本 QC 汇总 | MultiQC | ❌ |
| 序列组装 | MEGAHIT / metaSPAdes | ✅ |
| 组装质量评估 | QUAST | ❌ |
| 分箱 | MetaBAT2 + MaxBin2 + CONCOCT + DAS_Tool | ✅ |
| MAG 质量 | CheckM2 / BUSCO | ✅ |
| MAG 分类 | GTDB-Tk | ✅ |
| 基因预测+注释 | Prokka / Bakta | ✅ |
| 功能注释 | eggNOG-mapper v2 | ✅ |
| 蛋白质域 | InterProScan | ❌ |
| 核酸比对 | blastn | ✅ |

**当前：16 个插件**，主干流程已覆盖。

### 城市污水专项（AMR/Mobilome）

> 污水研究的核心分析维度：**resistome + mobilome 联合**，与常规宏基因组有本质区别。

| 工具 | 用途 | 优先级 | 插件 |
|------|------|--------|------|
| RGI (CARD) | ARG 注释，reads+contig 双模式，SNP 感知 | P0 | ❌ |
| geNomad | 质粒+噬菌体识别（2024 Nature Biotech）| P0 | ❌ |
| IntegronFinder | 整合子检测（ARG 水平转移主要载体）| P1 | ❌ |
| ISEScan | 插入序列（IS elements）| P1 | ❌ |
| AMRFinderPlus | NCBI 官方 AMR，与 RGI 互补 | P1 | ❌ |
| QUAST | 组装质量评估 | P1 | ❌ |
| VirulenceFinder | 毒力因子（ESKAPE 病原体）| P2 | ❌ |

**关键结论**：
- OXA β-内酰胺酶（碳青霉烯耐药）常连质粒传播 → geNomad 必须有
- Class 1 整合子在污水处理全程普遍检出 → IntegronFinder 必须有
- ESKAPE 病原体（克雷伯菌、肠杆菌）在污水出水 >1% 丰度 → VirulenceFinder 重要

### 三条分析路径

```
reads 路径:  fastp → hostile → kraken2 + bracken → krona
MAG 路径:    fastp → hostile → megahit/metaspades → [binning] → checkm2 → gtdbtk → bakta → eggnog
AMR 路径:    fastp → hostile → megahit → prokka/bakta → RGI + geNomad + IntegronFinder
```

---

## 明确不做的事

- 不支持 16S rRNA 扩增子测序（只做宏基因组 shotgun）
- 不内置数据可视化服务器（用 matplotlib 本地渲染，不用 web 技术）
- 不支持三代测序（ONT/PacBio）的专属组装工具（HiFiAsm 等）
- 不做工作流程共享/协作功能（单机单用户）
- 不做云存储/云计算对接（只做本地桌面 + SSH 到自有服务器）

---

## 插件待补充清单（按优先级）

```
P0（读长分析路径必需）:   bracken, krona
P0（污水 AMR 分析必需）:  rgi, genomad
P1（分析完整性）:         integron_finder, iss_can, quast, amrfinderplus
P2（进阶功能）:           multiqc, interproscan, virulencefinder
```
