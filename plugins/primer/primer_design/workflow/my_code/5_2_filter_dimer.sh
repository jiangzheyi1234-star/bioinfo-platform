#!/bin/bash

# 获取脚本所在目录的父目录（即项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 根据dimer_filtered.txt过滤primer_result_dimer.txt
# 去除涉及二聚体问题的引物对，生成primer_result_final.txt

cd "$PROJECT_DIR"

if [ ! -f my_result/primer_result_dimer.txt ]; then
    echo "错误: 未找到文件 my_result/primer_result_dimer.txt"
    exit 1
fi

if [ ! -f my_result/dimer_filtered.txt ]; then
    echo "错误: 未找到文件 my_result/dimer_filtered.txt"
    echo "请先运行 5_dimer.sh 生成二聚体分析结果"
    exit 1
fi

# 检查dimer_filtered.txt是否为空（没有需要删除的引物）
if [ ! -s my_result/dimer_filtered.txt ] || grep -q "未发现需要删除的引物对" my_result/dimer_filtered.txt; then
    echo "未发现需要删除的引物对，直接复制 primer_result_dimer.txt 为 primer_result_final.txt"
    cp my_result/primer_result_dimer.txt my_result/primer_result_final.txt
    echo "完成：primer_result_final.txt 已生成（与 primer_result_dimer.txt 相同）"
    exit 0
fi

# 从dimer_filtered.txt中提取需要删除的引物对ID
# dimer_filtered.txt格式：Dimer X: 引物ID1 x 引物ID2    score    delta_g
# 引物ID格式：病原体名--区间ID_F 或 病原体名--区间ID_R
# 需要提取：病原体名--区间ID（去掉_F或_R后缀）

awk -F '\t' '
{
    if (NF >= 1) {
        # 第1列：Dimer信息，格式：Dimer X: 引物ID1 x 引物ID2
        dimer_line = $1;
        
        # 提取引物ID（使用更兼容的方法）
        # 查找 "Dimer X: " 之后和 " x " 之前的内容
        if (match(dimer_line, /Dimer [0-9]+: /)) {
            # 获取 "Dimer X: " 之后的内容
            after_dimer = substr(dimer_line, RSTART + RLENGTH);
            # 查找 " x " 的位置
            x_pos = index(after_dimer, " x ");
            if (x_pos > 0) {
                primer1 = substr(after_dimer, 1, x_pos - 1);
                primer2 = substr(after_dimer, x_pos + 3);
                # 去掉引物2中可能存在的制表符和后续内容
                tab_pos = index(primer2, "\t");
                if (tab_pos > 0) {
                    primer2 = substr(primer2, 1, tab_pos - 1);
                }
                
                # 去掉前后空格
                gsub(/^[ \t]+|[ \t]+$/, "", primer1);
                gsub(/^[ \t]+|[ \t]+$/, "", primer2);
                
                # 去掉_F或_R后缀，得到引物对ID（格式：病原体名--区间ID）
                gsub(/_[FR]$/, "", primer1);
                gsub(/_[FR]$/, "", primer2);
                
                # 记录需要删除的引物对ID
                if (primer1 != "") to_delete[primer1] = 1;
                if (primer2 != "") to_delete[primer2] = 1;
            }
        }
    }
}
END {
    # 输出需要删除的引物对ID
    for (id in to_delete) {
        print id;
    }
}' my_result/dimer_filtered.txt > tmp_to_delete_ids.txt

# 统计需要删除的引物对数量
delete_count=$(wc -l < tmp_to_delete_ids.txt)
echo "发现 $delete_count 个需要删除的引物对ID"

# 从primer_result_dimer.txt中过滤掉这些引物对
awk -F '\t' '
BEGIN {
    # 读取需要删除的ID列表
    while ((getline line < "tmp_to_delete_ids.txt") > 0) {
        gsub(/^[ \t]+|[ \t]+$/, "", line);
        to_delete[line] = 1;
    }
    close("tmp_to_delete_ids.txt");
}
{
    if (NF >= 2) {
        # 构建引物对ID：病原体名--区间ID
        primer_id = $1 "--" $2;
        
        # 检查是否需要删除
        if (!(primer_id in to_delete)) {
            print $0;
        } else {
            deleted++;
        }
    }
}
END {
    if (deleted > 0) {
        print "已删除 " deleted " 对引物" > "/dev/stderr";
    }
}' my_result/primer_result_dimer.txt > my_result/primer_result_final.txt

# 清理临时文件
rm -f tmp_to_delete_ids.txt

# 统计结果
original_count=$(wc -l < my_result/primer_result_dimer.txt)
final_count=$(wc -l < my_result/primer_result_final.txt)
removed_count=$((original_count - final_count))

echo ""
echo "过滤完成："
echo "  原始引物对数: $original_count"
echo "  删除引物对数: $removed_count"
echo "  最终引物对数: $final_count"
echo ""
echo "结果已保存到 my_result/primer_result_final.txt"
