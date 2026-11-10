"""FastAPI server for the HumoTech web app. Start with `humotech app` (see cli.py)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .jobs import JobManager
from .workspace import BadRequest, NotFound, Workspace, clean, now

STATIC = Path(__file__).parent / "static"


def _deep_update(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_update(a[k], v)
        else:
            a[k] = v
    return a


def create_app(data_root: str | Path) -> FastAPI:
    ws = Workspace(data_root)
    jobs = JobManager(ws.root)
    app = FastAPI(title="HumoTech", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.ws, app.state.jobs = ws, jobs
    sys_cache: dict = {}

    @app.exception_handler(NotFound)
    async def _nf(_req, e):
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(BadRequest)
    async def _br(_req, e):
        return JSONResponse({"detail": str(e)}, status_code=400)

    def with_jobs(sid: str, subj: dict) -> dict:
        for t in subj["trials"]:
            j = jobs.latest_for(kind="pipeline", subject=sid, trial=t["id"])
            t["job"] = j.public() if j else None
        return subj

    # ------------------------------------------------------------- overview
    @app.get("/api/overview")
    def overview():
        return clean({"data_root": str(ws.root), "version": __version__,
                      "subjects": [ws.subject_brief(s) for s in ws.subject_ids()],
                      "intrinsics": ws.intrinsics_list(),
                      "active_jobs": [j.public() for j in jobs.active()]})

    @app.get("/api/config/default")
    def default_config():
        from ..pipeline import load_config
        return clean(load_config())

    # ------------------------------------------------------------- subjects
    @app.post("/api/subjects")
    def create_subject(body: dict = Body(...)):
        sid = str(body.get("id", "")).strip()
        ws.create_subject(sid, body)
        return with_jobs(sid, ws.subject(sid))

    @app.get("/api/subjects/{sid}")
    def get_subject(sid: str):
        return with_jobs(sid, ws.subject(sid))

    @app.patch("/api/subjects/{sid}")
    def update_subject(sid: str, body: dict = Body(...)):
        ws.update_subject(sid, body)
        return with_jobs(sid, ws.subject(sid))

    @app.put("/api/subjects/{sid}/videos/{name}")
    async def upload_video(sid: str, name: str, request: Request):
        """Raw-body upload: the browser streams the file, written to a temp file then renamed."""
        dest = ws.upload_target(sid, name)
        tmp = dest.with_name(f".{dest.name}.part")
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
            if tmp.stat().st_size == 0:
                raise BadRequest("Empty upload")
            tmp.rename(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return {"name": dest.name}

    @app.get("/api/subjects/{sid}/videos/{name}/frame")
    def video_frame(sid: str, name: str, idx: int = 0, max_w: int | None = None):
        jpg = ws.frame_jpeg(ws.video_path(sid, name), idx, max_w)
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    # ---------------------------------------------------------- calibration
    @app.post("/api/subjects/{sid}/calibration")
    def calibrate(sid: str, body: dict = Body(...)):
        try:
            L, W = float(body["belt_length_m"]), float(body["belt_width_m"])
        except (KeyError, TypeError, ValueError):
            raise BadRequest("Belt length and width (m) are required") from None
        meta = ws.meta(sid)
        intr = body.get("intrinsics", meta.get("intrinsics"))
        cal = ws.save_calibration(sid, str(body.get("video", "")), int(body.get("frame", 0)), L, W,
                                  body.get("landmarks") or [], intr or None)
        if intr != meta.get("intrinsics"):
            ws.update_subject(sid, {"intrinsics": intr})
        return cal

    @app.get("/api/subjects/{sid}/calibration.png")
    def calibration_png(sid: str):
        p = ws.subject_dir(sid) / "calibration.png"
        if not p.is_file():
            raise NotFound("no calibration preview")
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ processing
    @app.post("/api/subjects/{sid}/process")
    def process(sid: str, body: dict = Body(...)):
        d = ws.subject_dir(sid)
        meta = ws.meta(sid)
        calib = d / "calibration.json"
        if not calib.is_file():
            raise BadRequest("Calibrate the belt for this subject first")
        if not meta.get("height_m") or not meta.get("mass_kg"):
            raise BadRequest("Set the subject's height and mass first (used to scale the OpenSim model)")
        settings = body.get("settings") or {}
        if isinstance(settings, str):
            settings = yaml.safe_load(settings) or {}
        if not isinstance(settings, dict):
            raise BadRequest("settings must be a mapping")
        advanced = body.get("advanced_yaml") or ""
        if advanced.strip():
            try:
                adv = yaml.safe_load(advanced)
            except yaml.YAMLError as e:
                raise BadRequest(f"Advanced settings are not valid YAML: {e}") from None
            if not isinstance(adv, dict):
                raise BadRequest("Advanced settings must be a YAML mapping")
            _deep_update(settings, adv)
        speeds = body.get("displayed_speeds") or {}
        submitted, skipped = [], []
        for tid in body.get("trials") or []:
            vp = ws.trial_video(sid, tid)
            prev = jobs.latest_for(kind="pipeline", subject=sid, trial=tid)
            if prev and prev.status in ("queued", "running"):
                skipped.append({"trial": tid, "reason": "already queued or running"})
                continue
            rd = ws.results_dir(sid, tid)
            rd.mkdir(parents=True, exist_ok=True)
            cfg = json.loads(json.dumps(settings))
            _deep_update(cfg, {"subject": {"height_m": meta["height_m"], "mass_kg": meta["mass_kg"]}})
            shown = speeds.get(tid)
            shown = float(shown) if shown not in (None, "") else None
            bs = cfg.setdefault("belt_speed", {})
            if bs.get("source") == "known" and bs.get("known_m_s") in (None, ""):
                if shown is None:
                    raise BadRequest(f"{tid}: belt speed source is 'known' but no treadmill speed was given")
                bs["known_m_s"] = shown
            (rd / "run_config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
            (rd / "run.json").write_text(json.dumps({"submitted": now(), "displayed_speed_m_s": shown,
                                                     "settings": cfg, "force": bool(body.get("force"))},
                                                    indent=2))
            args = ["run", "--video", vp, "--calib", calib, "--config", rd / "run_config.yaml", "--out", rd]
            if body.get("force"):
                args.append("--force")
            j = jobs.submit("pipeline", f"{sid} / {tid}", args, {"subject": sid, "trial": tid})
            submitted.append(j.public())
        return {"submitted": submitted, "skipped": skipped}

    @app.get("/api/subjects/{sid}/trials/{tid}/results")
    def results(sid: str, tid: str):
        r = ws.results(sid, tid)
        j = jobs.latest_for(kind="pipeline", subject=sid, trial=tid)
        r["job"] = j.public() if j else None
        return r

    @app.get("/api/subjects/{sid}/trials/{tid}/files/{rel:path}")
    def result_file(sid: str, tid: str, rel: str, download: bool = False):
        p = ws.results_file(sid, tid, rel)
        return FileResponse(p, filename=p.name if download else None, headers={"Cache-Control": "no-cache"},
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/subjects/{sid}/trials/{tid}/frame")
    def trial_frame(sid: str, tid: str, idx: int = 0, max_w: int | None = 1280, overlay: bool = True):
        vp = ws.trial_video(sid, tid)
        kp = ws.results_dir(sid, tid) / "kp2d.npz" if overlay else None
        return Response(ws.frame_jpeg(vp, idx, max_w, kp, quality=82), media_type="image/jpeg")

    # ------------------------------------------------------------ intrinsics
    @app.get("/api/intrinsics")
    def intrinsics():
        return ws.intrinsics_list()

    @app.post("/api/intrinsics")
    def new_intrinsics(body: dict = Body(...)):
        rel, out = ws.new_intrinsics_path(str(body.get("name", "")).strip())
        if out.exists() and not body.get("overwrite"):
            raise BadRequest(f"A camera named {out.stem} already exists")
        vp = ws.video_path(str(body.get("subject", "")), str(body.get("video", "")))
        try:
            cols, rows = int(body["cols"]), int(body["rows"])
            square = float(body["square_m"])
            step = int(body.get("step", 20))
        except (KeyError, TypeError, ValueError):
            raise BadRequest("Board columns, rows and square size are required") from None
        if cols < 2 or rows < 2 or square <= 0 or step < 1:
            raise BadRequest("Check the board size, square size and frame step")
        out.parent.mkdir(parents=True, exist_ok=True)
        j = jobs.submit("intrinsics", f"Camera intrinsics: {out.stem}",
                        ["intrinsics", vp, "--board", f"{cols}x{rows}", "--square", square, "--step", step,
                         "--out", out],
                        {"intrinsics": rel, "subject": body.get("subject"), "video": vp.name})
        return j.public()

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list()

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, tail: int = 400):
        j = jobs.get(jid)
        if j is None:
            raise NotFound("job not found")
        return {**j.public(), "log": jobs.tail(jid, max(1, min(tail, 5000)))}

    @app.get("/api/jobs/{jid}/log")
    def job_log(jid: str):
        p = jobs.log_path(jid)
        if not p.is_file():
            raise NotFound("log not found")
        return FileResponse(p, media_type="text/plain", filename=f"humotech-{jid}.log")

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        j = jobs.cancel(jid)
        if j is None:
            raise NotFound("job not found")
        return j.public()

    @app.post("/api/selftest")
    def selftest():
        return jobs.submit("selftest", "Self-test on synthetic data",
                           ["synth", "--run", "--out", ws.root / ".jobs" / "selftest"]).public()

    # ---------------------------------------------------------------- system
    @app.get("/api/system")
    def system(refresh: bool = False):
        if sys_cache and not refresh and time.time() - sys_cache["t"] < 60:
            return sys_cache["v"]
        pkgs, header = [], ""
        try:
            r = subprocess.run([sys.executable, "-m", "humotech.cli", "check"], capture_output=True, text=True,
                               timeout=120, env=_child_env())
            for ln in r.stdout.splitlines():
                m = re.match(r"\s*\[(ok|missing)\]\s+(\S+)\s*(.*)", ln)
                if m:
                    pkgs.append({"name": m.group(2), "ok": m.group(1) == "ok", "detail": m.group(3).strip()})
                elif ln.strip():
                    header = ln.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            header = f"check failed: {e}"
        gpus = []
        if shutil.which("nvidia-smi"):
            try:
                r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,"
                                    "utilization.gpu", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=10)
                for ln in r.stdout.strip().splitlines():
                    f = [x.strip() for x in ln.split(",")]
                    if len(f) == 5:
                        gpus.append({"name": f[0], "driver": f[1], "mem_used_mb": _num(f[2]),
                                     "mem_total_mb": _num(f[3]), "util_pct": _num(f[4])})
            except (OSError, subprocess.TimeoutExpired):
                pass
        v = {"python": header, "packages": pkgs, "gpus": gpus, "data_root": str(ws.root),
             "executable": sys.executable, "checked": time.time()}
        sys_cache.update(t=time.time(), v=v)
        return v

    # ---------------------------------------------------------------- static
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


def _child_env():
    import os

    from .jobs import PKG_SRC
    return {**os.environ, "PYTHONPATH": PKG_SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
