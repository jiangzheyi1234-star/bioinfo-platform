#!/bin/bash

###############################################################################
# 靶向测序引物自动设计流程
# 功能：参考基因组进，靶向测序引物结果出
# 作者：自动生成
# 日期：2026-01-15
###############################################################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录（支持从任意目录运行）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 项目路径（默认为脚本所在目录，可通过环境变量覆盖）
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
cd "$PROJECT_DIR" || exit 1

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}步骤 $1: $2${NC}"
    echo -e "${GREEN}========================================${NC}"
}

# 检查 conda 环境
check_conda_env() {
    print_info "检查 conda 环境..."
    if ! command -v conda &> /dev/null; then
        print_error "conda 未安装或未在 PATH 中"
        exit 1
    fi
    
    # 激活 PCR 环境
    # 尝试多种方式激活 conda 环境
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
        print_warning "无法自动激活 PCR 环境，请手动运行: conda activate PCR"
        print_info "然后重新运行此脚本，或确保在 PCR 环境中运行"
        # 检查是否已经在 PCR 环境中
        if [ "$CONDA_DEFAULT_ENV" = "PCR" ]; then
            print_success "已在 PCR 环境中"
        else
            print_error "请先激活 PCR 环境: conda activate PCR"
            exit 1
        fi
    fi
}

# 检查必需的工具
check_tools() {
    print_info "检查必需的工具..."
    local tools=("seqkit" "blastn" "primer3_core" "perl" "python3")
    local missing_tools=()
    
    for tool in "${tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        print_error "以下工具未找到: ${missing_tools[*]}"
        print_info "请运行: conda activate PCR && conda install -c bioconda seqkit blast primer3"
        exit 1
    fi
    print_success "所有必需工具已就绪"
}

# 检查输入文件
check_input() {
    print_info "检查输入文件..."
    if [ ! -d "ref_genome" ]; then
        print_error "ref_genome 目录不存在"
        print_info "请创建 ref_genome 目录并放入参考基因组文件（.fasta 或 .fna 格式）"
        exit 1
    fi
    
    local genome_count=$(find -L ref_genome -maxdepth 1 -type f \( -name "*.fasta" -o -name "*.fna" \) | wc -l)
    if [ "$genome_count" -eq 0 ]; then
        print_error "ref_genome 目录中没有找到基因组文件（.fasta 或 .fna）"
        print_info "请将参考基因组序列文件放入 ref_genome 目录"
        exit 1
    fi
    
    print_success "找到 $genome_count 个基因组文件"
}

# 检查数据库
check_database() {
    print_info "检查 core_nt 数据库..."
    local db_path="/home/zyserver/project_ssd/common_data/core_nt_database/core_nt"
    if [ ! -f "${db_path}.00.nhr" ]; then
        print_error "core_nt 数据库未找到: $db_path"
        print_info "请确保数据库已构建"
        exit 1
    fi
    print_success "core_nt 数据库已就绪"
}

# 计时器函数（在后台运行）
timer_display() {
    local start_time=$(date +%s)
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        local hours=$((elapsed / 3600))
        local minutes=$(((elapsed % 3600) / 60))
        local seconds=$((elapsed % 60))
        
        # 使用回车符覆盖同一行
        printf "\r${YELLOW}[运行中]${NC} 已运行时间: %02d:%02d:%02d" "$hours" "$minutes" "$seconds"
        sleep 1
    done
}

# 运行步骤并检查错误
run_step() {
    local step_num=$1
    local step_name=$2
    local script=$3
    local show_timer=${4:-false}  # 第四个参数控制是否显示计时器
    
    print_step "$step_num" "$step_name"
    
    if [ ! -f "$script" ]; then
        print_error "脚本不存在: $script"
        exit 1
    fi
    
    # 根据文件扩展名选择解释器
    local cmd=""
    if [[ "$script" == *.py ]]; then
        cmd="python3"
    elif [[ "$script" == *.sh ]]; then
        cmd="bash"
    else
        # 检查 shebang
        local first_line=$(head -n 1 "$script")
        if [[ "$first_line" == *python* ]]; then
            cmd="python3"
        elif [[ "$first_line" == *bash* ]] || [[ "$first_line" == *sh* ]]; then
            cmd="bash"
        else
            # 默认为 bash
            cmd="bash"
        fi
    fi
    
    # 如果需要显示计时器
    if [ "$show_timer" = "true" ]; then
        local start_time=$(date +%s)
        # 启动计时器（后台进程）
        timer_display &
        local timer_pid=$!
        
        # 运行脚本
        local script_exit_code=0
        $cmd "$script" || script_exit_code=$?
        
        # 停止计时器（忽略错误，避免影响主流程）
        kill $timer_pid 2>/dev/null || true
        wait $timer_pid 2>/dev/null || true
        
        # 清除计时器行
        printf "\r                                                                                \r"
        
        # 检查脚本执行结果
        if [ $script_exit_code -eq 0 ]; then
            # 计算总时间
            local end_time=$(date +%s)
            local total_time=$((end_time - start_time))
            local hours=$((total_time / 3600))
            local minutes=$(((total_time % 3600) / 60))
            local seconds=$((total_time % 60))
            
            # 显示完成信息
            printf "${GREEN}[SUCCESS]${NC} $step_name 完成 (耗时: %02d:%02d:%02d)\n" "$hours" "$minutes" "$seconds"
            return 0
        else
            print_error "$step_name 失败 (退出码: $script_exit_code)"
            exit 1
        fi
    else
        # 不显示计时器，正常运行
        if $cmd "$script"; then
            print_success "$step_name 完成"
            return 0
        else
            print_error "$step_name 失败"
            exit 1
        fi
    fi
}

# 显示结果摘要
show_summary() {
    echo ""
    print_step "完成" "结果摘要"
    
    if [ -f "my_result/primer_result.txt" ]; then
        local total=$(wc -l < my_result/primer_result.txt)
        print_success "总引物对数: $total"
    fi
    
    if [ -f "my_result/primer_result_final.txt" ]; then
        local final=$(wc -l < my_result/primer_result_final.txt)
        print_success "最终引物对数: $final"
    fi
    
    if [ -f "my_result/primer_result_final_2.txt" ]; then
        local final2=$(wc -l < my_result/primer_result_final_2.txt)
        print_success "每种病原体第一个引物对数: $final2"
    fi
    
    echo ""
    print_success "所有结果文件位于: my_result/ 目录"
    echo ""
    echo "主要结果文件："
    echo "  - primer_result.txt: 所有设计的引物对"
    echo "  - primer_result_final.txt: 过滤后的引物对"
    echo "  - primer_result_final_2.txt: 每种病原体的第一个引物对（推荐使用）"
    echo ""
}

###############################################################################
# 主流程
###############################################################################

echo ""
echo "=========================================="
echo "  靶向测序引物自动设计流程"
echo "  参考基因组进，引物结果出"
echo "=========================================="
echo ""

# 前置检查
check_conda_env
check_tools
check_input
check_database

# 运行流程
run_step "1" "文件名标准化" "my_code/1_create_name.py"
run_step "2" "基因组切割和BLAST比对" "my_code/2_split_blast.sh" "true"  # 显示计时器
run_step "3" "保守特异性序列筛选" "my_code/3_select.sh"
run_step "4" "引物设计和扩增子提取" "my_code/4_primer.sh"
run_step "5" "提取引物对用于二聚体分析" "my_code/5_1_extract_dimer.sh"
run_step "6" "引物二聚体分析" "my_code/5_dimer.sh"
run_step "7" "过滤有问题的引物对" "my_code/5_2_filter_dimer.sh"
run_step "8" "提取每种病原体的第一个引物对" "my_code/5_3_extract_first.sh"

# 显示结果
show_summary

print_success "流程全部完成！"
