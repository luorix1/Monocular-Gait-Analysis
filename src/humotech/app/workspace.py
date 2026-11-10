"""The data folder as the app sees it: subjects, their videos/trials, calibration, intrinsics and results.

All paths handed to the API are names *inside* the data folder; every lookup is validated so a
request can never reach a file outside it.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

import numpy as np

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
RESERVED = {"intrinsics", "synthetic", "results"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CHECKERBOARD_HINT = re.compile(r"intrinsic|checker", re.I)
SPEED_IN_NAME = re.compile(r"(\d+)p(\d+)\s*mps", re.I)       # e.g. 1p2mps_walk -> 1.2 m/s
# Sagittal-plane angles only: with one side-on camera, hip adduction/rotation are poorly observable
# (out of plane) and are left to ik.mot for anyone who wants them.
JOINTS = [("hip_flexion", "Hip flexion"), ("knee_angle", "Knee flexion"), ("ankle_angle", "Ankle dorsiflexion")]


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def clean(obj):
    """JSON-safe copy: numpy -> python, NaN/inf -> None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def speed_from_name(name: str) -> float | None:
    m = SPEED_IN_NAME.search(name)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._video_info_cache: dict[tuple[str, float], dict] = {}

    # ------------------------------------------------------------------ paths
    def _inside(self, p: Path) -> Path:
        # normalise '..' without following symlinks, so videos symlinked into the data folder still work
        p = Path(os.path.abspath(p))
        if p != self.root and self.root not in p.parents:
            raise NotFound("outside the data folder")
        return p

    def subject_dir(self, sid: str, must_exist: bool = True) -> Path:
        if not ID_RE.match(sid or "") or sid.lower() in RESERVED:
            raise NotFound(f"invalid subject id {sid!r}")
        d = self._inside(self.root / sid)
        if must_exist and not d.is_dir():
            raise NotFound(f"subject {sid} not found")
        return d

    def video_path(self, sid: str, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise NotFound(f"invalid video name {name!r}")
        p = self._inside(self.subject_dir(sid) / name)
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
            raise NotFound(f"video {name} not found")
        return p

    def trial_video(self, sid: str, trial: str) -> Path:
        for v in self._videos(self.subject_dir(sid)):
            if v.stem == trial:
                return v
        raise NotFound(f"trial {trial} not found")

    def results_dir(self, sid: str, trial: str) -> Path:
        if not trial or "/" in trial or "\\" in trial or trial.startswith("."):
            raise NotFound(f"invalid trial {trial!r}")
        return self._inside(self.subject_dir(sid) / "results" / trial)

    def results_file(self, sid: str, trial: str, rel: str) -> Path:
        base = self.results_dir(sid, trial)
        p = self._inside(base / rel)
        if base not in p.parents or not p.is_file():
            raise NotFound(f"file {rel} not found")
        return p

    def intrinsics_path(self, iid: str) -> Path:
        if not iid or not iid.endswith(".json") or ".." in iid:
            raise NotFound(f"invalid intrinsics id {iid!r}")
        p = self._inside(self.root / iid)
        if not p.is_file():
            raise NotFound(f"intrinsics {iid} not found")
        return p

    def new_intrinsics_path(self, name: str) -> tuple[str, Path]:
        if not ID_RE.match(name or ""):
            raise BadRequest("Camera name: letters, digits, '-' and '_' only")
        rel = f"intrinsics/{name}.json"
        return rel, self._inside(self.root / rel)

    # --------------------------------------------------------------- subjects
    def subject_ids(self) -> list[str]:
        out = []
        for d in sorted(self.root.iterdir(), key=lambda p: p.name.lower()):
            if d.is_dir() and ID_RE.match(d.name) and d.name.lower() not in RESERVED:
                out.append(d.name)
        return out

    def meta(self, sid: str) -> dict:
        d = self.subject_dir(sid)
        m = read_json(d / "subject.json", {}) or {}
        m.setdefault("height_m", None)
        m.setdefault("mass_kg", None)
        m.setdefault("notes", "")
        m.setdefault("video_roles", {})
        if "intrinsics" not in m:  # default: the shared data/intrinsics.json if there is one
            m["intrinsics"] = "intrinsics.json" if (self.root / "intrinsics.json").is_file() else None
        return m

    def create_subject(self, sid: str, fields: dict) -> dict:
        if not ID_RE.match(sid or "") or sid.lower() in RESERVED:
            raise BadRequest("Subject ID: up to 64 letters, digits, '-' or '_' (e.g. S02)")
        d = self.subject_dir(sid, must_exist=False)
        if d.exists():
            raise BadRequest(f"Subject {sid} already exists")
        d.mkdir(parents=True)
        return self.update_subject(sid, fields)

    def update_subject(self, sid: str, fields: dict) -> dict:
        d = self.subject_dir(sid)
        m = self.meta(sid)
        for k in ("height_m", "mass_kg"):
            if k in fields:
                v = fields[k]
                if v in (None, ""):
                    m[k] = None
                else:
                    try:
                        m[k] = float(v)
                    except (TypeError, ValueError):
                        raise BadRequest(f"{k} must be a number") from None
        if "notes" in fields:
            m["notes"] = str(fields["notes"] or "")
        if "intrinsics" in fields:
            iid = fields["intrinsics"] or None
            if iid:
                self.intrinsics_path(iid)
            m["intrinsics"] = iid
        if "video_roles" in fields and isinstance(fields["video_roles"], dict):
            for name, role in fields["video_roles"].items():
                if role in ("trial", "checkerboard"):
                    m["video_roles"][name] = role
        (d / "subject.json").write_text(json.dumps(m, indent=2))
        return m

    # ----------------------------------------------------------------- videos
    @staticmethod
    def _videos(d: Path) -> list[Path]:
        return sorted((p for p in d.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT
                       and not p.name.startswith(".")), key=lambda p: p.name.lower())

    def video_info(self, path: Path) -> dict:
        key = (str(path), path.stat().st_mtime)
        if key not in self._video_info_cache:
            from ..io.data import video_info
            try:
                info = video_info(path)
                info["duration_s"] = info["n_frames"] / info["fps"] if info["fps"] else None
            except IOError as e:
                info = {"error": str(e)}
            self._video_info_cache[key] = info
        return dict(self._video_info_cache[key])

    def role(self, meta: dict, name: str) -> str:
        r = meta.get("video_roles", {}).get(name)
        return r or ("checkerboard" if CHECKERBOARD_HINT.search(name) else "trial")

    def upload_target(self, sid: str, filename: str) -> Path:
        """Where an uploaded video goes (sanitised name, must not exist yet)."""
        d = self.subject_dir(sid)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename or "").name).lstrip(".")
        if Path(name).suffix.lower() not in VIDEO_EXT:
            raise BadRequest(f"Not a video file ({', '.join(sorted(VIDEO_EXT))})")
        dest = self._inside(d / name)
        if dest.exists():
            raise BadRequest(f"{name} already exists in {sid}")
        return dest

    # ------------------------------------------------------------ calibration
    def calibration(self, sid: str) -> dict | None:
        p = self.subject_dir(sid) / "calibration.json"
        d = read_json(p)
        if not d:
            return None
        rep = d.get("report", {})
        return clean({
            "rms_px": rep.get("rms_px"), "focal_px": rep.get("focal_px"),
            "focal_estimated": rep.get("focal_estimated"), "camera_height_m": rep.get("camera_height_m"),
            "camera_center_m": rep.get("camera_center_m"),
            "reprojection_error_px": rep.get("reprojection_error_px", {}), "warning": rep.get("warning"),
            "video": Path(d["video"]).name if d.get("video") else None, "frame": d.get("frame", 0),
            "belt_length_m": d.get("belt_length_m"), "belt_width_m": d.get("belt_width_m"),
            "intrinsics": d.get("intrinsics"),
            "landmarks": d.get("landmarks", []), "image_size": d.get("camera", {}).get("image_size"),
            "has_preview": (p.with_suffix(".png")).is_file(),
            "updated": p.stat().st_mtime,
        })

    def save_calibration(self, sid: str, video: str, frame_idx: int, belt_length: float, belt_width: float,
                         landmarks: list[dict], intrinsics: str | None) -> dict:
        import cv2

        from ..calibration import Landmark, belt_corner_world, load_intrinsics, save_calibration, solve_camera
        from ..calibration.annotate import read_frame
        from ..calibration.preview import draw_calibration_preview

        d = self.subject_dir(sid)
        vp = self.video_path(sid, video)
        if not (belt_length > 0 and belt_width > 0):
            raise BadRequest("Belt length and width must be positive (metres)")
        frame = read_frame(str(vp), int(frame_idx))
        h, w = frame.shape[:2]
        world = belt_corner_world(belt_length, belt_width)
        lms = []
        for lm in landmarks:
            name = str(lm.get("name", "")).strip()
            px = lm.get("pixel")
            if not name or not px or len(px) != 2:
                continue
            xyz = world.get(name)
            if xyz is None:
                xyz = lm.get("world")
                if xyz is None or len(xyz) != 3:
                    raise BadRequest(f"Landmark {name}: world position (X, Y, Z) needed")
            lms.append(Landmark(name, np.asarray(xyz, float), np.asarray(px, float)))
        missing = [n for n in world if n not in {lm.name for lm in lms}]
        if missing:
            raise BadRequest("Place all four belt corners (missing: " + ", ".join(missing) + ")")
        K = dist = None
        warnings = []
        if intrinsics:
            K, dist, size = load_intrinsics(self.intrinsics_path(intrinsics))
            if tuple(size) != (w, h):
                if tuple(size) == (h, w):
                    raise BadRequest(f"Intrinsics are for a {size[0]}x{size[1]} image but this video is {w}x{h} "
                                     "(rotated). Record the checkerboard in the same orientation as the trials.")
                warnings.append(f"Intrinsics image size {size[0]}x{size[1]} differs from the video ({w}x{h}).")
        try:
            cam, rep = solve_camera(lms, (w, h), K, dist)
        except (ValueError, np.linalg.LinAlgError) as e:
            raise BadRequest(f"Calibration failed: {e}") from None
        if warnings:
            rep["warning"] = " ".join(warnings + ([rep["warning"]] if rep.get("warning") else []))
        out = d / "calibration.json"
        save_calibration(out, cam, lms, rep, {
            "video": str(vp.relative_to(self.root.parent)) if self.root.parent in vp.parents else str(vp),
            "frame": int(frame_idx), "belt_length_m": belt_length, "belt_width_m": belt_width,
            "intrinsics": intrinsics})
        cv2.imwrite(str(out.with_suffix(".png")), draw_calibration_preview(frame, cam, belt_length, belt_width))
        return self.calibration(sid)

    # -------------------------------------------------------------- intrinsics
    def intrinsics_list(self) -> list[dict]:
        files = []
        if (self.root / "intrinsics.json").is_file():
            files.append(self.root / "intrinsics.json")
        if (self.root / "intrinsics").is_dir():
            files += sorted((self.root / "intrinsics").glob("*.json"))
        out = []
        for p in files:
            d = read_json(p)
            if not d or "K" not in d:
                continue
            K = np.asarray(d["K"], float)
            out.append(clean({
                "id": p.relative_to(self.root).as_posix(), "name": p.stem if p.parent != self.root else "default",
                "fx": K[0, 0], "fy": K[1, 1], "cx": K[0, 2], "cy": K[1, 2], "dist": d.get("dist"),
                "image_size": d.get("image_size"), "rms_px": d.get("rms_px"), "source": d.get("source"),
                "updated": p.stat().st_mtime,
            }))
        return out

    # ------------------------------------------------------------------ trials
    def trial_summary(self, sid: str, trial: str) -> dict:
        rd = self.results_dir(sid, trial)
        s = read_json(rd / "summary.json")
        run = read_json(rd / "run.json", {}) or {}
        out = {"processed": s is not None, "displayed_speed_m_s": run.get("displayed_speed_m_s")}
        if s:
            g = lambda k: (s.get(k) or {}).get("mean")  # noqa: E731
            out.update({
                "processed_at": (rd / "summary.json").stat().st_mtime,
                "belt_speed_m_s": s.get("belt_speed_m_s"), "cadence": s.get("cadence_steps_per_min"),
                "stride_length": g("stride_length"), "stride_time": g("stride_time"),
                "step_width": g("step_width"), "stance_pct": g("stance_pct"),
                "n_strides": sum((s.get("n_strides") or {}).values()),
                "has_opensim": (rd / "opensim" / "ik.mot").is_file(),
            })
        return clean(out)

    def subject(self, sid: str) -> dict:
        d = self.subject_dir(sid)
        m = self.meta(sid)
        videos, trials = [], []
        for v in self._videos(d):
            role = self.role(m, v.name)
            item = {"name": v.name, "stem": v.stem, "role": role, "size": v.stat().st_size,
                    "info": self.video_info(v)}
            videos.append(item)
            if role == "trial":
                trials.append({**item, "id": v.stem, "speed_hint": speed_from_name(v.stem),
                               **self.trial_summary(sid, v.stem)})
        return clean({"id": sid, "meta": m, "videos": videos, "trials": trials,
                      "calibration": self.calibration(sid)})

    def subject_brief(self, sid: str) -> dict:
        s = self.subject(sid)
        t = s["trials"]
        return {"id": sid, "meta": s["meta"], "n_trials": len(t), "n_processed": sum(x["processed"] for x in t),
                "calibrated": s["calibration"] is not None,
                "calibration_rms_px": (s["calibration"] or {}).get("rms_px"),
                "updated": max([d.stat().st_mtime for d in [self.subject_dir(sid)]]
                               + [x.get("processed_at") or 0 for x in t])}

    def results(self, sid: str, trial: str) -> dict:
        rd = self.results_dir(sid, trial)
        summary = read_json(rd / "summary.json")
        if summary is None:
            raise NotFound(f"{trial} has no results yet")
        out = {"summary": summary, "run": read_json(rd / "run.json", {}),
               "refine": read_json(rd / "refine_info.json"),
               "events": read_json(rd / "events.json"),
               "analysis_2d": (read_json(rd / "analysis_2d.json") or {}).get("belt_speed"),
               "scale_factors": read_json(rd / "opensim" / "scale_factors.json"),
               "processed_at": (rd / "summary.json").stat().st_mtime}
        try:
            import pandas as pd
            df = pd.read_csv(rd / "strides.csv")
            out["strides"] = df.to_dict(orient="records")
        except (OSError, ValueError):
            out["strides"] = []
        out["joint_angles"] = self._joint_curves(rd, out["events"])
        kp = rd / "kp2d.npz"
        if kp.is_file():
            with np.load(kp, allow_pickle=True) as z:
                out["video"] = {"n_frames": int(len(z["kp"])), "fps": float(z["fps"]),
                                "image_size": [int(x) for x in z["image_size"]]}
        try:
            vp = self.trial_video(sid, trial)
            out["video_file"] = vp.name
        except NotFound:
            out["video_file"] = None
        out["files"] = sorted(p.relative_to(rd).as_posix() for p in rd.rglob("*")
                              if p.is_file() and not p.name.startswith("."))
        return clean(out)

    @staticmethod
    def _joint_curves(rd: Path, events: dict | None) -> list[dict]:
        mot = rd / "opensim" / "ik.mot"
        if not mot.is_file() or not events:
            return []
        from ..io.data import read_mot
        try:
            df = read_mot(mot)
        except Exception:  # noqa: BLE001
            return []
        curves = []
        for coord, title in JOINTS:
            entry = {"coord": coord, "title": title, "sides": {}}
            for s, suf in (("L", "_l"), ("R", "_r")):
                hs = np.asarray(events.get("hs", {}).get(s, []), float)
                if coord + suf not in df or len(hs) < 2:
                    continue
                y = df[coord + suf].to_numpy(float)
                cyc = []
                for a, b in zip(hs[:-1], hs[1:]):
                    cyc.append(np.interp(np.linspace(a, b, 101), np.arange(len(y)), y))
                cyc = np.array(cyc)
                entry["sides"][s] = {"mean": cyc.mean(0), "sd": cyc.std(0), "n": len(cyc)}
            if entry["sides"]:
                curves.append(entry)
        return curves

    # -------------------------------------------------------------- frames
    def frame_jpeg(self, video: Path, idx: int, max_w: int | None = None, kp2d: Path | None = None,
                   quality: int = 88) -> bytes:
        import cv2

        cap = cv2.VideoCapture(str(video))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        idx = int(min(max(idx, 0), n - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise NotFound(f"could not read frame {idx}")
        if kp2d is not None and kp2d.is_file():
            frame = self._draw_skeleton(frame, kp2d, idx)
        if max_w and frame.shape[1] > max_w:
            s = max_w / frame.shape[1]
            frame = cv2.resize(frame, (max_w, round(frame.shape[0] * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    _kp_cache: dict = {}

    def _draw_skeleton(self, frame, kp2d: Path, idx: int):
        import cv2

        from ..keypoints import BONES, IDX

        key = (str(kp2d), kp2d.stat().st_mtime)
        if key not in self._kp_cache:
            with np.load(kp2d, allow_pickle=True) as z:
                self._kp_cache.clear()
                self._kp_cache[key] = np.array(z["kp"])
        kp = self._kp_cache[key]
        if idx >= len(kp):
            return frame
        img = frame.copy()
        th = max(2, round(max(img.shape[:2]) / 500))
        col = {"L": (214, 120, 42), "R": (52, 104, 235), "C": (200, 200, 200)}   # BGR of #2a78d6 / #eb6834
        side = lambda n: n[0] if n[0] in "LR" and n[1].isupper() else "C"  # noqa: E731
        pts = kp[idx]
        for a, b in BONES:
            pa, pb = pts[IDX[a]], pts[IDX[b]]
            if np.all(np.isfinite(pa[:2])) and np.all(np.isfinite(pb[:2])) and pa[2] > 0.05 and pb[2] > 0.05:
                c = col[side(a)] if side(a) == side(b) else col["C"]
                cv2.line(img, tuple(int(v) for v in pa[:2]), tuple(int(v) for v in pb[:2]), c, th, cv2.LINE_AA)
        for n, i in IDX.items():
            p = pts[i]
            if np.all(np.isfinite(p[:2])) and p[2] > 0.05:
                cv2.circle(img, (int(p[0]), int(p[1])), th + 2, col[side(n)], -1, cv2.LINE_AA)
                cv2.circle(img, (int(p[0]), int(p[1])), th + 2, (255, 255, 255), 1, cv2.LINE_AA)
        return img


def now() -> float:
    return time.time()
