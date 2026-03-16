#!/bin/bash

if ! command -v seqkit &> /dev/null; then
    echo "错误: seqkit 命令未找到"
    exit 1
fi

if ! command -v blastn &> /dev/null; then
    echo "错误: blastn 命令未找到"
    exit 1
fi

if [ -z "${BLAST_DB_PATH:-}" ]; then
    echo "错误: BLAST_DB_PATH 未设置"
    exit 1
fi

mkdir -p splits
for i in $(cat name.txt); do
  ref_file=$(ls ./ref_genome/*_${i}.fasta 2>/dev/null | head -1)
  if [ -z "$ref_file" ]; then
    ref_file="./ref_genome/${i}.fasta"
    if [ ! -f "$ref_file" ]; then
      echo "警告: 未找到文件 ./ref_genome/*_${i}.fasta 或 ./ref_genome/${i}.fasta"
      continue
    fi
  fi
  seqkit sliding -s 500 -W 500 "$ref_file" -o ./splits/${i}.fasta
done

total_cores=$(nproc)
half_cores=$((total_cores / 2))
threads=$((half_cores > 0 ? half_cores : 1))
echo "使用 $threads 个线程进行 BLAST 比对"

mkdir -p blast
total_files=$(wc -l < name.txt)
current=0

for i in $(cat name.txt); do
  current=$((current + 1))
  if [ ! -f ./splits/${i}.fasta ]; then
    echo "警告: 文件 ./splits/${i}.fasta 不存在，跳过"
    continue
  fi
  echo "[$current/$total_files] 正在比对: $i"
  blastn \
    -query ./splits/${i}.fasta \
    -db "$BLAST_DB_PATH" \
    -outfmt "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore stitle staxids" \
    -evalue 1e-5 \
    -out ./blast/${i}.txt \
    -num_threads $threads
  echo "[$current/$total_files] 完成: $i"
done

echo "所有 BLAST 比对完成"
