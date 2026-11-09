"""End-to-end pipeline with cached intermediate files in a session output directory.

    out_dir/
      kp2d_raw.npz  kp2d.npz            2D keypoints (raw / cleaned)
      analysis_2d.json                  2D-only events + belt speed (sanity check)
      kp3d_init.npz kp3d_refined.npz    3D keypoints (treadmill frame)
      refine_info.json
      opensim/ model_markers.osim scaled.osim markers.trc ik.mot kp3d_model.npz
      events.json strides.csv summary.json plots/
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from .calibration.camera import Camera
from .gait.analysis import analyze_2d
from .gait.belt_speed import belt_speed_from_3d
from .gait.events import detect_events_velocity, detect_events_zeni
from .gait.spatiotemporal import stride_table, summarize
from .io.data import Keypoints2D
from .keypoints import FOOT, IDX
from .pose2d.filtering import clean_keypoints

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    cfg = yaml.safe_load(DEFAULT_CONFIG.read_text()) if DEFAULT_CONFIG.exists() else {}
    if path:
        _deep_update(cfg, yaml.safe_load(Path(path).read_text()) or {})
    if overrides:
        _deep_update(cfg, overrides)
    return cfg


def _deep_update(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_update(a[k], v)
        else:
            a[k] = v
    return a


def _json(obj):
    if isinstance(obj, dict):
        return {str(k): _json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj


def _dump(path, obj):
    Path(path).write_text(json.dumps(_json(obj), indent=2, default=str))


def detect_events(X: np.ndarray, fps: float, cfg: dict, belt_speed: float):
    heel = {s: X[:, IDX[FOOT[s]["heel"]]] for s in FOOT}
    toe = {s: X[:, IDX[FOOT[s]["toe"]]] for s in FOOT}
    ec = cfg["events"]
    if ec["method"] == "velocity":
        ev = detect_events_velocity(heel, toe, fps, belt_speed, frac=ec.get("velocity_frac", 0.5))
    else:
        ev = detect_events_zeni(heel, toe, X[:, IDX["Hip"]], fps)
    for s in ev.hs:
        ev.hs[s] = ev.hs[s] + ec.get("hs_offset_ms", 0) * fps / 1000
        ev.to[s] = ev.to[s] + ec.get("to_offset_ms", 0) * fps / 1000
    return ev, heel


def run_pipeline(cam: Camera, out_dir: str | Path, cfg: dict, video: str | Path | None = None,
                 k2d_raw: Keypoints2D | None = None, force: bool = False, log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config_used.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    fps = None

    # 1. 2D keypoints ----------------------------------------------------------
    p_raw = out / "kp2d_raw.npz"
    if k2d_raw is None:
        if p_raw.exists() and not force:
            k2d_raw = Keypoints2D.load(p_raw)
        else:
            from .pose2d.detect import detect_video
            pc = cfg["pose2d"]
            log(f"[1/6] 2D pose with {pc['backend']} ...")
            k2d_raw = detect_video(video, pc["backend"], pc["device"], pc.get("mode", "balanced"),
                                   pc.get("yolo_weights", "yolo11m-pose.pt"))
    k2d_raw.save(p_raw)
    cc = cfg["clean"]
    k2d = clean_keypoints(k2d_raw, cc["conf_thr"], cc["max_gap_s"], cc["cutoff_hz"], cc.get("fix_lr_swaps", True))
    k2d.save(out / "kp2d.npz")
    fps = k2d.fps

    # 2. 2D-only analysis (belt speed seed + sanity check) ---------------------
    log("[2/6] 2D-only events and belt speed ...")
    a2 = analyze_2d(k2d.uv, cam, fps, k2d.conf)
    _dump(out / "analysis_2d.json", {"belt_speed": a2["belt_speed"], "events": a2["events"].to_dict(),
                                     "summary": a2["summary"]})
    v2d = a2["belt_speed"]["belt_speed"]
    log(f"      belt speed (2D stance foot): {v2d:.3f} m/s")

    # 3. 3D lift --------------------------------------------------------------
    lc = cfg["lift"]
    log(f"[3/6] 3D lift ({lc['backend']}) ...")
    if lc["backend"] == "planar":
        from .lift3d.planar import planar_init
        k3d0 = planar_init(k2d, cam, cfg["subject"]["height_m"])
    elif lc["backend"] in ("gvhmr", "wham"):
        from .lift3d import smpl_lifters as sl
        params = sl.load_gvhmr(lc["result_path"]) if lc["backend"] == "gvhmr" else sl.load_wham(lc["result_path"])
        k3d0 = sl.lift_from_smpl(params, k2d, cam, lc["smpl_model_dir"], device=cfg["refine"]["device"])
    else:
        raise ValueError(lc["backend"])
    k3d0.save(out / "kp3d_init.npz")

    # 4. treadmill-constrained refinement --------------------------------------
    rc = cfg["refine"]
    k3d, v_ref = k3d0, np.nan
    if rc.get("enabled", True):
        from .lift3d.refine import RefineConfig, refine
        log("[4/6] treadmill-constrained refinement ...")
        rcfg = RefineConfig(**{k: v for k, v in rc.items() if k in RefineConfig.__dataclass_fields__},
                            init_belt_speed=v2d if np.isfinite(v2d) else None, verbose=False)
        k3d, info = refine(k2d, k3d0, cam, rcfg)
        v_ref = info["belt_speed"]
        _dump(out / "refine_info.json", info)
        log(f"      reprojection RMSE {info['reproj_rmse_px']:.2f} px, belt speed {v_ref:.3f} m/s")
    k3d.save(out / "kp3d_refined.npz")

    # 5. OpenSim scale + IK ---------------------------------------------------------
    k3d_model, mot = None, None
    if cfg["opensim"].get("enabled", True):
        try:
            from .biomech import opensim_pipeline as op
            log("[5/6] OpenSim scaling + inverse kinematics ...")
            od = out / "opensim"
            od.mkdir(exist_ok=True)
            model, factors = op.scale_model(k3d, cfg["subject"]["mass_kg"], od / "scaled.osim")
            trc = op.write_markers_trc(k3d, od / "markers.trc")
            mot = op.run_ik(model, trc, od / "ik.mot")
            k3d_model = op.ik_to_keypoints3d(model, mot, fps)
            k3d_model.save(od / "kp3d_model.npz")
            _dump(od / "scale_factors.json", factors)
        except ImportError as e:
            log(f"      skipped: {e}")

    # 6. events + spatiotemporal ---------------------------------------------------
    log("[6/6] gait events + spatiotemporal parameters ...")
    src = cfg["events"]["source"]
    X = {"opensim": k3d_model.X if k3d_model is not None else k3d.X, "refined": k3d.X}.get(src, k3d.X)
    bc = cfg["belt_speed"]
    ev_tmp, _ = detect_events(X, fps, {**cfg, "events": {**cfg["events"], "method": "zeni"}}, 1.0)
    v3d = belt_speed_from_3d(X, ev_tmp, fps)["belt_speed"]
    v = {"known": bc.get("known_m_s"), "2d": v2d, "3d": v3d, "refined": v_ref}.get(bc["source"])
    if v is None or not np.isfinite(v):
        v = v3d if np.isfinite(v3d) else v2d
    if src == "2d":
        ev, heel = a2["events"], None
        from .gait.analysis import foot_tracks_from_2d
        heel = foot_tracks_from_2d(k2d.uv, cam)[0]
    else:
        ev, heel = detect_events(X, fps, cfg, v)
    df = stride_table(ev, heel, v)
    summ = summarize(df, v)
    summ["belt_speed_estimates"] = {"2d": v2d, "refined": v_ref, "3d_" + src: v3d, "used": v,
                                    "source": bc["source"]}
    df.to_csv(out / "strides.csv", index=False)
    _dump(out / "events.json", ev.to_dict())
    _dump(out / "summary.json", summ)
    try:
        from .report import make_plots
        make_plots(out, X, ev, fps, mot)
    except Exception as e:  # plotting must never break the pipeline
        log(f"      plotting failed: {e}")
    log(f"done -> {out}")
    return {"summary": summ, "strides": df, "events": ev, "k3d": k3d, "k3d_model": k3d_model}
