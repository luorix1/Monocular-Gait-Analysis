"""Adapters for SMPL-family video lifters (run on Ubuntu + NVIDIA).

GVHMR (Shen et al., SIGGRAPH Asia 2024) — recommended: https://github.com/zju3dv/GVHMR
    python tools/demo/demo.py --video=<video> -s          # -s = static camera
    -> outputs/demo/<name>/hmr4d_results.pt  (SMPL-X params, keys smpl_params_incam/global)
WHAM (Shin et al., CVPR 2024): https://github.com/yohanshin/WHAM
    python demo.py --video <video> --estimate_local_only --save_pkl
    -> output/demo/<name>/wham_output.pkl    (SMPL params; 'pose','trans','betas',...)

Both need the SMPL / SMPL-X body model files (free registration at smpl.is.tue.mpg.de /
smpl-x.is.tue.mpg.de) placed under ``<model_dir>/smpl`` and ``<model_dir>/smplx``.

We only use the *root-relative* body pose (in the camera frame) from these networks; global
placement, scale and foot contact come from our treadmill calibration + refinement, which
is more reliable than the networks' monocular depth / world trajectory on a treadmill
(their world-grounding priors assume the feet are static during contact, which is false
on a moving belt).

NOTE: written against the public output formats as of 2025-2026; verify on first run.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..calibration.camera import Camera
from ..io.data import Keypoints2D, Keypoints3D
from ..keypoints import HALPE26, IDX
from .planar import place_root_relative

# SMPL / SMPL-X share the first 22 regressed joints
_SMPL_J = {"pelvis": 0, "LHip": 1, "RHip": 2, "LKnee": 4, "RKnee": 5, "LAnkle": 7, "RAnkle": 8,
           "Neck": 12, "Head": 15, "LShoulder": 16, "RShoulder": 17, "LElbow": 18, "RElbow": 19,
           "LWrist": 20, "RWrist": 21}
# smplx.vertex_ids keys -> Halpe names
_VTX = {"nose": "Nose", "reye": "REye", "leye": "LEye", "rear": "REar", "lear": "LEar",
        "LBigToe": "LBigToe", "LSmallToe": "LSmallToe", "LHeel": "LHeel",
        "RBigToe": "RBigToe", "RSmallToe": "RSmallToe", "RHeel": "RHeel"}


def smpl_forward_halpe26(params: dict, model_type: str, model_dir: str | Path,
                         gender: str = "neutral", device: str = "cpu", batch: int = 512) -> np.ndarray:
    """Run SMPL/SMPL-X and return (T, 26, 3) Halpe-26 joints in the params' frame."""
    import torch
    import smplx
    from smplx.vertex_ids import vertex_ids

    T = len(params["global_orient"])
    kw = dict(model_path=str(model_dir), model_type=model_type, gender=gender, batch_size=batch)
    if model_type == "smplx":
        kw.update(use_pca=False, flat_hand_mean=True, num_betas=params["betas"].shape[-1])
    model = smplx.create(**kw).to(device)
    vids = vertex_ids["smplx" if model_type == "smplx" else "smplh"]
    out = np.zeros((T, len(HALPE26), 3))
    for s in range(0, T, batch):
        e = min(T, s + batch)
        n = e - s
        def tt(x, d):
            a = torch.as_tensor(np.asarray(x[s:e]), dtype=torch.float32, device=device).reshape(n, d)
            if n < batch:
                a = torch.cat([a, a[-1:].repeat(batch - n, 1)])
            return a
        betas = params["betas"]
        if betas.ndim == 1:
            betas = np.repeat(betas[None], T, 0)
        bp = np.asarray(params["body_pose"]).reshape(T, -1)
        args = dict(global_orient=tt(params["global_orient"], 3), body_pose=tt(bp, bp.shape[1]),
                    betas=tt(betas, betas.shape[-1]), transl=tt(params["transl"], 3))
        with torch.no_grad():
            o = model(**args)
        J = o.joints[:n].cpu().numpy()
        V = o.vertices[:n].cpu().numpy()
        for name, j in _SMPL_J.items():
            if name in IDX:
                out[s:e, IDX[name]] = J[:, j]
        for k, name in _VTX.items():
            out[s:e, IDX[name]] = V[:, vids[k]]
        out[s:e, IDX["Hip"]] = 0.5 * (J[:, 1] + J[:, 2])
    return out


def load_gvhmr(result_pt: str | Path) -> dict:
    import torch
    r = torch.load(result_pt, map_location="cpu")
    p = r["smpl_params_incam"]
    return {"model_type": "smplx", **{k: v.numpy() for k, v in p.items()}}


def load_wham(result_pkl: str | Path, subject: int | None = None) -> dict:
    import joblib
    r = joblib.load(result_pkl)
    sid = subject if subject is not None else max(r, key=lambda k: len(r[k]["frame_ids"]))
    d = r[sid]
    pose = np.asarray(d["pose"])
    return {"model_type": "smpl", "global_orient": pose[:, :3], "body_pose": pose[:, 3:72],
            "betas": np.asarray(d["betas"]), "transl": np.asarray(d["trans"]),
            "frame_ids": np.asarray(d["frame_ids"])}


def lift_from_smpl(params: dict, k2d: Keypoints2D, cam: Camera, model_dir: str | Path,
                   device: str = "cpu") -> Keypoints3D:
    J = smpl_forward_halpe26(params, params["model_type"], model_dir, device=device)
    if "frame_ids" in params:  # WHAM may skip frames
        full = np.full((len(k2d.kp),) + J.shape[1:], np.nan)
        full[params["frame_ids"]] = J
        J = full
        good = np.isfinite(J).all((1, 2))
        for j in range(J.shape[1]):
            for c in range(3):
                J[~good, j, c] = np.interp(np.flatnonzero(~good), np.flatnonzero(good), J[good, j, c])
    rel = J - J[:, IDX["Hip"]][:, None]
    k3d = place_root_relative(rel, k2d, cam)
    k3d.meta["lifter"] = params["model_type"]
    return k3d
