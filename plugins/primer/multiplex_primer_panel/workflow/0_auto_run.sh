#!/bin/bash
set -euo pipefail

WORK_DIR="$(pwd)"
OUTPUT_DIR="${MULTIPLEX_OUTPUT_DIR:-$WORK_DIR}"
mkdir -p "$OUTPUT_DIR"

python my_code/1_merge_primers.py \
  --input "${MULTIPLEX_INPUT_CANDIDATES}" \
  --output "$OUTPUT_DIR/pool_input.tsv" \
  --fasta "$OUTPUT_DIR/pool_all.fasta"

bash my_code/2_pool_cross_dimer.sh \
  "$OUTPUT_DIR/pool_all.fasta" \
  "$OUTPUT_DIR/pool_cross_dimer.txt"

python my_code/4_length_deconflict.py \
  --input "$OUTPUT_DIR/pool_input.tsv" \
  --output "$OUTPUT_DIR/length_deconflict.txt" \
  --min-diff "${MULTIPLEX_MIN_AMPLICON_DIFF_BP:-10}"

python my_code/5_tm_gc_check.py \
  --input "$OUTPUT_DIR/pool_input.tsv" \
  --output "$OUTPUT_DIR/tm_gc_report.txt" \
  --max-deviation "${MULTIPLEX_MAX_TM_DEVIATION:-2.0}"

python my_code/6_iterative_optimize.py \
  --input "$OUTPUT_DIR/pool_input.tsv" \
  --output "$OUTPUT_DIR/current_pool.tsv" \
  --log "$OUTPUT_DIR/optimization_log.txt" \
  --max-iterations "${MULTIPLEX_MAX_ITERATIONS:-50}"

python my_code/7_final_report.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --panel "$OUTPUT_DIR/multiplex_panel.txt" \
  --order "$OUTPUT_DIR/synthesis_order.txt"
