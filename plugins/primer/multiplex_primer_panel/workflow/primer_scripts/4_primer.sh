#!/bin/bash
# ──────────────────────────────────────────────────────────────
# 4_primer.sh — Primer3 设计 + 三级约束松弛
#
#   Tier 1  peizhi_final.txt     严格参数（Tm 50-62, GC 40-68, 180-220bp）
#   Tier 2  peizhi_relaxed.txt   中等松弛（Tm 47-65, GC 30-75, 150-280bp）
#   Tier 3  peizhi_rescue.txt    最大松弛 + PRIMER_PICK_ANYWAY=1
#
# 参考：Primer3 manual — "set PRIMER_PICK_ANYWAY=1 to obtain primers
#       even if they violate specific constraints"
#       primer3-py-plus gradient relaxation pattern
# ──────────────────────────────────────────────────────────────

mkdir -p primer
cd primer

# ---------- 1. 格式化保守序列 ----------
mkdir -p mod_seq
for i in $(cat ../name.txt); do
    sed -e "s/:/_/g" ../conserved_seq/${i}.fasta | sed -e "s/_sliding//g" | seqkit seq -w 0 > ./mod_seq/${i}.fasta
done

# ---------- 2. 生成 Primer3 输入 ----------
mkdir -p primer_mod
for i in $(cat ../name.txt); do
    perl P3IN.pl ./mod_seq/${i}.fasta ./primer_mod/${i}_out.txt
done

# ---------- 3. 三级 Primer3 设计 ----------
# 配置文件路径（peizhi_final.txt 与脚本同目录）
SETTINGS_DIR="$(dirname "$0")/../primer"
TIER1="${SETTINGS_DIR}/peizhi_final.txt"
TIER2="${SETTINGS_DIR}/peizhi_relaxed.txt"
TIER3="${SETTINGS_DIR}/peizhi_rescue.txt"
# 兼容：如果在 primer/ 子目录执行（cd primer 之后）
[ ! -f "$TIER1" ] && TIER1="peizhi_final.txt"
[ ! -f "$TIER2" ] && TIER2="peizhi_relaxed.txt"
[ ! -f "$TIER3" ] && TIER3="peizhi_rescue.txt"

mkdir -p primer_data
mkdir -p ../primer_tier_log

has_primers() {
    # 检查 primer3 -format_output 结果是否包含有效引物
    # 如果有 LEFT_PRIMER 行就说明出了引物
    local f="$1"
    [ -f "$f" ] && grep -q "LEFT PRIMER" "$f"
}

for i in $(cat ../name.txt); do
    INPUT="./primer_mod/${i}_out.txt"
    OUTPUT="./primer_data/${i}.txt"
    TIER_USED=1

    # Tier 1: 严格参数
    primer3_core -output="$OUTPUT" -p3_settings_file="$TIER1" -format_output "$INPUT"

    if ! has_primers "$OUTPUT"; then
        # Tier 2: 中等松弛
        TIER_USED=2
        echo "  [TIER 2] ${i}: Tier 1 returned 0 primers, relaxing constraints..."
        primer3_core -output="$OUTPUT" -p3_settings_file="$TIER2" -format_output "$INPUT"
    fi

    if ! has_primers "$OUTPUT"; then
        # Tier 3: 最大松弛 + PRIMER_PICK_ANYWAY
        TIER_USED=3
        echo "  [TIER 3] ${i}: Tier 2 returned 0 primers, using rescue mode (PICK_ANYWAY)..."
        primer3_core -output="$OUTPUT" -p3_settings_file="$TIER3" -format_output "$INPUT"
    fi

    if ! has_primers "$OUTPUT"; then
        echo "  [WARNING] ${i}: all 3 tiers failed — no primers possible for this pathogen"
        TIER_USED=0
    fi

    # 记录每个病原体使用的 tier 级别
    echo -e "${i}\t${TIER_USED}" >> ../primer_tier_log/tier_used.tsv
done

echo "Primer3 design completed (3-tier progressive relaxation)"

# ---------- 4. 后续解析（与原脚本一致） ----------
for i in $(cat ../name.txt); do
    grep -E "PRIMER PICKING|OLIGO|LEFT PRIMER|RIGHT PRIMER|PRODUCT SIZE" ./primer_data/${i}.txt > ./primer_data/${i}_ann.txt
done

mkdir -p primer_change
for i in $(cat ../name.txt); do
    grep -v "PRODUCT SIZE" ./primer_data/${i}_ann.txt | grep -v "ADDITIONAL OLIGOS" | sed -e "s/ PRIMER/_PRIMER/g" | sed -e 's/\s\+/ /g' | sed -e 's/ /\t/g' | sed -e "s/^\t[1-9]\t//" | sed -e "s/^\t//g" > ./primer_data/${i}_out.txt
done

for i in $(cat ../name.txt); do
    grep 'LEFT_PRIMER' ./primer_data/${i}_out.txt > ./primer_change/${i}_F.txt
    grep 'RIGHT_PRIMER' ./primer_data/${i}_out.txt > ./primer_change/${i}_R.txt
    paste ./primer_change/${i}_F.txt ./primer_change/${i}_R.txt > ./primer_change/${i}_primer.txt
done

mkdir -p name_change
for i in $(cat ../name.txt); do
    awk '{if($0~/^PRIMER/) {seq_name=$5;count=1;} else if($0~/LEFT_PRIMER/) forward=$9; else if ($0~/RIGHT_PRIMER/) {reverse=$9; printf("%s@%d\t%s\t%s\n", seq_name,count,forward, reverse); count+=1;} }' ./primer_data/${i}_out.txt | awk '{print $1}' > ./name_change/${i}.txt
    awk '{print $1}' ./name_change/${i}.txt > ./name_change/${i}_name.txt
done

for i in $(cat ../name.txt); do
    paste ./name_change/${i}_name.txt ./primer_change/${i}_primer.txt > ./name_change/${i}_result.txt
done

mkdir -p primer_result
for i in $(cat ../name.txt); do
    sed -e '1i\id\tOLIGO\tstart\tlen\ttm\tgc\tany_th\t3_th\thairpin\tseq\tOLIGO\tstart\tlen\ttm\tgc\tany_th\t3_th\thairpin\tseq' ./name_change/${i}_result.txt > ./primer_result/${i}_result.txt
done

echo "primer_result directory prepared"

mkdir -p primer_position
for i in $(cat ../name.txt); do
    awk '{print $1"\t"$3-1"\t"$12}' ./primer_result/${i}_result.txt | sed -e "s/@[1-9]//g" | sed -e '1d' > ./primer_position/${i}.txt
done

mkdir -p primer_seq
for i in $(cat ../name.txt); do
    seqkit subseq --bed ./primer_position/${i}.txt ./mod_seq/${i}.fasta -o ./primer_seq/${i}.fasta
    seqkit fx2tab ./primer_seq/${i}.fasta | sed -e 's/:\.//g' | sed -e 's/ //g' | sed -e 's/\t$//g' > ./primer_seq/${i}_seq.txt
done

mkdir -p tmp
for i in $(cat ../name.txt); do
    awk '{print $1"_"$2+1"-"$3}' ./primer_position/${i}.txt > ./tmp/${i}_tmp.txt
    awk '{print $1}' ./primer_result/${i}_result.txt | sed -e '1d' > ./tmp/${i}.txt
    paste ./tmp/${i}_tmp.txt ./tmp/${i}.txt > ./tmp/${i}_name.txt
done

mkdir -p seq_result
for i in $(cat ../name.txt); do
    awk 'NR==FNR{a[$1]=$2;next}{print $0 FS a[$1]}' ./primer_seq/${i}_seq.txt ./tmp/${i}_name.txt | sed -e "s/ /\t/g" | awk -F '\t' '{print $2"\t"$1"\t"$3}' > ./seq_result/${i}_seq_final.txt
done

mkdir -p primer_tmp
for i in $(cat ../name.txt); do
    cat ./primer_result/${i}_result.txt | xargs -i echo ${i}--{} > ./primer_tmp/${i}.txt
    sed -e '1d' ./primer_tmp/${i}.txt | awk -F '\t' '{print $1"\t"$10"\t"$19"\t"$5"\t"$14"\t"$6"\t"$15}' > ./primer_tmp/${i}_ePCR_primer.txt
done

cat ./seq_result/*_seq_final.txt > all_seq.txt
cat ./primer_tmp/*_ePCR_primer.txt > all_primer.txt

awk -F '\t' '
BEGIN {
    while ((getline line < "all_seq.txt") > 0) {
        n = split(line, fields, "\t");
        if (n >= 3) {
            region_id = fields[1];
            position = fields[2];
            sequence = fields[3];
            seq_map[region_id] = position "\t" sequence;
        }
    }
    close("all_seq.txt");
}
{
    if (NF >= 7) {
        primer_id = $1;
        forward_seq = $2;
        reverse_seq = $3;
        tm_f = $4;
        tm_r = $5;
        gc_f = $6;
        gc_r = $7;
        dash_pos = index(primer_id, "--");
        if (dash_pos > 0) {
            region_id = substr(primer_id, dash_pos + 2);
            if (region_id in seq_map) {
                split(seq_map[region_id], seq_fields, "\t");
                position = seq_fields[1];
                amplicon_seq = seq_fields[2];
                print primer_id "\t" forward_seq "\t" reverse_seq "\t" tm_f "\t" tm_r "\t" gc_f "\t" gc_r "\t" position "\t" amplicon_seq;
            } else {
                print primer_id "\t" forward_seq "\t" reverse_seq "\t" tm_f "\t" tm_r "\t" gc_f "\t" gc_r "\t\t";
            }
        }
    }
}' all_primer.txt > primer_result.txt

sed -i 's/\--/\t/g' primer_result.txt

echo "primer_result.txt generated"

mkdir -p ../my_result
cp primer_result.txt ../my_result/primer_result.txt
echo "copied to my_result/primer_result.txt"
