#!/bin/bash

# 获取脚本所在目录的父目录（即项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 引物二聚体分析
# 检查 mfeprimer 是否在 PATH 中
MEPRIMER_CMD=""
if command -v mfeprimer &> /dev/null; then
    MEPRIMER_CMD="mfeprimer"
elif [ -f "$PROJECT_DIR/software/mfeprimer" ]; then
    # 使用项目目录下的 mfeprimer
    MEPRIMER_CMD="$PROJECT_DIR/software/mfeprimer"
    # 确保有执行权限
    chmod +x "$MEPRIMER_CMD" 2>/dev/null
    echo "使用项目目录下的 mfeprimer: $MEPRIMER_CMD"
else
    echo "错误: mfeprimer 未找到"
    echo "请确保 mfeprimer 已安装并在 PATH 中，或位于以下路径："
    echo "  $PROJECT_DIR/software/mfeprimer"
    exit 1
fi

# 进入项目目录
cd "$PROJECT_DIR"

# 检查输入文件
if [ ! -f my_result/primer_result_dimer.txt ]; then
    echo "错误: 未找到输入文件 my_result/primer_result_dimer.txt"
    echo "请先运行提取脚本生成 primer_result_dimer.txt"
    exit 1
fi

# 创建二聚体分析目录
mkdir -p dimer_analysis
cd dimer_analysis

# 1）将引物设计结果整理成名称+序列两列（制表符分隔）
# 从primer_result_dimer.txt中提取引物对
# 格式：病原体名\t区间ID\t正向引物\t反向引物\t...
# 需要提取：病原体名--区间ID作为ID，正向引物和反向引物作为序列

awk -F '\t' '{
    if (NF >= 4) {
        # 第1列：病原体名称
        pathogen = $1;
        # 第2列：区间ID（格式：NC_002022.1_1501-2000@1）
        region_id = $2;
        # 第3列：正向引物序列
        forward_seq = $3;
        # 第4列：反向引物序列
        reverse_seq = $4;
        # 构建引物对ID：病原体名--区间ID
        primer_id = pathogen "--" region_id;
        # 输出正向引物：ID_F 序列
        print primer_id "_F\t" forward_seq;
        # 输出反向引物：ID_R 序列
        print primer_id "_R\t" reverse_seq;
    }
}' ../my_result/primer_result_dimer.txt > yinwu.txt

if [ ! -s yinwu.txt ]; then
    echo "错误: 未能从 primer_result_dimer.txt 中提取引物序列"
    exit 1
fi

echo "已整理引物序列，共 $(wc -l < yinwu.txt) 条引物序列"

# 2）通过seqkit将txt转换成fasta格式
if ! command -v seqkit &> /dev/null; then
    echo "错误: seqkit 未安装，请先安装 seqkit"
    exit 1
fi

seqkit tab2fx yinwu.txt > yinwu.fasta

# 3）引物二聚体分析
if [ ! -f yinwu.fasta ] || [ ! -s yinwu.fasta ]; then
    echo "错误: yinwu.fasta 文件不存在或为空"
    exit 1
fi

$MEPRIMER_CMD dimer -i yinwu.fasta -o dimer.txt

if [ ! -f dimer.txt ]; then
    echo "错误: 二聚体分析失败，未生成 dimer.txt 文件"
    exit 1
fi

# 查看结果
echo "二聚体分析结果："
head -20 dimer.txt
echo "..."

# 4）筛选二聚体打分
grep -E "Dimer|Score" dimer.txt | sed -e '1,2d' > dimer_id.txt

if [ ! -s dimer_id.txt ]; then
    echo "警告: 未找到二聚体信息，可能所有引物对都没有二聚体问题"
    touch dimer_score.txt
    touch dimer_filtered.txt
    echo "未发现二聚体问题" > dimer_score.txt
    echo "未发现需要删除的引物对" > dimer_filtered.txt
else
    grep "Dimer" dimer_id.txt > tmp_1.txt
    grep "Score" dimer_id.txt > tmp_2.txt

    # 5）整理 
    # 第1列是Dimer信息，第2列是score，第3列是Delta G ( kcal/mol)
    # mfeprimer输出格式：Score: X, Tm = 58.57 °C, Delta G = -Y kcal/mol（Delta G为负值）
    # 需要从第2列中提取Score值（去掉空格和逗号后的Tm信息）
    paste tmp_1.txt tmp_2.txt | sed -e '$d' | sed -e 's/Score: //g' | sed -e 's/, Delta G = -/\t/g' | sed 's/ kcal\/mol//g' | \
    awk -F '\t' '{
        if (NF >= 3) {
            # 第1列：Dimer信息
            dimer_info = $1;
            # 第2列：提取Score值（去掉开头的空格，取逗号前的数字）
            score_str = $2;
            gsub(/^[ \t]+/, "", score_str);  # 去掉开头的空格
            gsub(/,.*$/, "", score_str);     # 去掉逗号及后面的内容
            score = score_str + 0;            # 转换为数字
            # 第3列：Delta G（绝对值，单位kcal/mol）
            delta_g = $3 + 0;  # 转换为数字
            # 输出：Dimer信息、Score、Delta G（制表符分隔）
            print dimer_info "\t" score "\t" delta_g;
        }
    }' > dimer_score.txt

    echo "二聚体评分结果已保存到 dimer_score.txt"
    echo "可以将 dimer_score.txt 复制粘贴成 .xlsx 文件分析删除的引物对"

    # 6）筛选二聚体的引物对
    # 筛选规则：引物二聚体及发夹结构的能值过高（超过4.5kcal/mol）易导致产生引物二聚体带
    # 经验：引物二聚体的ΔG不能超过4.5不然容易导致引物二聚体，但是我之前设计引物有的是6.5左右的发现只要不超过8一般单重还是能出的，但是如果是多重的都说不要超过6
    # score>10 或 Delta G绝对值>6 的引物对易产生二聚体，需删除
    # 注意：Delta G在文件中是正值（因为已经去掉了负号），所以直接比较即可

    # 筛选出需要删除的引物对（score>10 或 Delta G>6）
    awk -F '\t' '{
        if (NF >= 3) {
            # 第1列是Dimer信息（引物对名称）
            dimer_info = $1;
            # 第2列是score
            score = $2 + 0;  # 转换为数字
            # 第3列是Delta G（绝对值，单位kcal/mol）
            delta_g = $3 + 0;  # 转换为数字
            # 筛选条件：score>10 或 Delta G>6
            if (score > 10 || delta_g > 6) {
                print $0;
            }
        }
    }' dimer_score.txt > dimer_filtered.txt

    echo ""
    echo "需要删除的引物对（score>10 或 Delta G>6）："
    if [ -s dimer_filtered.txt ]; then
        head -20 dimer_filtered.txt
        echo "..."
    else
        echo "未发现需要删除的引物对"
    fi

    # 统计需要删除的引物对数量
    bad_count=$(wc -l < dimer_filtered.txt)
    total_count=$(wc -l < dimer_score.txt)
    echo ""
    echo "统计信息："
    echo "总引物对数: $total_count"
    echo "需要删除的引物对数: $bad_count"
fi

# 将结果复制到my_result文件夹
mkdir -p ../my_result
cp dimer_score.txt ../my_result/dimer_score.txt
cp dimer_filtered.txt ../my_result/dimer_filtered.txt
echo ""
echo "结果已保存到 my_result 目录："
echo "  - dimer_score.txt: 所有引物对的二聚体评分"
echo "  - dimer_filtered.txt: 需要删除的引物对（score>10 或 Delta G>6）"
