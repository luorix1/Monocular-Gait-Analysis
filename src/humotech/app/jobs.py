"""Background jobs: each job runs a `humotech` CLI command in its own process, one at a time (the GPU
is shared), with output captured to a log file and progress parsed from the pipeline's
"[k/6]" stage lines and tqdm percentages.

Running the CLI as a subprocess (instead of in the web server) keeps a crash, a CUDA error or a
cancel from taking the server down, and captures native-library output (onnxruntime, OpenSim).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

ACTIVE = ("queued", "running")
STAGE_RE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*?)\s*\.*\s*$")
PCT_RE = re.compile(r"(\d{1,3})%\|")
# share of the total run time per pipeline stage (2D pose dominates)
STAGE_WEIGHTS = [0.55, 0.02, 0.03, 0.22, 0.15, 0.03]
PKG_SRC = str(Path(__file__).resolve().parents[2])  # .../src, so the subprocess imports this checkout


@dataclass
class Job:
    id: str
    kind: str                         # pipeline | intrinsics | selftest
    title: str
    argv: list[str]
    meta: dict = field(default_factory=dict)       # subject, trial, out, ...
    status: str = "queued"            # queued | running | done | failed | cancelled | interrupted
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    returncode: int | None = None
    stage: str | None = None
    stage_index: int | None = None
    stage_count: int | None = None
    progress: float | None = None     # 0..1, None = indeterminate
    live: str = ""                    # current tqdm line (not written to the log)
    error: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d.pop("argv")
        return d


class JobManager:
    def __init__(self, root: Path, max_history: int = 300):
        self.dir = Path(root) / ".jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.max_history = max_history
        self._load()
        threading.Thread(target=self._worker, daemon=True, name="humotech-jobs").start()

    # ---------------------------------------------------------------- records
    def _load(self):
        for p in sorted(self.dir.glob("*.json")):
            try:
                j = Job(**json.loads(p.read_text()))
            except (OSError, ValueError, TypeError):
                continue
            if j.status in ACTIVE:   # server stopped while it was queued/running
                j.status, j.live = "interrupted", ""
                j.error = j.error or "The app was stopped before this job finished."
                self._save(j)
            self.jobs[j.id] = j

    def _save(self, j: Job):
        tmp = self.dir / f".{j.id}.json.tmp"
        tmp.write_text(json.dumps(asdict(j), indent=1))
        tmp.replace(self.dir / f"{j.id}.json")

    def log_path(self, jid: str) -> Path:
        return self.dir / f"{jid}.log"

    # -------------------------------------------------------------------- API
    def submit(self, kind: str, title: str, args: list[str], meta: dict | None = None) -> Job:
        argv = [sys.executable, "-m", "humotech.cli", *map(str, args)]
        j = Job(id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], kind=kind, title=title,
                argv=argv, meta=meta or {})
        with self.lock:
            self.jobs[j.id] = j
            self.queue.append(j.id)
            self._save(j)
        self.log_path(j.id).write_text("$ humotech " + " ".join(map(str, args)) + "\n")
        self.wake.set()
        return j

    def list(self) -> list[dict]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)[: self.max_history]
            return [j.public() for j in jobs]

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def tail(self, jid: str, n: int = 400) -> list[str]:
        try:
            with open(self.log_path(jid), errors="replace") as f:
                return list(deque(f, maxlen=n))
        except OSError:
            return []

    def latest_for(self, **meta) -> Job | None:
        with self.lock:
            hits = [j for j in self.jobs.values() if all(j.meta.get(k) == v for k, v in meta.items())]
        return max(hits, key=lambda j: j.created) if hits else None

    def active(self) -> list[Job]:
        with self.lock:
            return [j for j in self.jobs.values() if j.status in ACTIVE]

    def cancel(self, jid: str) -> Job | None:
        with self.lock:
            j = self.jobs.get(jid)
            if j is None:
                return None
            if j.status == "queued":
                try:
                    self.queue.remove(jid)
                except ValueError:
                    pass
                j.status, j.finished = "cancelled", time.time()
                self._save(j)
                return j
            proc = self.proc if j.status == "running" else None
            if proc is not None:
                j.meta["cancel_requested"] = True
        if proc is not None:
            _terminate(proc)
        return j

    # ----------------------------------------------------------------- worker
    def _worker(self):
        while True:
            self.wake.wait(timeout=1.0)
            self.wake.clear()
            while True:
                with self.lock:
                    if not self.queue:
                        break
                    j = self.jobs[self.queue.popleft()]
                    j.status, j.started = "running", time.time()
                    self._save(j)
                try:
                    self._run(j)
                except Exception as e:  # noqa: BLE001  (never let the worker die)
                    j.status, j.error = "failed", f"{type(e).__name__}: {e}"
                j.finished, j.live = time.time(), ""
                with self.lock:
                    self.proc = None
                    self._save(j)

    def _run(self, j: Job):
        env = {**os.environ, "PYTHONUNBUFFERED": "1",
               "PYTHONPATH": PKG_SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
        env.pop("MPLBACKEND", None)
        with open(self.log_path(j.id), "a", buffering=1, errors="replace") as log:
            proc = subprocess.Popen(j.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                    cwd=str(self.dir),  # stray files (e.g. opensim.log) land in .jobs/
                                    start_new_session=(os.name != "nt"))
            with self.lock:
                self.proc = proc
            tail: deque[str] = deque(maxlen=12)
            buf = ""
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                parts = re.split(r"(\r\n|\n|\r)", buf)
                buf = parts.pop()  # incomplete remainder
                for text, sep in zip(parts[0::2], parts[1::2]):
                    if sep == "\r":           # tqdm redraw: show live, don't log
                        j.live = text.strip()
                        self._progress_from_pct(j, text)
                        continue
                    if text.strip():
                        log.write(text + "\n")
                        tail.append(text)
                        self._parse_line(j, text)
            if buf.strip():
                log.write(buf + "\n")
                tail.append(buf)
            j.returncode = proc.wait()
        if j.meta.get("cancel_requested"):
            j.status, j.error = "cancelled", "Cancelled by the user."
        elif j.returncode == 0:
            j.status, j.progress = "done", 1.0
        else:
            j.status = "failed"
            j.error = _error_summary(list(tail)) or f"exited with code {j.returncode}"

    def _parse_line(self, j: Job, line: str):
        m = STAGE_RE.match(line.strip())
        if m:
            k, n = int(m.group(1)), int(m.group(2))
            j.stage_index, j.stage_count, j.stage = k, n, m.group(3)
            if n == len(STAGE_WEIGHTS):
                j.progress = sum(STAGE_WEIGHTS[: k - 1])
            else:
                j.progress = (k - 1) / n
            with self.lock:
                self._save(j)
        else:
            self._progress_from_pct(j, line)

    @staticmethod
    def _progress_from_pct(j: Job, text: str):
        m = PCT_RE.search(text)
        if not m:
            return
        f = min(int(m.group(1)), 100) / 100
        if j.stage_index and j.stage_count == len(STAGE_WEIGHTS):
            k = j.stage_index
            j.progress = sum(STAGE_WEIGHTS[: k - 1]) + STAGE_WEIGHTS[k - 1] * f
        elif j.kind != "pipeline":
            j.progress = f


def _terminate(proc: subprocess.Popen):
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError):
        return

    def _kill_later():
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL) if os.name != "nt" else proc.kill()
            except (ProcessLookupError, PermissionError):
                pass
    threading.Thread(target=_kill_later, daemon=True).start()


def _error_summary(lines: list[str]) -> str | None:
    """Last meaningful line of a failed run (the exception message, usually)."""
    for ln in reversed(lines):
        s = ln.strip()
        if s and not s.startswith(("File ", "^", "~", "Traceback")):
            return s[:500]
    return None
