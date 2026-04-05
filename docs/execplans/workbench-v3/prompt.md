# Workbench V3 Prompt

## Goal
把“结果工作台”改造成统一结果壳层，UI 对齐目标稿：
- 左侧分区：`分析功能` + `历史结果`
- 顶部运行入口分离：`启动分析` / `重新运行` 按钮，不再使用页面内执行卡片
- 主区统一模板：`KPI -> 数据表格 -> 图表 -> 产物文件 -> 溯源信息`
- 不同功能点击后可展示真实结果或“等待运行”空状态

## Feature Scope
- 病原体引物设计（`primer_design`）
- 多重引物池设计（`multiplex_primer_panel`）
- 靶向测序分析（`targeted_sequencing` -> `centrifuge` / `kraken2`）
- 未知样品检测（`unknown_sample_detection`）
- 废水宏基因组基础分析（`wastewater_metagenomics_basic`）
- 动物源宏基因组基础分析（`animal_metagenomics_basic`）
- 基因组分析（`target_screening`，占位）

## Hard Constraints
- 运行入口必须通过 Modal 打开，不和结果卡片混排。
- 历史结果支持固定/取消固定与关闭。
- 扩展新功能时以注册配置驱动，不要求改 UI 结构代码。
- 不新增 SQLite 执行状态枚举。

## Done When
1. 页面不再包含旧执行入口块（`integrated-run-card`）。
2. 侧边栏具备分析/历史两段容器并正确渲染。
3. 结果 tabs 固定为 `table/chart/artifacts/provenance`。
4. 后端返回的分析功能顺序稳定，不受插入路径影响。
