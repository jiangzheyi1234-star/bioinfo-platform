#!/bin/bash

# 检查必需的工具是否可用
if ! command -v seqkit &> /dev/null; then
    echo "错误: seqkit 命令未找到"
    echo "请先安装 seqkit: conda install -c bioconda seqkit"
    echo "或确保已激活正确的 conda 环境: conda activate PCR"
    exit 1
fi

if ! command -v blastn &> /dev/null; then
    echo "错误: blastn 命令未找到"
    echo "请先安装 BLAST+: conda install -c bioconda blast"
    echo "或确保已激活正确的 conda 环境: conda activate PCR"
    exit 1
fi

# 5.将基因组文件切割成500bp区间
mkdir -p splits
for i in `cat name.txt`; do
  # 查找对应的ref_genome文件（可能带编号前缀，格式：数字_${i}.fasta）
  ref_file=$(ls ./ref_genome/*_${i}.fasta 2>/dev/null | head -1)
  if [ -z "$ref_file" ]; then
    # 如果找不到带前缀的文件，尝试直接查找
    ref_file="./ref_genome/${i}.fasta"
    if [ ! -f "$ref_file" ]; then
      echo "警告: 未找到文件 ./ref_genome/*_${i}.fasta 或 ./ref_genome/${i}.fasta"
      continue
    fi
  fi
  seqkit sliding -s 500 -W 500 "$ref_file" -o ./splits/${i}.fasta
done

# 6.将切割后的基因组比对到数据库
# 比对且输出注释
# 注意：使用一半核心数以避免内存溢出（特别是处理多个文件时）
# 计算线程数：至少1个，最多为总核心数的一半
total_cores=$(nproc)
half_cores=$((total_cores / 2))
threads=$((half_cores > 0 ? half_cores : 1))
echo "使用 $threads 个线程进行 BLAST 比对（总核心数: $total_cores）"

mkdir -p blast
total_files=$(wc -l < name.txt)
current=0

for i in `cat name.txt`;
do 
  current=$((current + 1))
  if [ ! -f ./splits/${i}.fasta ]; then
    echo "警告: 文件 ./splits/${i}.fasta 不存在，跳过"
    continue
  fi
  echo "[$current/$total_files] 正在比对: $i"
  blastn -query ./splits/${i}.fasta -db /home/zyserver/project_ssd/common_data/core_nt_database/core_nt  -outfmt "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore stitle" -evalue 1e-5 -out ./blast/${i}.txt -num_threads $threads
  echo "[$current/$total_files] 完成: $i"
done
echo "所有 BLAST 比对完成"