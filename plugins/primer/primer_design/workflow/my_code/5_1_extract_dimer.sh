#!/bin/bash

# 获取脚本所在目录的父目录（即项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 从primer_result.txt中提取每个病原体的前三个区间，每个区间提取前三对引物对
# 生成primer_result_dimer.txt

cd "$PROJECT_DIR"

if [ ! -f my_result/primer_result.txt ]; then
    echo "错误: 未找到文件 my_result/primer_result.txt"
    exit 1
fi

# 使用Python脚本进行提取（更可靠）
python3 << 'PYTHON_SCRIPT'
import sys
from collections import defaultdict

# 读取primer_result.txt
input_file = 'my_result/primer_result.txt'
output_file = 'my_result/primer_result_dimer.txt'

# 存储结构：{病原体: {区间名: [(引物编号, 完整行)]}}
data = defaultdict(lambda: defaultdict(list))

with open(input_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 4:
            continue
        
        pathogen = parts[0]
        region_id = parts[1]  # 格式：NC_002022.1_1501-2000@1
        
        # 提取区间名和引物编号
        if '@' in region_id:
            region_name, primer_num_str = region_id.rsplit('@', 1)
            try:
                primer_num = int(primer_num_str)
            except:
                continue
        else:
            continue
        
        # 只保留每个区间的前3对引物
        region_data = data[pathogen][region_name]
        if len(region_data) < 3:
            # 检查是否已存在相同编号的引物
            if not any(x[0] == primer_num for x in region_data):
                region_data.append((primer_num, line))
                # 按引物编号排序
                region_data.sort(key=lambda x: x[0])

# 输出结果：每个病原体的前3个区间，每个区间的前3对引物
output_lines = []
for pathogen in sorted(data.keys()):
    regions = sorted(data[pathogen].keys())[:3]  # 每个病原体取前3个区间
    for region_name in regions:
        primers = sorted(data[pathogen][region_name], key=lambda x: x[0])[:3]  # 每个区间取前3对
        for primer_num, line in primers:
            output_lines.append(line)

# 写入输出文件
with open(output_file, 'w') as f:
    for line in output_lines:
        f.write(line + '\n')

# 统计信息
print(f"已提取 {len(output_lines)} 对引物到 primer_result_dimer.txt")
print("\n各病原体提取的引物对数量：")
pathogen_counts = defaultdict(int)
for line in output_lines:
    pathogen = line.split('\t')[0]
    pathogen_counts[pathogen] += 1

for pathogen, count in sorted(pathogen_counts.items(), key=lambda x: -x[1]):
    print(f"  {pathogen}: {count} 对")
PYTHON_SCRIPT

if [ $? -eq 0 ]; then
    echo ""
    echo "提取完成：primer_result_dimer.txt 已生成"
else
    echo "错误: Python脚本执行失败"
    exit 1
fi
