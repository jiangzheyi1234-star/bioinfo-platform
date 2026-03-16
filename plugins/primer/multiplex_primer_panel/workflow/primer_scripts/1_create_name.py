#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将ref_genome目录下的基因组序列文件空格替换为下划线，后缀改为.fasta
并将文件名（不含后缀）依次记录到name.txt文件中
"""

import os
from pathlib import Path

# 获取项目根目录
project_root = Path(__file__).parent.parent
ref_genome_dir = project_root / "ref_genome"
name_txt_file = project_root / "name.txt"

# 检查ref_genome目录是否存在
if not ref_genome_dir.exists():
    print(f"错误: {ref_genome_dir} 目录不存在")
    exit(1)

# 获取所有文件并按文件名开头的数字排序
def get_sort_key(file_path):
    """提取文件名开头的数字用于排序"""
    name = file_path.name
    # 提取文件名开头的数字
    try:
        num_str = name.split('_')[0]
        return int(num_str)
    except (ValueError, IndexError):
        return 0

# 先查找.fna文件，如果没有则查找.fasta文件（避免重复处理）
files = sorted(ref_genome_dir.glob("*.fna"), key=get_sort_key)
if not files:
    files = sorted(ref_genome_dir.glob("*.fasta"), key=get_sort_key)

if not files:
    print(f"警告: {ref_genome_dir} 目录下没有找到 .fna 或 .fasta 文件")
    exit(1)

# 处理文件名：将空格替换为下划线，将.fna改为.fasta，并重命名文件
processed_names = []
for file in files:
    # 获取文件名（不含路径）
    original_name = file.name
    # 将空格替换为下划线
    new_name = original_name.replace(" ", "_")
    # 将.fna后缀改为.fasta
    if new_name.endswith('.fna'):
        new_name = new_name[:-4] + '.fasta'
    
    # 如果文件名已经改变，则重命名文件
    if new_name != original_name:
        new_path = file.parent / new_name
        file.rename(new_path)
        print(f"重命名: {original_name} -> {new_name}")
    
    # 提取文件名（不含后缀）用于写入name.txt
    name_without_ext = new_name.rsplit('.', 1)[0]  # 移除最后一个.及其后的内容
    
    # 去除文件名开头的编号（格式：数字_其他内容 -> 其他内容）
    # 例如：8_Severe_acute_respiratory_syndrome_coronavirus_2 -> Severe_acute_respiratory_syndrome_coronavirus_2
    if '_' in name_without_ext:
        parts = name_without_ext.split('_', 1)  # 只分割第一个下划线
        # 检查第一部分是否为数字
        if parts[0].isdigit():
            name_without_ext = parts[1]  # 去除数字和下划线，保留后面的部分
    
    processed_names.append(name_without_ext)

# 将处理后的文件名（不含后缀）写入name.txt文件
with open(name_txt_file, 'w', encoding='utf-8') as f:
    for name in processed_names:
        f.write(name + '\n')

print(f"\n成功处理 {len(processed_names)} 个文件")
print(f"文件名已记录到: {name_txt_file}")
print("\nname.txt中的文件名列表（不含后缀）:")
for name in processed_names:
    print(f"  {name}")

