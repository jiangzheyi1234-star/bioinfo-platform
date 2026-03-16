#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
export BLAST_DB_PATH="${BLAST_DB_PATH:-${MULTIPLEX_DB_PATH:-}}"
cd "$PROJECT_DIR" || exit 1

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_step()    { echo ""; echo -e "${GREEN}========================================${NC}"; echo -e "${GREEN}步骤 $1: $2${NC}"; echo -e "${GREEN}========================================${NC}"; }

check_conda_env() {
    print_info "检查 conda 环境..."
    if ! command -v conda &> /dev/null; then
        print_error "conda 未安装或不在 PATH 中"
        exit 1
    fi
    if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    else
        eval "$(conda shell.bash hook)" 2>/dev/null || true
    fi
    if conda activate PCR 2>/dev/null; then
        print_success "PCR 环境已激活"
    else
        if [ "$CONDA_DEFAULT_ENV" = "PCR" ]; then
            print_success "已在 PCR 环境中"
        else
            print_error "请先激活 PCR 环境: conda activate PCR"
            exit 1
        fi
    fi
}

check_tools() {
    print_info "检查必需工具..."
    local tools=("seqkit" "blastn" "primer3_core" "perl" "python3")
    local missing_tools=()
    for tool in "${tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    if [ ${#missing_tools[@]} -gt 0 ]; then
        print_error "以下工具未找到: ${missing_tools[*]}"
        exit 1
    fi
    print_success "所有必需工具已就绪"
}

check_input() {
    print_info "检查输入文件..."
    if [ ! -d "ref_genome" ]; then
        print_error "ref_genome 目录不存在"
        exit 1
    fi
    local genome_count
    genome_count=$(find -L ref_genome -maxdepth 1 -type f \( -name "*.fasta" -o -name "*.fna" \) | wc -l)
    if [ "$genome_count" -eq 0 ]; then
        print_error "ref_genome 目录中没有找到 .fasta/.fna 文件"
        exit 1
    fi
    print_success "找到 $genome_count 个基因组文件"
}

check_database() {
    print_info "检查 core_nt 数据库..."
    if [ -z "${BLAST_DB_PATH:-}" ]; then
        print_error "BLAST_DB_PATH 未设置"
        exit 1
    fi
    if [ ! -f "${BLAST_DB_PATH}.00.nhr" ]; then
        print_error "core_nt 数据库未找到: $BLAST_DB_PATH"
        exit 1
    fi
    print_success "core_nt 数据库已就绪"
}

timer_display() {
    local start_time
    start_time=$(date +%s)
    while true; do
        local current_time elapsed hours minutes seconds
        current_time=$(date +%s)
        elapsed=$((current_time - start_time))
        hours=$((elapsed / 3600))
        minutes=$(((elapsed % 3600) / 60))
        seconds=$((elapsed % 60))
        printf "\r${YELLOW}[运行中]${NC} 已运行时间: %02d:%02d:%02d" "$hours" "$minutes" "$seconds"
        sleep 1
    done
}

run_step() {
    local step_num=$1
    local step_name=$2
    local script=$3
    local show_timer=${4:-false}

    print_step "$step_num" "$step_name"

    if [ ! -f "$script" ]; then
        print_error "脚本不存在: $script"
        exit 1
    fi

    local cmd="bash"
    if [[ "$script" == *.py ]]; then
        cmd="python3"
    fi

    if [ "$show_timer" = "true" ]; then
        local start_time
        start_time=$(date +%s)
        timer_display &
        local timer_pid=$!
        local script_exit_code=0
        $cmd "$script" || script_exit_code=$?
        kill $timer_pid 2>/dev/null || true
        wait $timer_pid 2>/dev/null || true
        printf "\r                                                                                \r"
        if [ $script_exit_code -eq 0 ]; then
            local end_time total_time hours minutes seconds
            end_time=$(date +%s)
            total_time=$((end_time - start_time))
            hours=$((total_time / 3600))
            minutes=$(((total_time % 3600) / 60))
            seconds=$((total_time % 60))
            printf "${GREEN}[SUCCESS]${NC} %s 完成 (耗时: %02d:%02d:%02d)\n" "$step_name" "$hours" "$minutes" "$seconds"
            return 0
        fi
        print_error "$step_name 失败 (退出码: $script_exit_code)"
        exit 1
    fi

    if $cmd "$script"; then
        print_success "$step_name 完成"
        return 0
    fi

    print_error "$step_name 失败"
    exit 1
}

OUTPUT_DIR="${MULTIPLEX_OUTPUT_DIR:-$(pwd)}"

echo ""
echo "=========================================="
echo "  多重引物池设计全流程"
echo "=========================================="
echo ""

check_conda_env
check_tools
check_input
check_database

print_info "===== 阶段一：引物设计 ====="
run_step "1/16" "文件名标准化" "primer_scripts/1_create_name.py"
run_step "2/16" "基因组切割和BLAST比对" "primer_scripts/2_split_blast.sh" "true"
run_step "3/16" "保守+特异性靶点筛选" "primer_scripts/3_select.py"

# 验证：检查是否有空的 conserved_seq 文件
EMPTY_COUNT=$(find conserved_seq/ -name "*.fasta" -empty 2>/dev/null | wc -l)
if [ "$EMPTY_COUNT" -gt 0 ]; then
    EMPTY_FILES=$(find conserved_seq/ -name "*.fasta" -empty -printf '%f\n' 2>/dev/null | tr '\n' ', ')
    print_error "$EMPTY_COUNT 个病原体的保守序列为空: ${EMPTY_FILES%, }"
    print_error "请检查 BLAST 比对结果或参考基因组文件"
    exit 1
fi
print_success "验证通过: conserved_seq/ 下无空文件"

run_step "4/16" "引物设计和扩增子提取" "primer_scripts/4_primer.sh"
run_step "4b/16" "引物注释（保守/特异）" "primer_scripts/4b_annotate_primers.py"
run_step "5/16" "提取引物对" "primer_scripts/5_1_extract_dimer.sh"
run_step "6/16" "引物二聚体分析" "primer_scripts/5_dimer.sh"
run_step "7/16" "过滤问题引物对" "primer_scripts/5_2_filter_dimer.sh"
run_step "8/16" "提取每种病原体首选引物" "primer_scripts/5_3_extract_first.sh"

cp -f my_result/primer_result.txt "$OUTPUT_DIR/primer_result.txt" 2>/dev/null || true
cp -f my_result/primer_result_final.txt "$OUTPUT_DIR/primer_result_final.txt" 2>/dev/null || true
cp -f my_result/primer_result_final_2.txt "$OUTPUT_DIR/primer_result_final_2.txt" 2>/dev/null || true

CANDIDATES_TSV="my_result/primer_result.txt"
REF_DIR="ref_genome"

if [ ! -f "$CANDIDATES_TSV" ]; then
    print_error "阶段一未生成 primer_result.txt，无法继续阶段二"
    exit 1
fi

print_info "===== 阶段二：多重池优化 ====="

mkdir -p "$OUTPUT_DIR"

echo "[9/16] merge primer candidates"
python my_code/1_merge_primers.py \
  --input "$CANDIDATES_TSV" \
  --output "$OUTPUT_DIR/pool_input.tsv" \
  --fasta "$OUTPUT_DIR/pool_all.fasta"

echo "[10/16] optimize multiplex pool"
python my_code/6_iterative_optimize.py \
  --input "$OUTPUT_DIR/pool_input.tsv" \
  --output "$OUTPUT_DIR/current_pool.tsv" \
  --log "$OUTPUT_DIR/optimization_log.txt" \
  --max-iterations "${MULTIPLEX_MAX_ITERATIONS:-50}" \
  --max-cross-dimer-score "${MULTIPLEX_MAX_CROSS_DIMER_SCORE:-10}" \
  --max-cross-dimer-dg "${MULTIPLEX_MAX_CROSS_DIMER_DG:-6}" \
  --min-amplicon-diff "${MULTIPLEX_MIN_AMPLICON_DIFF_BP:-10}" \
  --max-tm-deviation "${MULTIPLEX_MAX_TM_DEVIATION:-2.0}"

echo "[11/16] assess cross-dimer conflicts"
bash my_code/2_pool_cross_dimer.sh \
  "$OUTPUT_DIR/current_pool.tsv" \
  "$OUTPUT_DIR/pool_cross_dimer.txt" \
  "${MULTIPLEX_MAX_CROSS_DIMER_SCORE:-10}" \
  "${MULTIPLEX_MAX_CROSS_DIMER_DG:-6}"

echo "[12/16] assess in-silico PCR cross-amplification"
bash my_code/3_insilico_pcr.sh \
  "$OUTPUT_DIR/current_pool.tsv" \
  "$REF_DIR" \
  "$OUTPUT_DIR/insilico_pcr_result.txt"

echo "[13/16] check amplicon length deconflicts"
python my_code/4_length_deconflict.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --output "$OUTPUT_DIR/length_deconflict.txt" \
  --min-diff "${MULTIPLEX_MIN_AMPLICON_DIFF_BP:-10}"

echo "[14/16] check Tm/GC uniformity"
python my_code/5_tm_gc_check.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --output "$OUTPUT_DIR/tm_gc_report.txt" \
  --max-deviation "${MULTIPLEX_MAX_TM_DEVIATION:-2.0}"

echo "[15/16] generate final reports"
python my_code/7_final_report.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --panel "$OUTPUT_DIR/multiplex_panel.txt" \
  --order "$OUTPUT_DIR/synthesis_order.txt"

echo "[16/16] validate coverage"
python my_code/8_validate_coverage.py \
  --names "name.txt" \
  --panel "$OUTPUT_DIR/multiplex_panel.txt" \
  --output "$OUTPUT_DIR/validation_report.txt"

print_success "全流程完成"
