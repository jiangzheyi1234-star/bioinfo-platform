#!/bin/bash
# ============================================================================
# 脚本名称: 3_select.sh
# 功能描述: 从BLAST比对结果中筛选保守且特异的序列区域，用于引物设计
# 工作流程:
#   1. 筛选完全匹配的比对结果（相似度100%，长度≥500bp）
#   2. 识别非特异性比对（比对到其他物种的片段）
#   3. 计算特异性区间（完全匹配区间 - 非特异性区间）
#   4. 统计每个特异性区间的比对数量（保守性指标）
#   5. 选择每个病原体最保守的6个特异性区域
#   6. 提取对应的序列用于引物设计
# 依赖工具: seqkit (需要激活conda环境PCR)
# ============================================================================

# 检查seqkit是否可用
if ! command -v seqkit &> /dev/null; then
    echo "错误: seqkit命令未找到"
    echo "请先激活conda环境: conda activate PCR"
    exit 1
fi

# ============================================================================
# 步骤1: 筛选完全匹配的比对结果
# 目的: 只保留相似度100%且长度≥500bp的高质量比对结果
# 条件: $3>=100 (相似度百分比) 且 $4>=500 (比对长度)
# 输出: blast_filt/ 目录，包含每个病原体的高质量比对结果
# ============================================================================
echo "步骤1: 筛选完全匹配的比对结果..."
mkdir -p blast_filt
for i in $(cat name.txt); do 
  # 查找对应的blast文件（可能带编号前缀，格式：数字_${i}.txt）
  blast_file=$(ls ./blast/*_${i}.txt 2>/dev/null | head -1)
  if [ -z "$blast_file" ]; then
    # 如果找不到带前缀的文件，尝试直接查找
    blast_file="./blast/${i}.txt"
    if [ ! -f "$blast_file" ]; then
      echo "警告: 未找到文件 ./blast/*_${i}.txt 或 ./blast/${i}.txt"
      continue
    fi
  fi
  awk '($3>=100 && $4>=500){print $0}' "$blast_file" > ./blast_filt/${i}.txt
done

# ============================================================================
# 步骤2: 标准化序列标题格式
# 目的: 将第13列（stitle，序列标题）中的空格替换为下划线，便于后续文本匹配
# 原因: 序列标题中的空格会影响grep等文本匹配操作
# 输出: 更新后的blast_filt/文件（空格→下划线）
# ============================================================================
echo "步骤2: 标准化序列标题格式（空格→下划线）..."
for f in ./blast_filt/*.txt; do
  awk -F'\t' 'BEGIN{OFS="\t"} {
    gsub(/ /, "_", $13);  # 将第13列（序列标题）中的空格替换为下划线
    print $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
  }' "$f" > tmp && mv tmp "$f"
done

# ============================================================================
# 步骤3: 识别非特异性比对
# 目的: 找出比对到其他物种的片段（非特异性片段）
# 方法: 从文件名提取关键词，筛选序列标题中不包含这些关键词的比对结果
#       这些比对结果可能比对到了其他物种，属于非特异性片段
# 注意: 由于name.txt中已去除编号，直接使用文件名作为关键词
# 输出: blast_nonspecifity/ 目录，包含每个病原体的非特异性比对结果
# ============================================================================
echo "步骤3: 识别非特异性比对（比对到其他物种的片段）..."
mkdir -p blast_nonspecifity

while read i; do
  # 提取文件名中的关键词用于匹配（由于name.txt已去除编号，直接使用文件名）
  # 例如: "Severe_acute_respiratory_syndrome_coronavirus_2" 
  # 提取前两个关键词: "Severe" 和 "acute"
  keys=($(echo "$i" | cut -d'_' -f1,2 | tr '_' ' '))
  
  file="./blast_filt/${i}.txt"
  out="./blast_nonspecifity/${i}.txt"

  # 筛选序列标题中既不包含第一个关键词也不包含第二个关键词的行
  # -i: 不区分大小写
  # -v: 取反，排除匹配的行
  # 这些行可能比对到了其他物种，属于非特异性片段
  if [ ${#keys[@]} -ge 2 ]; then
    grep -i -v "${keys[0]}" "$file" | grep -i -v "${keys[1]}" > "$out"
  else
    # 如果只有一个关键词，只使用第一个
    grep -i -v "${keys[0]}" "$file" > "$out"
  fi

done < name.txt

# ============================================================================
# 步骤4: 提取区间ID
# 目的: 从比对结果中提取唯一的序列区间ID（查询序列ID，即$1字段）
# 说明: BLAST输出格式6包含13个字段，$1是查询序列ID（qseqid）
#       例如: "NC_045512.2_sliding:1-500" 表示原序列的第1-500bp片段
# 输出: 
#   - blast_nonspecifity/${i}_non_id.txt: 非特异性区间ID列表
#   - blast_nonspecifity/${i}_id.txt: 所有高质量比对区间ID列表
# ============================================================================
echo "步骤4: 提取区间ID..."
for i in $(cat name.txt); do
  # 检查文件是否存在
  if [ ! -f ./blast_nonspecifity/${i}.txt ]; then
    echo "警告: 文件 ./blast_nonspecifity/${i}.txt 不存在，跳过"
    continue
  fi
  if [ ! -f ./blast_filt/${i}.txt ]; then
    echo "警告: 文件 ./blast_filt/${i}.txt 不存在，跳过"
    continue
  fi
  
  # 提取非特异性区间ID（比对到其他物种的区间）
  awk '{print $1}' ./blast_nonspecifity/${i}.txt | sort | uniq > ./blast_nonspecifity/${i}_non_id.txt
  
  # 提取所有高质量比对区间ID（完全匹配的区间）
  awk '{print $1}' ./blast_filt/${i}.txt | sort | uniq > ./blast_nonspecifity/${i}_id.txt
done

# ============================================================================
# 步骤5: 计算特异性区间
# 目的: 通过集合差集运算，找出只比对到目标病原体的特异性区间
# 方法: 所有高质量比对区间 - 非特异性区间 = 特异性区间
# 说明: 特异性区间是指只比对到目标病原体，不比对到其他物种的区间
#       这些区间适合用于设计特异性引物
# 输出: blast_nonspecifity/${i}_id_final.txt: 每个病原体的特异性区间ID列表
# ============================================================================
echo "步骤5: 计算特异性区间（完全匹配区间 - 非特异性区间）..."
for i in $(cat name.txt); do
  # 使用grep找出在_id.txt中但不在_non_id.txt中的区间ID
  # -F: 固定字符串匹配
  # -v: 排除匹配的行
  # -x: 整行匹配
  # -f: 从文件读取模式
  grep -Fvxf ./blast_nonspecifity/${i}_non_id.txt ./blast_nonspecifity/${i}_id.txt > ./blast_nonspecifity/${i}_id_final.txt
done

# ============================================================================
# 步骤6: 统计特异性区间的保守性
# 目的: 统计每个特异性区间在数据库中的比对数量，作为保守性指标
# 说明: 比对数量越多，说明该区间在数据库中越常见，越保守
#       保守的区间更适合用于引物设计，因为引物更容易成功扩增
# 输出: number/${i}_count_result.txt: 每个病原体的区间ID及其比对数量
# ============================================================================
echo "步骤6: 统计特异性区间的保守性（比对数量）..."
mkdir -p ./number

for i in $(cat name.txt); do
  # 检查文件是否存在
  if [ ! -f ./blast_nonspecifity/${i}_id_final.txt ]; then
    echo "警告: 文件 ./blast_nonspecifity/${i}_id_final.txt 不存在，跳过"
    continue
  fi
  if [ ! -f ./blast_filt/${i}.txt ]; then
    echo "警告: 文件 ./blast_filt/${i}.txt 不存在，跳过"
    continue
  fi
  
  > ./number/${i}_count_result.txt  # 清空文件
  
  while read region; do
    # 统计该区间在高质量比对结果中出现的次数
    # 出现次数越多，说明该区间越保守
    count=$(grep -c "^$region" ./blast_filt/${i}.txt)
    echo -e "$region\t$count"
  done < ./blast_nonspecifity/${i}_id_final.txt > ./number/${i}_count_result.txt
done

# ============================================================================
# 步骤7: 选择最保守的特异性区域
# 目的: 对每个病原体，选择比对数量最多的6个特异性区域
# 方法: 按比对数量降序排序，取前6个
# 说明: 这些区域既具有特异性（只比对到目标病原体），又具有保守性（比对数量多）
#       是引物设计的最佳候选区域
# 输出: number/${i}_top6_regions.txt: 每个病原体的前6个保守特异性区域ID
# ============================================================================
echo "步骤7: 选择每个病原体最保守的6个特异性区域..."
for i in $(cat name.txt); do
  # 检查文件是否存在
  if [ ! -f ./number/${i}_count_result.txt ]; then
    echo "警告: 文件 ./number/${i}_count_result.txt 不存在，跳过"
    continue
  fi
  
  # 按比对数量（第2列）降序排序
  sort -k2,2nr ./number/${i}_count_result.txt > ./number/${i}_count_result_sorted.txt
  
  # 提取前6名区域的ID（第1列），如果少于6个则全部提取
  total=$(wc -l < ./number/${i}_count_result_sorted.txt)
  if [ "$total" -gt 0 ]; then
    head -n 6 ./number/${i}_count_result_sorted.txt | cut -f1 > ./number/${i}_top6_regions.txt
    extracted=$(wc -l < ./number/${i}_top6_regions.txt)
    echo "  ${i}: 提取了 ${extracted} 个保守特异性区域（共 ${total} 个）"
  else
    echo "警告: ${i} 没有特异性区间"
    > ./number/${i}_top6_regions.txt  # 创建空文件
  fi
done

# ============================================================================
# 步骤8: 提取保守特异性序列
# 目的: 从切割后的序列文件中提取选定的6个保守特异性区域的序列
# 说明: 这些序列将用于后续的引物设计
# 输出: conserved_seq/${i}.fasta: 每个病原体的6个保守特异性序列
# ============================================================================
echo "步骤8: 提取保守特异性序列..."
mkdir -p conserved_seq

for i in $(cat name.txt); do
  # 查找对应的splits文件（可能带编号前缀，格式：数字_${i}.fasta）
  splits_file=$(ls ./splits/*_${i}.fasta 2>/dev/null | head -1)
  if [ -z "$splits_file" ]; then
    # 如果找不到带前缀的文件，尝试直接查找
    splits_file="./splits/${i}.fasta"
    if [ ! -f "$splits_file" ]; then
      echo "警告: 未找到文件 ./splits/*_${i}.fasta 或 ./splits/${i}.fasta"
      continue
    fi
  fi
  
  # 检查top6文件是否存在
  if [ ! -f ./number/${i}_top6_regions.txt ]; then
    echo "警告: 文件 ./number/${i}_top6_regions.txt 不存在，跳过"
    continue
  fi
  
  > ./conserved_seq/${i}.fasta  # 清空文件
  
  while read region; do
    # 使用seqkit从切割后的序列文件中提取指定区间的序列
    # -r: 使用正则表达式匹配
    # -p: 模式匹配（匹配序列ID）
    seqkit grep -r -p "^${region}$" "$splits_file" >> ./conserved_seq/${i}.fasta
  done < ./number/${i}_top6_regions.txt
done

echo "完成！保守特异性序列已保存到 conserved_seq/ 目录"