#!/bin/bash
set -euo pipefail

WORK_DIR="$(pwd)"
OUTPUT_DIR="${MULTIPLEX_OUTPUT_DIR:-$WORK_DIR}"
CANDIDATES_TSV="${WORK_DIR}/primer_candidates.tsv"
REF_DIR="${WORK_DIR}/ref_genome"

mkdir -p "$OUTPUT_DIR"

echo "[1/7] merge primer candidates"
python my_code/1_merge_primers.py \
  --input "$CANDIDATES_TSV" \
  --output "$OUTPUT_DIR/pool_input.tsv" \
  --fasta "$OUTPUT_DIR/pool_all.fasta"

echo "[2/7] optimize multiplex pool"
python my_code/6_iterative_optimize.py \
  --input "$OUTPUT_DIR/pool_input.tsv" \
  --output "$OUTPUT_DIR/current_pool.tsv" \
  --log "$OUTPUT_DIR/optimization_log.txt" \
  --max-iterations "${MULTIPLEX_MAX_ITERATIONS:-50}" \
  --max-cross-dimer-score "${MULTIPLEX_MAX_CROSS_DIMER_SCORE:-10}" \
  --max-cross-dimer-dg "${MULTIPLEX_MAX_CROSS_DIMER_DG:-6}" \
  --min-amplicon-diff "${MULTIPLEX_MIN_AMPLICON_DIFF_BP:-10}" \
  --max-tm-deviation "${MULTIPLEX_MAX_TM_DEVIATION:-2.0}"

echo "[3/7] assess cross-dimer conflicts"
bash my_code/2_pool_cross_dimer.sh \
  "$OUTPUT_DIR/current_pool.tsv" \
  "$OUTPUT_DIR/pool_cross_dimer.txt" \
  "${MULTIPLEX_MAX_CROSS_DIMER_SCORE:-10}" \
  "${MULTIPLEX_MAX_CROSS_DIMER_DG:-6}"

echo "[4/7] assess in-silico PCR cross-amplification"
bash my_code/3_insilico_pcr.sh \
  "$OUTPUT_DIR/current_pool.tsv" \
  "$REF_DIR" \
  "$OUTPUT_DIR/insilico_pcr_result.txt"

echo "[5/7] check amplicon length deconflicts"
python my_code/4_length_deconflict.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --output "$OUTPUT_DIR/length_deconflict.txt" \
  --min-diff "${MULTIPLEX_MIN_AMPLICON_DIFF_BP:-10}"

echo "[6/7] check Tm/GC uniformity"
python my_code/5_tm_gc_check.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --output "$OUTPUT_DIR/tm_gc_report.txt" \
  --max-deviation "${MULTIPLEX_MAX_TM_DEVIATION:-2.0}"

echo "[7/7] generate final reports"
python my_code/7_final_report.py \
  --input "$OUTPUT_DIR/current_pool.tsv" \
  --panel "$OUTPUT_DIR/multiplex_panel.txt" \
  --order "$OUTPUT_DIR/synthesis_order.txt"
