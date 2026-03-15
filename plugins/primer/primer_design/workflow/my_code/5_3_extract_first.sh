#!/bin/bash

# 获取脚本所在目录的父目录（即项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 从primer_result_final.txt中提取每种病原体的第一个引物对
# 输出到primer_result_final_2.txt

cd "$PROJECT_DIR"

if [ ! -f my_result/primer_result_final.txt ]; then
    echo "错误: 未找到文件 my_result/primer_result_final.txt"
    exit 1
fi

# 使用awk提取每种病原体的第一个引物对
awk -F '\t' '
{
    if (NF >= 4) {
        # 第1列：病原体名称
        pathogen = $1;
        
        # 如果该病原体还没有记录，则记录第一行
        if (!(pathogen in seen)) {
            seen[pathogen] = 1;
            # 保存完整行数据
            first_primer[pathogen] = $0;
            # 记录顺序
            order[++count] = pathogen;
        }
    }
}
END {
    # 按出现顺序输出（或者可以按病原体名称排序）
    for (i = 1; i <= count; i++) {
        pathogen = order[i];
        print first_primer[pathogen];
    }
}' my_result/primer_result_final.txt > my_result/primer_result_final_2.txt

# 统计结果
total_lines=$(wc -l < my_result/primer_result_final_2.txt)
echo "已提取 $total_lines 对引物到 primer_result_final_2.txt"

# 显示提取的病原体和引物对信息
echo ""
echo "提取的引物对信息："
awk -F '\t' '{print "  " $1 ": " $2}' my_result/primer_result_final_2.txt

echo ""
echo "结果已保存到 my_result/primer_result_final_2.txt"
