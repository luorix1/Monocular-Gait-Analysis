"""Command line interface:  humotech <command> --help"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def cmd_calibrate(a):
    from .calibration import Landmark, belt_corner_world, load_intrinsics, save_calibration, solve_camera
    from .calibration.annotate import click_landmarks, read_frame
    import yaml

    frame = read_frame(a.video, a.frame)
    h, w = frame.shape[:2]
    world = belt_corner_world(a.belt_length, a.belt_width)
    optional = set()
    if a.extra:  # YAML: {name: [X, Y, Z], ...} in the treadmill frame
        extra = yaml.safe_load(Path(a.extra).read_text())
        for n, xyz in extra.items():
            world[n] = np.array(xyz, float)
            optional.add(n)
    print("Belt corners: FRONT = end the subject faces. LEFT/RIGHT = subject's left/right.")
    pts = click_landmarks(frame, list(world), optional=optional)
    lms = [Landmark(n, world[n], pts[n]) for n in world if n in pts]
    K = dist = None
    if a.intrinsics:
        K, dist, _ = load_intrinsics(a.intrinsics)
    cam, rep = solve_camera(lms, (w, h), K, dist)
    save_calibration(a.out, cam, lms, rep, {"video": str(a.video), "frame": a.frame,
                                            "belt_length_m": a.belt_length, "belt_width_m": a.belt_width})
    print(json.dumps(rep, indent=2))
    if a.preview:
        _preview_calibration(frame, cam, a.belt_length, a.belt_width, Path(a.out).with_suffix(".png"))


def _preview_calibration(frame, cam, L, W, path):
    import cv2
    img = frame.copy()
    # belt outline + 0.1 m grid + 1 m vertical posts at the corners
    for x in np.arange(-L / 2, L / 2 + 1e-6, 0.1):
        p = cam.project(np.array([[x, 0, -W / 2], [x, 0, W / 2]])).astype(int)
        cv2.line(img, tuple(p[0]), tuple(p[1]), (0, 200, 255), 1)
    for sx in (-1, 1):
        for sz in (-1, 1):
            p = cam.project(np.array([[sx * L / 2, 0, sz * W / 2], [sx * L / 2, 1.0, sz * W / 2]])).astype(int)
            cv2.line(img, tuple(p[0]), tuple(p[1]), (0, 255, 0), 2)
    o = cam.project(np.array([[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0], [0, 0, 0.3]])).astype(int)
    for k, c in zip(range(1, 4), [(0, 0, 255), (0, 255, 0), (255, 0, 0)]):
        cv2.arrowedLine(img, tuple(o[0]), tuple(o[k]), c, 2)
    cv2.imwrite(str(path), img)
    print(f"preview -> {path}  (grid should lie on the belt; green posts are 1 m tall; X red, Y green, Z blue)")


def cmd_intrinsics(a):
    from .calibration.solve import calibrate_intrinsics_checkerboard
    from .io.data import iter_frames
    cols, rows = map(int, a.board.lower().split("x"))
    frames = (f for _, f in iter_frames(a.video, step=a.step))
    K, dist, size, rms = calibrate_intrinsics_checkerboard(frames, (cols, rows), a.square)
    Path(a.out).write_text(json.dumps({"K": K.tolist(), "dist": dist.tolist(), "image_size": list(size),
                                       "rms_px": rms}, indent=2))
    print(f"RMS {rms:.3f}px -> {a.out}")


def cmd_detect(a):
    from .pose2d.detect import detect_video
    k = detect_video(a.video, a.backend, a.device, a.mode, a.yolo_weights)
    k.save(a.out)
    print(f"{k.kp.shape} -> {a.out}")


def cmd_run(a):
    from .calibration.camera import Camera
    from .io.data import Keypoints2D
    from .pipeline import load_config, run_pipeline
    ov = {}
    if a.height:
        ov.setdefault("subject", {})["height_m"] = a.height
    if a.mass:
        ov.setdefault("subject", {})["mass_kg"] = a.mass
    if a.device:
        ov.setdefault("refine", {})["device"] = a.device
        ov.setdefault("pose2d", {})["device"] = a.device
    cfg = load_config(a.config, ov)
    cam = Camera.load(a.calib)
    k2d = Keypoints2D.load(a.kp2d) if a.kp2d else None
    res = run_pipeline(cam, a.out, cfg, video=a.video, k2d_raw=k2d, force=a.force)
    _print_summary(res["summary"])


def _print_summary(s):
    keys = ["stride_time", "stride_frequency", "stride_length", "step_length", "step_width", "stance_pct",
            "double_support_pct"]
    print(f"\nbelt speed used: {s['belt_speed_m_s']:.3f} m/s   cadence: {s.get('cadence_steps_per_min', float('nan')):.1f} steps/min")
    for k in keys:
        if k in s:
            v = s[k]
            print(f"  {k:20s} {v['mean']:8.3f} ± {v['sd']:.3f}   (L {v['L']:.3f} / R {v['R']:.3f})")


def cmd_synth(a):
    from .calibration import save_calibration
    from .pipeline import load_config, run_pipeline
    from .synth.gait_generator import GaitParams, make_session
    from .calibration import solve_camera
    s = make_session(GaitParams(belt_speed=a.speed, stride_time=a.stride_time), seed=a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cam, rep = solve_camera(s.landmarks, s.cam.image_size)
    save_calibration(out / "calibration.json", cam, s.landmarks, rep)
    s.k2d.save(out / "kp2d_synthetic.npz")
    (out / "ground_truth.json").write_text(json.dumps({k: (v.tolist() if hasattr(v, "tolist") else
                                                          {kk: vv.tolist() for kk, vv in v.items()} if isinstance(v, dict) else v)
                                                      for k, v in s.gt.items()}, indent=2))
    print(f"synthetic session -> {out}")
    if a.run:
        cfg = load_config(a.config)
        res = run_pipeline(cam, out / "results", cfg, k2d_raw=s.k2d)
        _print_summary(res["summary"])
        print(f"\nground truth: v={s.gt['belt_speed']}  stride_time={s.gt['stride_time']}  "
              f"stride_length={s.gt['stride_length']:.3f}  step_width={s.gt['step_width']}")


def cmd_check(a):
    import importlib
    import platform
    print(f"python {sys.version.split()[0]} on {platform.system()} {platform.machine()}")
    for mod in ["numpy", "scipy", "cv2", "pandas", "yaml", "torch", "opensim", "rtmlib", "onnxruntime",
                "ultralytics", "smplx"]:
        try:
            m = importlib.import_module(mod)
            extra = ""
            if mod == "torch":
                extra = f"  cuda={m.cuda.is_available()} mps={getattr(m.backends, 'mps', None) is not None and m.backends.mps.is_available()}"
            if mod == "onnxruntime":
                extra = f"  providers={m.get_available_providers()}"
            print(f"  [ok]      {mod:12s} {getattr(m, '__version__', '')}{extra}")
        except Exception as e:  # noqa: BLE001
            print(f"  [missing] {mod:12s} ({type(e).__name__})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="humotech", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrate", help="click belt corners (+extra landmarks) on a frame -> calibration.json")
    c.add_argument("video")
    c.add_argument("--out", default="calibration.json")
    c.add_argument("--frame", type=int, default=0)
    c.add_argument("--belt-length", type=float, required=True, help="m, front-back")
    c.add_argument("--belt-width", type=float, required=True, help="m, left-right")
    c.add_argument("--intrinsics", help="JSON from `humotech intrinsics` (recommended)")
    c.add_argument("--extra", help="YAML of extra landmarks {name: [X,Y,Z]} in treadmill frame")
    c.add_argument("--no-preview", dest="preview", action="store_false")
    c.set_defaults(func=cmd_calibrate)

    c = sub.add_parser("intrinsics", help="checkerboard intrinsics from a video")
    c.add_argument("video")
    c.add_argument("--board", default="9x6", help="inner corners, cols x rows")
    c.add_argument("--square", type=float, default=0.025, help="square size (m)")
    c.add_argument("--step", type=int, default=10, help="use every N-th frame")
    c.add_argument("--out", default="intrinsics.json")
    c.set_defaults(func=cmd_intrinsics)

    c = sub.add_parser("detect", help="2D keypoints only")
    c.add_argument("video")
    c.add_argument("--out", default="kp2d_raw.npz")
    c.add_argument("--backend", default="rtmlib", choices=["rtmlib", "yolo"])
    c.add_argument("--device", default="cpu")
    c.add_argument("--mode", default="balanced")
    c.add_argument("--yolo-weights", default="yolo11m-pose.pt")
    c.set_defaults(func=cmd_detect)

    c = sub.add_parser("run", help="full pipeline")
    c.add_argument("--video")
    c.add_argument("--kp2d", help="reuse an existing kp2d_raw.npz instead of running detection")
    c.add_argument("--calib", required=True)
    c.add_argument("--config")
    c.add_argument("--out", required=True)
    c.add_argument("--height", type=float)
    c.add_argument("--mass", type=float)
    c.add_argument("--device")
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=cmd_run)

    c = sub.add_parser("synth", help="generate a synthetic session (and optionally run the pipeline on it)")
    c.add_argument("--out", default="data/synthetic")
    c.add_argument("--speed", type=float, default=1.2)
    c.add_argument("--stride-time", type=float, default=1.1)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--config")
    c.add_argument("--run", action="store_true")
    c.set_defaults(func=cmd_synth)

    c = sub.add_parser("check", help="report which optional dependencies are available")
    c.set_defaults(func=cmd_check)

    a = p.parse_args(argv)
    if a.cmd == "run" and not (a.video or a.kp2d):
        p.error("run needs --video or --kp2d")
    a.func(a)


if __name__ == "__main__":
    main()
