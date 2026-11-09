#!/usr/bin/env bash
# macOS (Apple Silicon) setup. Run from anywhere:  bash scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v conda >/dev/null || { echo "conda not found - install miniforge (arm64) first"; exit 1; }
if conda env list | grep -qE '^humotech\s'; then
  conda env update -n humotech -f environment.yml
else
  conda env create -f environment.yml
fi
# PyTorch from PyPI has native arm64 wheels (CPU + MPS); used by the 3D refinement.
conda run -n humotech python -m pip install torch
# this package + 2D pose (rtmlib/ONNX Runtime CPU) + dev tools; YOLO is optional
conda run -n humotech python -m pip install -e ".[pose,refine,dev]"
conda run -n humotech python -m pip install ultralytics || echo "(ultralytics optional - skipped)"
conda run -n humotech humotech check
conda run -n humotech python -m pytest
echo
echo "Done. Activate with:  conda activate humotech"
