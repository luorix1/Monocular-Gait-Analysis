"""Web app (`humotech app`): API, workspace safety, calibration, results, job runner.

Skipped when the app extra (fastapi) or httpx (TestClient) is missing.
"""
import json
import sys
import time

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
cv2 = pytest.importorskip("cv2")

from fastapi.testclient import TestClient  # noqa: E402

from humotech.app.jobs import STAGE_WEIGHTS, Job, JobManager  # noqa: E402
from humotech.app.server import create_app  # noqa: E402


def _write_video(path, size=(320, 240), n=5, fps=30):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for i in range(n):
        w.write(np.full((size[1], size[0], 3), 40 * i % 255, np.uint8))
    w.release()


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "data")
    submitted = []
    # never launch real pipeline subprocesses from the API tests
    app.state.jobs.submit = lambda kind, title, args, meta=None: submitted.append((kind, args, meta)) or Job(
        id=f"j{len(submitted)}", kind=kind, title=title, argv=[], meta=meta or {})
    c = TestClient(app)
    c.submitted = submitted
    c.root = tmp_path / "data"
    return c


def test_subjects_and_validation(client):
    assert client.get("/api/overview").json()["subjects"] == []
    assert client.post("/api/subjects", json={"id": "../evil"}).status_code == 400
    assert client.post("/api/subjects", json={"id": "results"}).status_code == 400
    r = client.post("/api/subjects", json={"id": "S02", "height_m": "1.7", "mass_kg": 65})
    assert r.status_code == 200 and r.json()["meta"]["height_m"] == 1.7
    assert client.post("/api/subjects", json={"id": "S02"}).status_code == 400          # duplicate
    assert client.patch("/api/subjects/S02", json={"mass_kg": "abc"}).status_code == 400
    assert client.get("/api/subjects/nope").status_code == 404


def test_upload_roles_frames_and_traversal(client, tmp_path):
    client.post("/api/subjects", json={"id": "S01"})
    src = tmp_path / "walk.avi"
    _write_video(src)
    r = client.put("/api/subjects/S01/videos/1p2mps walk.avi", content=src.read_bytes())
    assert r.status_code == 200 and r.json()["name"] == "1p2mps_walk.avi"            # sanitised
    assert client.put("/api/subjects/S01/videos/1p2mps_walk.avi", content=b"x").status_code == 400
    assert client.put("/api/subjects/S01/videos/notes.txt", content=b"x").status_code == 400
    _write_video(client.root / "S01" / "intrinsic_board.avi")
    s = client.get("/api/subjects/S01").json()
    roles = {v["name"]: v["role"] for v in s["videos"]}
    assert roles == {"1p2mps_walk.avi": "trial", "intrinsic_board.avi": "checkerboard"}
    t = s["trials"][0]
    assert t["speed_hint"] == 1.2 and t["info"]["n_frames"] == 5 and not t["processed"]
    f = client.get("/api/subjects/S01/videos/1p2mps_walk.avi/frame?idx=2")
    assert f.status_code == 200 and f.content[:2] == b"\xff\xd8"
    for bad in ["/api/subjects/S01/videos/..%2F..%2Fsecret.avi/frame",
                "/api/subjects/S01/trials/x/files/../../../subject.json",
                "/api/subjects/S01/trials/1p2mps_walk/files/%2Fetc%2Fpasswd"]:
        assert client.get(bad).status_code == 404, bad


def test_calibration_roundtrip(client, session):
    """Clicked pixels of the synthetic belt corners -> same camera as the CLI solver."""
    client.post("/api/subjects", json={"id": "S01"})
    W, H = session.cam.image_size
    _write_video(client.root / "S01" / "trial.avi", size=(W, H), n=2)
    lms = [{"name": lm.name, "pixel": lm.pixel.tolist(), "world": lm.world.tolist()} for lm in session.landmarks]
    corners = {lm.name: lm.world for lm in session.landmarks if lm.name.startswith("belt_")}
    L = float(corners["belt_front_left"][0] * 2)
    Wb = float(-corners["belt_front_left"][2] * 2)
    r = client.post("/api/subjects/S01/calibration", json={"video": "trial.avi", "frame": 0, "belt_length_m": L,
                                                          "belt_width_m": Wb, "landmarks": lms[:3]})
    assert r.status_code == 400 and "missing" in r.json()["detail"]
    r = client.post("/api/subjects/S01/calibration", json={"video": "trial.avi", "frame": 0, "belt_length_m": L,
                                                          "belt_width_m": Wb, "landmarks": lms})
    assert r.status_code == 200, r.text
    cal = r.json()
    assert cal["rms_px"] < 1.0 and abs(cal["camera_height_m"] - session.cam.center[1]) < 0.05
    assert (client.root / "S01" / "calibration.png").is_file()
    assert client.get("/api/subjects/S01/calibration.png").status_code == 200


def test_process_requires_calibration_and_body_size(client):
    client.post("/api/subjects", json={"id": "S01"})
    _write_video(client.root / "S01" / "t1.avi")
    body = {"trials": ["t1"], "settings": {"pose2d": {"device": "cpu"}}}
    assert "Calibrate" in client.post("/api/subjects/S01/process", json=body).json()["detail"]
    (client.root / "S01" / "calibration.json").write_text("{}")
    assert "height" in client.post("/api/subjects/S01/process", json=body).json()["detail"]
    client.patch("/api/subjects/S01", json={"height_m": 1.8, "mass_kg": 75})
    bad = {**body, "settings": {"belt_speed": {"source": "known"}}}
    assert "treadmill speed" in client.post("/api/subjects/S01/process", json=bad).json()["detail"]
    r = client.post("/api/subjects/S01/process", json={**body, "displayed_speeds": {"t1": 1.1}, "force": True,
                                                        "advanced_yaml": "refine:\n  iters: 5"})
    assert r.status_code == 200 and len(r.json()["submitted"]) == 1
    kind, args, meta = client.submitted[-1]
    assert kind == "pipeline" and meta == {"subject": "S01", "trial": "t1"} and "--force" in args
    import yaml
    cfg = yaml.safe_load((client.root / "S01" / "results" / "t1" / "run_config.yaml").read_text())
    assert cfg["subject"] == {"height_m": 1.8, "mass_kg": 75.0} and cfg["refine"]["iters"] == 5
    assert json.loads((client.root / "S01" / "results" / "t1" / "run.json").read_text())["displayed_speed_m_s"] == 1.1


def test_results_payload(client):
    import pandas as pd

    from humotech.io.data import write_mot
    client.post("/api/subjects", json={"id": "S01"})
    _write_video(client.root / "S01" / "t1.avi")
    rd = client.root / "S01" / "results" / "t1"
    (rd / "opensim").mkdir(parents=True)
    (rd / "summary.json").write_text(json.dumps({"belt_speed_m_s": 1.2, "n_strides": {"L": 2, "R": 1},
                                                 "stride_time": {"mean": 1.1, "sd": float("nan"), "L": 1.1, "R": 1.1}}))
    pd.DataFrame({"side": ["L", "R"], "t_hs": [0.1, 0.6], "stride_time": [1.1, None]}).to_csv(rd / "strides.csv", index=False)
    (rd / "events.json").write_text(json.dumps({"fps": 10, "hs": {"L": [0, 10, 20], "R": [5, 15]}, "to": {"L": [], "R": []}}))
    t = np.arange(30) / 10
    write_mot(rd / "opensim" / "ik.mot", pd.DataFrame({"time": t, "knee_angle_l": 10 * t, "knee_angle_r": t}))
    r = client.get("/api/subjects/S01/trials/t1/results")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["stride_time"]["sd"] is None                         # NaN -> null
    assert d["strides"][1]["stride_time"] is None
    knee = next(j for j in d["joint_angles"] if j["coord"] == "knee_angle")
    assert knee["sides"]["L"]["n"] == 2 and len(knee["sides"]["L"]["mean"]) == 101
    assert "opensim/ik.mot" in d["files"]
    assert client.get("/api/subjects/S01/trials/t1/files/summary.json?download=1").status_code == 200
    s = client.get("/api/subjects/S01").json()["trials"][0]
    assert s["processed"] and s["has_opensim"] and s["n_strides"] == 3


def test_latest_for_matches_kind_and_meta(tmp_path):
    jm = JobManager(tmp_path)
    a = Job(id="a", kind="pipeline", title="", argv=[], meta={"subject": "S01", "trial": "t1"}, created=1)
    b = Job(id="b", kind="pipeline", title="", argv=[], meta={"subject": "S01", "trial": "t1"}, created=2)
    c = Job(id="c", kind="intrinsics", title="", argv=[], meta={"subject": "S01", "trial": "t1"}, created=3)
    jm.jobs.update({j.id: j for j in (a, b, c)})
    assert jm.latest_for(kind="pipeline", subject="S01", trial="t1") is b
    assert jm.latest_for(kind="pipeline", subject="S01", trial="t2") is None
    assert jm.latest_for(subject="S01", trial="t1") is c


def test_trial_shows_queued_job_and_blocks_duplicates(tmp_path):
    """The subject view reports a trial's queued job, and the same trial can't be queued twice."""
    client = TestClient(create_app(tmp_path / "data", start_worker=False))   # real submit, jobs stay queued
    root = tmp_path / "data"
    client.post("/api/subjects", json={"id": "S01", "height_m": 1.8, "mass_kg": 75})
    _write_video(root / "S01" / "t1.avi")
    (root / "S01" / "calibration.json").write_text("{}")
    r = client.post("/api/subjects/S01/process", json={"trials": ["t1"]})
    assert len(r.json()["submitted"]) == 1
    t = client.get("/api/subjects/S01").json()["trials"][0]
    assert t["job"] and t["job"]["status"] == "queued"
    r2 = client.post("/api/subjects/S01/process", json={"trials": ["t1"]}).json()
    assert r2["submitted"] == [] and r2["skipped"][0]["trial"] == "t1"


def test_job_progress_parsing(tmp_path):
    jm = JobManager(tmp_path)
    j = Job(id="x", kind="pipeline", title="t", argv=[])
    jm._parse_line(j, "[4/6] treadmill-constrained refinement ...")
    assert j.stage_index == 4 and j.stage == "treadmill-constrained refinement"
    assert j.progress == pytest.approx(sum(STAGE_WEIGHTS[:3]))
    j2 = Job(id="y", kind="pipeline", title="t", argv=[])
    jm._parse_line(j2, "[1/6] 2D pose with rtmlib ...")
    jm._progress_from_pct(j2, "2D pose (rtmlib):  50%|#####     | 1800/3600")
    assert j2.progress == pytest.approx(STAGE_WEIGHTS[0] / 2)


def test_job_runner_real_subprocess(tmp_path):
    """A real CLI subprocess: output captured, status recorded, survives a manager restart."""
    jm = JobManager(tmp_path)
    j = jm.submit("selftest", "check", ["check"])
    for _ in range(300):
        if jm.get(j.id).status not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert jm.get(j.id).status == "done", jm.tail(j.id)
    assert any("numpy" in ln for ln in jm.tail(j.id))
    j2 = JobManager(tmp_path).get(j.id)
    assert j2 is not None and j2.status == "done"
    assert sys.executable in jm.get(j.id).argv[0]
