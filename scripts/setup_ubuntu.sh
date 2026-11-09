#!/usr/bin/env bash
# Ubuntu + NVIDIA setup:  bash scripts/setup_ubuntu.sh [cu124]
set -euo pipefail
cd "$(dirname "$0")/.."
CUDA_TAG="${1:-cu124}"        # match your driver: nvidia-smi shows the max CUDA version
command -v conda >/dev/null || { echo "conda not found - install miniforge first"; exit 1; }
nvidia-smi || echo "WARNING: nvidia-smi failed - is the NVIDIA driver installed?"
if conda env list | grep -qE '^humotech\s'; then
  conda env update -n humotech -f environment.yml
else
  conda env create -f environment.yml
fi
conda run -n humotech python -m pip install torch --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"
conda run -n humotech python -m pip install -e ".[pose,refine,dev]"
# GPU ONNX Runtime for rtmlib (replace the CPU build)
conda run -n humotech python -m pip uninstall -y onnxruntime || true
conda run -n humotech python -m pip install onnxruntime-gpu
conda run -n humotech python -m pip install ultralytics smplx || true
conda run -n humotech humotech check
conda run -n humotech python -m pytest
echo
echo "Done. For GVHMR/WHAM see scripts/install_gvhmr.sh and docs/ubuntu_handoff.md"
