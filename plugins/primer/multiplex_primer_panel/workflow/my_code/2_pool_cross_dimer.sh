#!/bin/bash
set -euo pipefail

INPUT_FASTA="${1:?missing input fasta}"
OUTPUT_TXT="${2:?missing output path}"

cat > "$OUTPUT_TXT" <<EOF
pathogen_A	primer_A	pathogen_B	primer_B	score	dg
stub_panel	F_1	stub_panel	R_1	0	0
EOF
