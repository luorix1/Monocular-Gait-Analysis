#!/usr/bin/env bash
# macOS (Apple Silicon) setup. Run from anywhere:  bash scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v conda >/dev/null || { echo "conda not found - install miniforge (arm64) first"; exit 1; }
# Native arm64 packages even if miniforge itself is the Intel build (running under Rosetta):
# an Intel env would get no current PyTorch wheels and run everything translated.
if [[ "$(uname -m)" == "arm64" || "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" == "1" ]]; then
  export CONDA_SUBDIR=osx-arm64
fi
if conda env list | grep -qE '^humotech\s'; then
  conda env update -n humotech -f environment.yml
else
  conda env create -f environment.yml
fi
[[ -n "${CONDA_SUBDIR:-}" ]] && conda env config vars set -n humotech CONDA_SUBDIR="$CONDA_SUBDIR" >/dev/null
# PyTorch from conda-forge, NOT pip: the pip wheel bundles its own libomp, which clashes with the conda
# packages' OpenMP ("OMP: Error #15 ... libomp.dylib already initialized") and aborts on import.
conda install -n humotech -y -c conda-forge pytorch
# this package + 2D pose (rtmlib/ONNX Runtime CPU) + web app + dev tools; YOLO is optional
conda run -n humotech python -m pip install -e ".[pose,refine,app,dev]"
conda run -n humotech python -m pip install ultralytics || echo "(ultralytics optional - skipped)"
conda run -n humotech humotech check
conda run -n humotech python -m pytest
echo
echo "Done. Activate with:  conda activate humotech"
echo "No NVIDIA GPU on a Mac: process with --device cpu (CLI) or Compute device = CPU (app)."
