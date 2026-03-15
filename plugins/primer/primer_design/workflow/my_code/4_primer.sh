#!/bin/bash

# 1. 创建引物设计目录
mkdir primer
cd primer

# 2. 安装primer3和seqkit（需要conda环境）
#conda install -y primer3
#conda install -y seqkit

# 3. 修改保守序列格式
mkdir mod_seq
for i in `cat ../name.txt`; do
    sed -e "s/:/_/g" ../conserved_seq/${i}.fasta | sed -e "s/_sliding//g" | seqkit seq -w 0 > ./mod_seq/${i}.fasta
done

# 4. 转化.fasta为primer3输入格式
mkdir primer_mod
for i in `cat ../name.txt`; do
    perl P3IN.pl ./mod_seq/${i}.fasta ./primer_mod/${i}_out.txt
done

# 5. 使用primer3批量设计引物
mkdir primer_data
for i in `cat ../name.txt`; do
    primer3_core -output=./primer_data/${i}.txt -p3_settings_file=peizhi_final.txt -format_output ./primer_mod/${i}_out.txt
done

# 6. 整理引物结果
for i in `cat ../name.txt`; do
    grep -E "PRIMER PICKING|OLIGO|LEFT PRIMER|RIGHT PRIMER|PRODUCT SIZE" ./primer_data/${i}.txt > ./primer_data/${i}_ann.txt
done

# 7. 调整格式
mkdir primer_change
for i in `cat ../name.txt`; do
    grep -v "PRODUCT SIZE" ./primer_data/${i}_ann.txt | grep -v "ADDITIONAL OLIGOS" | sed -e "s/ PRIMER/_PRIMER/g" | sed -e 's/\s\+/ /g' | sed -e 's/ /\t/g' | sed -e "s/^\t[1-9]\t//" | sed -e "s/^\t//g" > ./primer_data/${i}_out.txt
done

# 8. 表格整理
mkdir primer_change
for i in `cat ../name.txt`; do
    grep 'LEFT_PRIMER' ./primer_data/${i}_out.txt > ./primer_change/${i}_F.txt
    grep 'RIGHT_PRIMER' ./primer_data/${i}_out.txt > ./primer_change/${i}_R.txt
    paste ./primer_change/${i}_F.txt ./primer_change/${i}_R.txt > ./primer_change/${i}_primer.txt
done

# 9. 提取序列和ID
mkdir name_change
for i in `cat ../name.txt`; do
    awk '{if($0~/^PRIMER/) {seq_name=$5;count=1;} else if($0~/LEFT_PRIMER/) forward=$9; else if ($0~/RIGHT_PRIMER/) {reverse=$9; printf("%s@%d\t%s\t%s\n", seq_name,count,forward, reverse); count+=1;} }' ./primer_data/${i}_out.txt | awk '{print $1}' > ./name_change/${i}.txt
    awk '{print $1}' ./name_change/${i}.txt > ./name_change/${i}_name.txt
done

# 10. 匹配并加上唯一ID号
for i in `cat ../name.txt`; do
    paste ./name_change/${i}_name.txt ./primer_change/${i}_primer.txt > ./name_change/${i}_result.txt
done

# 11. 整理引物输出格式
mkdir primer_result
for i in `cat ../name.txt`; do
    sed -e '1i\id\tOLIGO\tstart\tlen\ttm\tgc\tany_th\t3_th\thairpin\tseq\tOLIGO\tstart\tlen\ttm\tgc\tany_th\t3_th\thairpin\tseq' ./name_change/${i}_result.txt > ./primer_result/${i}_result.txt
done

# 12. 引物结果整理完成
echo "引物结果整理完成：primer_result文件夹中的_result.txt文件"

# 11. 提取每对引物的扩增子序列
# 1) 制作位置文件
mkdir primer_position
for i in `cat ../name.txt`; do
    awk '{print $1"\t"$3-1"\t"$12}' ./primer_result/${i}_result.txt | sed -e "s/@[1-9]//g" | sed -e '1d' > ./primer_position/${i}.txt
done

# 2) 提取序列
mkdir primer_seq
for i in `cat ../name.txt`; do
    seqkit subseq --bed ./primer_position/${i}.txt ./mod_seq/${i}.fasta -o ./primer_seq/${i}.fasta
    seqkit fx2tab ./primer_seq/${i}.fasta | sed -e 's/:\.//g' | sed -e 's/ //g' | sed -e 's/\t$//g' > ./primer_seq/${i}_seq.txt
done

# 3) 整合序列文件，重新命名
mkdir tmp
for i in `cat ../name.txt`; do
    awk '{print $1"_"$2+1"-"$3}' ./primer_position/${i}.txt > ./tmp/${i}_tmp.txt
    awk '{print $1}' ./primer_result/${i}_result.txt | sed -e '1d' > ./tmp/${i}.txt
    paste ./tmp/${i}_tmp.txt ./tmp/${i}.txt > ./tmp/${i}_name.txt
done

mkdir seq_result
for i in `cat ../name.txt`; do
    awk 'NR==FNR{a[$1]=$2;next}{print $0 FS a[$1]}' ./primer_seq/${i}_seq.txt ./tmp/${i}_name.txt | sed -e "s/ /\t/g" | awk -F '\t' '{print $2"\t"$1"\t"$3}' > ./seq_result/${i}_seq_final.txt
done

# 4) 序列结果存放在seq_result文件夹中
mkdir primer_tmp
for i in `cat ../name.txt`; do
    cat ./primer_result/${i}_result.txt | xargs -i echo ${i}--{} > ./primer_tmp/${i}.txt
    sed -e '1d' ./primer_tmp/${i}.txt | awk -F '\t' '{print $1"\t"$10"\t"$19}' > ./primer_tmp/${i}_ePCR_primer.txt
done

# 按照区间ID匹配引物和序列，而不是按照行号
# 先合并所有文件，然后按照区间ID匹配
cat ./seq_result/*_seq_final.txt > all_seq.txt
cat ./primer_tmp/*_ePCR_primer.txt > all_primer.txt

# 按照区间ID匹配：从all_primer.txt中提取区间ID，从all_seq.txt中匹配对应的序列
awk -F '\t' '
BEGIN {
    # 读取all_seq.txt，建立区间ID到序列的映射
    while ((getline line < "all_seq.txt") > 0) {
        n = split(line, fields, "\t");
        if (n >= 3) {
            region_id = fields[1];  # 区间ID
            position = fields[2];    # 位置
            sequence = fields[3];    # 序列
            # 存储：region_id -> position + "\t" + sequence
            seq_map[region_id] = position "\t" sequence;
        }
    }
    close("all_seq.txt");
}
{
    # 处理all_primer.txt的每一行
    if (NF >= 3) {
        primer_id = $1;  # 格式：病原体名--区间ID
        forward_seq = $2;  # 前引物序列
        reverse_seq = $3;  # 后引物序列
        
        # 提取区间ID：从 "病原体名--区间ID" 中提取 "区间ID"
        # 查找 "--" 的位置
        dash_pos = index(primer_id, "--");
        if (dash_pos > 0) {
            region_id = substr(primer_id, dash_pos + 2);  # 提取 "--" 之后的部分
            # 查找对应的序列
            if (region_id in seq_map) {
                # 输出：病原体名--区间ID + 前引物 + 后引物 + 位置 + 序列
                print primer_id "\t" forward_seq "\t" reverse_seq "\t" seq_map[region_id];
            } else {
                # 如果找不到匹配的序列，输出原始行（可能有问题）
                print primer_id "\t" forward_seq "\t" reverse_seq "\t\t";
            }
        }
    }
}' all_primer.txt > primer_result.txt

sed -i 's/\--/\t/g' primer_result.txt

echo "所有引物和扩增后的序列整合在 primer_result.txt 中"

# 13. 将最终结果复制到my_result文件夹
mkdir -p ../my_result
cp primer_result.txt ../my_result/primer_result.txt
echo "最终结果已复制到 my_result/primer_result.txt"
