#!/usr/bin/env bash
# Run all four evaluator ablations sequentially.
# Results saved to Testing/Evaluator/Results/:
#   gemini-2.5-pro.json               — full pipeline (DOM diff + Step 1)
#   gemini-2.5-pro-no_dom_diff.json   — no DOM diff
#   gemini-2.5-pro-no_step1.json      — no Step 1 spec
#   gemini-2.5-pro-no_dom_diff-no_step1.json — screenshots only

set -e
cd "$(dirname "$0")/../.."

echo "============================================"
echo " Ablation 1/4: full pipeline (DOM diff + Step 1)"
echo "============================================"
python Testing/Evaluator/run.py

echo ""
echo "============================================"
echo " Ablation 2/4: no DOM diff"
echo "============================================"
python Testing/Evaluator/run.py --no-dom-diff

echo ""
echo "============================================"
echo " Ablation 3/4: no Step 1 spec"
echo "============================================"
python Testing/Evaluator/run.py --no-step1

echo ""
echo "============================================"
echo " Ablation 4/4: screenshots only (no DOM diff, no Step 1)"
echo "============================================"
python Testing/Evaluator/run.py --no-dom-diff --no-step1

echo ""
echo "All ablations complete. Results in Testing/Evaluator/Results/"
