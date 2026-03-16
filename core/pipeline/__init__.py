"""流程编排模块 — 线性流水线、DAG 重建、结果解析、导出。

子模块：
  - chart_data_parser: kreport / fastp 结果 → ECharts 数据
  - blast_result_parser: BLAST outfmt6 TSV → 物种汇总
  - detection_merger: 合并 kreport + BLAST 结果
  - report_generator: matplotlib PDF 检测报告
"""