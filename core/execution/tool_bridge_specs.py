from __future__ import annotations

from typing import Any


DETECTION_WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "unknown_sample_detection": {
        "feature": {
            "id": "unknown_sample_detection",
            "name": "未知样品检测",
            "badge": "mNGS",
            "description": "二代宏基因组鸟枪法测序 → fastp 质控 → hostile 去宿主 → Centrifuge 分类 + BLAST 补充鉴定 → PDF 检测报告。",
            "status": "active",
        },
        "view": {
            "feature_id": "unknown_sample_detection",
            "tool_ids": ["unknown_sample_detection"],
            "title": "未知样品病原体检测 (mNGS)",
            "description": "二代宏基因组鸟枪法测序全流程：fastp 质控 → hostile 去宿主 → Centrifuge 分类 → BLAST 补充鉴定 → 合并结果 PDF 报告。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交二代宏基因组双端 FASTQ 后，系统自动执行 QC → 去宿主 → 分类 → 报告全流程。",
            },
            "summary": [
                {"label": "原始 Reads", "value": "—", "tone": "primary"},
                {"label": "QC 后", "value": "—", "tone": "info"},
                {"label": "去宿主后", "value": "—", "tone": "info"},
                {"label": "宿主占比", "value": "—", "tone": "warning"},
                {"label": "已分类", "value": "—", "tone": "success"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "table": {
                "title": "检出微生物列表",
                "subtitle": "按 Reads 数降序排列，包含细菌、病毒、真菌、寄生虫等各类微生物。",
                "columns": [
                    {"key": "rank", "label": "#"},
                    {"key": "name", "label": "微生物名称"},
                    {"key": "category", "label": "类型"},
                    {"key": "reads", "label": "Reads"},
                    {"key": "rpm", "label": "RPM"},
                    {"key": "percentage", "label": "相对丰度 (%)"},
                    {"key": "source", "label": "检出来源"},
                ],
                "rows": [],
            },
            "artifacts": [],
            "charts": [],
            "provenance": {
                "parameters": [
                    {"label": "输入", "value": "二代宏基因组双端 FASTQ (PE150)"},
                    {"label": "质控", "value": "fastp 接头去除 + 低质量过滤"},
                    {"label": "去宿主", "value": "hostile (human-t2t-hla)"},
                    {"label": "分类引擎", "value": "Centrifuge + HPVC 数据库"},
                    {"label": "补充鉴定", "value": "BLAST + core_nt (未分类 reads)"},
                    {"label": "输出", "value": "物种表 + 饼图 + PDF 检测报告"},
                ],
            },
        },
        "legacy_workflow": "unknown_detection",
    },
    "wastewater_metagenomics_basic": {
        "feature": {
            "id": "wastewater_metagenomics_basic",
            "name": "废水宏基因组基础分析",
            "badge": "ENV",
            "description": "面向废水监测的读长宏基因组闭环：fastp → 可选 hostile → Kraken2 → Bracken → Krona。",
            "status": "active",
        },
        "view": {
            "feature_id": "wastewater_metagenomics_basic",
            "tool_ids": ["wastewater_metagenomics_basic"],
            "title": "废水宏基因组基础分析",
            "description": "面向废水监测的 read-based 宏基因组分析：fastp 质控 → 可选 hostile 去宿主 → Kraken2 分类 → Bracken 丰度重估计 → Krona 可视化。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交双端 FASTQ 后，系统自动完成 QC、分类、丰度重估计与 Krona 输出。",
            },
            "summary": [
                {"label": "总 Reads", "value": "—", "tone": "primary"},
                {"label": "已分类", "value": "—", "tone": "info"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "table": {
                "title": "废水样本微生物组成",
                "subtitle": "基于 Kraken2/Bracken 的读长分类结果，按丰度降序排列。",
                "columns": [
                    {"key": "rank", "label": "序号"},
                    {"key": "name", "label": "微生物名称"},
                    {"key": "reads", "label": "Reads 数"},
                    {"key": "percentage", "label": "占比 (%)"},
                ],
                "rows": [],
            },
            "artifacts": [],
            "charts": [],
            "provenance": {
                "parameters": [
                    {"label": "输入", "value": "废水样本双端 FASTQ"},
                    {"label": "质控", "value": "fastp"},
                    {"label": "可选去宿主", "value": "hostile (可关闭)"},
                    {"label": "分类/丰度", "value": "Kraken2 + Bracken"},
                    {"label": "输出", "value": "kreport + Bracken 表 + Krona HTML"},
                ],
            },
        },
    },
    "animal_metagenomics_basic": {
        "feature": {
            "id": "animal_metagenomics_basic",
            "name": "动物源宏基因组基础分析",
            "badge": "Animal",
            "description": "面向动物样本的读长宏基因组闭环：fastp → hostile → Kraken2 → Bracken → Krona。",
            "status": "active",
        },
        "view": {
            "feature_id": "animal_metagenomics_basic",
            "tool_ids": ["animal_metagenomics_basic"],
            "title": "动物源宏基因组基础分析",
            "description": "面向动物所病原筛查的 read-based 宏基因组分析：fastp 质控 → hostile 宿主去除 → Kraken2 分类 → Bracken 丰度重估计 → Krona 可视化。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交双端 FASTQ 与宿主索引后，系统自动完成 QC、去宿主、分类、丰度重估计与 Krona 输出。",
            },
            "summary": [
                {"label": "总 Reads", "value": "—", "tone": "primary"},
                {"label": "已分类", "value": "—", "tone": "info"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "table": {
                "title": "动物样本微生物组成",
                "subtitle": "基于 Kraken2/Bracken 的读长分类结果，适用于动物源样本的基础检出与丰度查看。",
                "columns": [
                    {"key": "rank", "label": "序号"},
                    {"key": "name", "label": "微生物名称"},
                    {"key": "reads", "label": "Reads 数"},
                    {"key": "percentage", "label": "占比 (%)"},
                ],
                "rows": [],
            },
            "artifacts": [],
            "charts": [],
            "provenance": {
                "parameters": [
                    {"label": "输入", "value": "动物样本双端 FASTQ"},
                    {"label": "质控", "value": "fastp"},
                    {"label": "宿主去除", "value": "hostile (宿主索引必填)"},
                    {"label": "分类/丰度", "value": "Kraken2 + Bracken"},
                    {"label": "输出", "value": "kreport + Bracken 表 + Krona HTML"},
                ],
            },
        },
    },
}

DETECTION_WORKFLOW_ORDER = tuple(DETECTION_WORKFLOW_SPECS)
TARGETED_RESULT_TOOL_IDS = ("centrifuge", "kraken2", *DETECTION_WORKFLOW_ORDER)


def build_integrated_workbench_config() -> dict[str, Any]:
    return {
        "title": "集成分析工作台",
        "subtitle": "集中承载多个分析能力，统一查看流程状态与分析结果。",
        "features": [
            {
                "id": "primer_design",
                "name": "病原体引物设计",
                "badge": "",
                "description": "上传病原体基因组，自动筛选保守特异靶点并设计引物对，输出每病原体的推荐引物。",
                "status": "active",
            },
            {
                "id": "targeted_sequencing",
                "name": "靶向测序分析",
                "badge": "tNGS",
                "description": "纳米孔靶向扩增测序 → Centrifuge + HPVC 快速鉴定，输出病原体物种组成表与检测报告。",
                "status": "active",
            },
            {
                "id": "unknown_sample_detection",
                "name": "未知样品检测",
                "badge": "mNGS",
                "description": "二代宏基因组鸟枪法测序 → fastp 质控 → hostile 去宿主 → Centrifuge 分类 + BLAST 补充鉴定 → PDF 检测报告。",
                "status": "active",
            },
            {
                "id": "target_screening",
                "name": "基因组分析",
                "badge": "",
                "description": "按同一工作台布局接入基因组分析能力。",
                "status": "placeholder",
            },
        ],
        "views": {
            "primer_design": {
                "tool_ids": ["primer_design"],
                "title": "病原体引物设计",
                "description": "上传病原体基因组序列，系统自动完成保守靶点筛选、特异性过滤和候选引物设计，最终输出每病原体的推荐引物对。",
                "status": {
                    "state": "ready",
                    "label": "结果已就绪",
                    "detail": "支持查看推荐结果，并可继续接入远程任务执行链路。",
                },
                "summary": [
                    {"label": "目标病原体", "value": "5", "tone": "primary"},
                    {"label": "候选引物对", "value": "18", "tone": "info"},
                    {"label": "通过二聚体过滤", "value": "9", "tone": "success"},
                    {"label": "最终推荐", "value": "5", "tone": "accent"},
                ],
                "table": {
                    "title": "分析结果",
                    "subtitle": "",
                    "columns": [
                        {"key": "pathogen", "label": "病原体"},
                        {"key": "region_id", "label": "区域 ID"},
                        {"key": "forward_primer", "label": "Forward Primer"},
                        {"key": "reverse_primer", "label": "Reverse Primer"},
                        {"key": "position", "label": "位置"},
                        {"key": "amplicon", "label": "扩增子"},
                    ],
                    "rows": [
                        {
                            "pathogen": "Mycobacterium tuberculosis",
                            "region_id": "MTB_region_01",
                            "forward_primer": "AGTGACCGTTCGATGATGAC",
                            "reverse_primer": "CTTGATCGGCTTCTTCAGGT",
                            "position": "1520-1688",
                            "amplicon": "169 bp",
                        },
                        {
                            "pathogen": "Influenza A virus",
                            "region_id": "FLUA_region_02",
                            "forward_primer": "TGGACTAGCGAAAGCAGGTA",
                            "reverse_primer": "CACCTTGTCTTTGCCAGTTC",
                            "position": "845-1016",
                            "amplicon": "172 bp",
                        },
                        {
                            "pathogen": "Rubella virus",
                            "region_id": "RUB_region_01",
                            "forward_primer": "GGATGGTGATGACACCAAGA",
                            "reverse_primer": "TTCCACCTTGAGGTTGTTGA",
                            "position": "221-373",
                            "amplicon": "153 bp",
                        },
                    ],
                },
                "artifacts": [
                    {"name": "primer_result_final_2.txt", "remote_path": "", "local_path": "", "available": False},
                    {"name": "primer_result_final.txt", "remote_path": "", "local_path": "", "available": False},
                    {"name": "dimer_score.txt", "remote_path": "", "local_path": "", "available": False},
                    {"name": "运行日志 / 原始结果包", "remote_path": "", "local_path": "", "available": False},
                ],
                "charts": [],
                "provenance": {
                    "parameters": [
                        {"label": "输入", "value": "病原体基因组 FASTA"},
                        {"label": "靶点筛选", "value": "保守性 + 特异性"},
                        {"label": "输出", "value": "每病原体首选引物对"},
                    ],
                },
            },
            "targeted_sequencing": {
                "tool_ids": ["centrifuge", "kraken2"],
                "title": "靶向测序分析 (tNGS)",
                "description": "上传纳米孔靶向扩增测序 FASTQ，Centrifuge + HPVC 数据库快速鉴定病原体组成。",
                "status": {
                    "state": "ready",
                    "label": "等待运行",
                    "detail": "使用 HPVC 病原体数据库，上传 FASTQ 文件后自动启动分析。",
                },
                "summary": [
                    {"label": "总 Reads", "value": "—", "tone": "primary"},
                    {"label": "已分类", "value": "—", "tone": "info"},
                    {"label": "物种数", "value": "—", "tone": "success"},
                    {"label": "Top 物种", "value": "—", "tone": "accent"},
                ],
                "table": {
                    "title": "病原体物种组成",
                    "subtitle": "运行 Centrifuge 分析后，物种组成表将在此呈现。",
                    "columns": [
                        {"key": "rank", "label": "序号"},
                        {"key": "name", "label": "病原体名称"},
                        {"key": "reads", "label": "Reads 数"},
                        {"key": "percentage", "label": "占比 (%)"},
                    ],
                    "rows": [],
                },
                "artifacts": [],
                "charts": [],
                "provenance": {
                    "parameters": [
                        {"label": "输入", "value": "纳米孔靶向 FASTQ"},
                        {"label": "分类引擎", "value": "Centrifuge + HPVC"},
                        {"label": "输出", "value": "物种表 + 图表 + 检测报告"},
                    ],
                },
            },
        },
    }
