import { api, uploadFile } from "../api.js";
import { h, clear, icon, fmt, modal, field, select, seg, card, crumbs, emptyState, jobBadge, progressBar,
  rmsBadge, toast, store } from "../ui.js";
import { newSubjectDialog } from "./subjects.js";

const ACTIVE = ["queued", "running"];

export async function render(view, [sid], ctx) {
  const state = { selected: new Set(), subject: null, intrinsics: [] };
  const root = h("div");
  view.append(root);

  async function load() {
    const [s, o] = await Promise.all([api.get(`/api/subjects/${api.enc(sid)}`), api.get("/api/intrinsics")]);
    state.subject = s; state.intrinsics = o;
    for (const id of [...state.selected]) if (!s.trials.some((t) => t.id === id)) state.selected.delete(id);
    draw();
  }

  function draw() {
    const s = state.subject;
    clear(root).append(
      crumbs({ label: "Subjects", href: "#/" }, { label: s.id }),
      header(s, state, load),
      steps(s, state, load),
      trialsCard(s, state, load, ctx),
      h("div", { class: "grid-2", style: { marginTop: "18px" } }, calibrationCard(s), videosCard(s, load)));
  }

  // live job status: re-fetch on status changes, patch progress in place otherwise
  let sig = "";
  ctx.onJobs((jobs) => {
    const mine = jobs.filter((j) => j.kind === "pipeline" && j.meta?.subject === sid);
    const nsig = mine.map((j) => `${j.id}:${j.status}`).join("|");
    if (sig && nsig !== sig) load();
    else for (const j of mine.filter((j) => j.status === "running")) {
      const cell = root.querySelector(`[data-trial-status="${CSS.escape(j.meta.trial)}"]`);
      if (cell) clear(cell).append(statusCell({ job: j, processed: false }));
    }
    sig = nsig;
  });
  await load();
}

// ------------------------------------------------------------------ header
function header(s, state, reload) {
  const m = s.meta;
  const bits = [];
  bits.push(h("span", {}, icon("users", 14), " ", m.height_m ? `${fmt.n(m.height_m, 2)} m` : "height not set", " · ",
    m.mass_kg ? `${fmt.n(m.mass_kg, 1)} kg` : "mass not set"));
  if (m.notes) bits.push(h("span", { class: "muted" }, m.notes));
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, s.id), h("div", { class: "sub" }, bits)),
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: () => newSubjectDialog(state.intrinsics, s) }, icon("edit", 15), "Edit details"),
      uploadButton(s, reload)));
}

// ------------------------------------------------------------------- steps
function steps(s, state, reload) {
  const m = s.meta, cal = s.calibration;
  const intr = state.intrinsics.find((i) => i.id === m.intrinsics);
  const nT = s.trials.length, nP = s.trials.filter((t) => t.processed).length;
  const pending = s.trials.filter((t) => !t.processed && !(t.job && ACTIVE.includes(t.job.status)));
  const nActive = s.trials.filter((t) => t.job && ACTIVE.includes(t.job.status)).length;
  const detailsOk = m.height_m && m.mass_kg;
  const step = (n, cls, top, title, detail, btn) => h("div", { class: `card step ${cls}` },
    h("div", { class: "step-top" }, h("span", { class: "step-icon" }, cls === "done" ? icon("check", 13) : cls === "warn" ? "!" : n), top),
    h("div", { class: "step-title" }, title), h("div", { class: "step-detail" }, detail), btn);
  const calBtn = h("a", { class: `btn sm${cal ? "" : " primary"}`, href: `#/s/${encodeURIComponent(s.id)}/calibrate` },
    icon("target", 14), cal ? "Recalibrate" : "Calibrate belt");
  const procBtn = h("button", { class: `btn sm${cal && detailsOk && pending.length ? " primary" : ""}`,
    disabled: !cal || !detailsOk || !pending.length, onclick: () => runDialog(s, pending.map((t) => t.id)) },
  icon("play", 13), pending.length ? `Process ${pending.length} remaining` : nActive ? `Processing ${nActive}…` : "All processed");
  return h("div", { class: "steps", style: { marginBottom: "22px" } },
    step(1, detailsOk ? "done" : "todo", "Step 1", "Subject details",
      detailsOk ? `${fmt.n(m.height_m, 2)} m · ${fmt.n(m.mass_kg, 1)} kg` : "Height and mass are needed",
      detailsOk ? null : h("button", { class: "btn sm primary", onclick: () => newSubjectDialog(state.intrinsics, s) }, "Add details")),
    step(2, intr ? "done" : "warn", "Step 2", "Camera intrinsics",
      intr ? h("span", {}, `${intr.name} · `, rmsBadge(intr.rms_px, 0.5, 1)) : "None: focal length estimated from the belt (less accurate)",
      h("a", { class: "btn sm", href: "#/cameras" }, icon("camera", 14), intr ? "Cameras" : "Calibrate camera")),
    step(3, cal ? (cal.rms_px > 2.5 ? "warn" : "done") : "todo", "Step 3", "Belt calibration",
      cal ? h("span", {}, "Reprojection ", rmsBadge(cal.rms_px)) : "Click the four belt corners on a frame", calBtn),
    step(4, nT && nP === nT ? "done" : "todo", "Step 4", "Process trials",
      nT ? `${nP} of ${nT} processed` : "Upload trial videos first", procBtn));
}

// ------------------------------------------------------------------- trials
function trialsCard(s, state, reload, ctx) {
  const sel = state.selected;
  const can = !!s.calibration && s.meta.height_m && s.meta.mass_kg;
  const procSel = h("button", { class: "btn sm primary", disabled: !sel.size || !can, onclick: () => runDialog(s, [...sel]) },
    icon("play", 13), sel.size ? `Process ${sel.size} selected` : "Process selected");
  const syncSel = () => { procSel.disabled = !sel.size || !can; procSel.lastChild.textContent = sel.size ? `Process ${sel.size} selected` : "Process selected"; };

  if (!s.trials.length) {
    return card("Trials", null, null, h("div", { class: "card-body" },
      emptyState("video", "No trial videos yet", "Drop the treadmill videos here. Checkerboard videos (name contains “intrinsic” or “checker”) are kept separate."),
      dropzone(s, reload)));
  }
  const all = h("input", { type: "checkbox", "aria-label": "Select all", checked: sel.size === s.trials.length,
    onchange: (e) => { s.trials.forEach((t) => (e.target.checked ? sel.add(t.id) : sel.delete(t.id))); tbody.querySelectorAll("input[type=checkbox]").forEach((c) => (c.checked = e.target.checked)); syncSel(); } });
  const tbody = h("tbody");
  for (const t of s.trials) {
    const href = `#/s/${encodeURIComponent(s.id)}/t/${encodeURIComponent(t.id)}`;
    const cb = h("input", { type: "checkbox", checked: sel.has(t.id), "aria-label": `Select ${t.id}`,
      onclick: (e) => e.stopPropagation(),
      onchange: (e) => { e.target.checked ? sel.add(t.id) : sel.delete(t.id); all.checked = sel.size === s.trials.length; syncSel(); } });
    const shown = t.displayed_speed_m_s ?? t.speed_hint;
    const diff = t.processed && shown ? (100 * (t.belt_speed_m_s - shown)) / shown : null;
    tbody.append(h("tr", { class: t.processed ? "click" : "", onclick: () => { if (t.processed) location.hash = href; } },
      h("td", { style: { width: "36px" } }, cb),
      h("td", {}, h("div", { class: "cell-main" }, t.id),
        h("div", { class: "cell-sub nowrap", title: `${t.name} · ${fmt.bytes(t.size)}` }, t.info?.error ? t.info.error
          : `${fmt.dur(t.info?.duration_s)} · ${Math.round(t.info?.fps || 0)} fps · ${t.info?.width}×${t.info?.height}`)),
      h("td", { "data-trial-status": t.id }, statusCell(t)),
      h("td", { class: "num" }, shown ? `${fmt.n(shown, 2)}` : h("span", { class: "muted" }, "–")),
      h("td", { class: "num" }, t.processed ? h("span", {}, fmt.n(t.belt_speed_m_s, 2),
        diff !== null ? h("span", { class: "cell-sub" }, ` (${diff >= 0 ? "+" : ""}${diff.toFixed(1)}%)`) : null) : "–"),
      h("td", { class: "num" }, t.processed ? fmt.n(t.cadence, 1) : "–"),
      h("td", { class: "num" }, t.processed ? fmt.n(t.stride_length, 2) : "–"),
      h("td", { class: "num" }, t.processed ? fmt.n(t.stance_pct, 1) : "–"),
      h("td", { class: "num nowrap" }, t.processed
        ? h("a", { class: "btn sm icon", href, title: "Open results", "aria-label": `Open results for ${t.id}`, onclick: (e) => e.stopPropagation() }, icon("chevron", 14))
        : t.job && ACTIVE.includes(t.job.status)
          ? h("a", { class: "btn sm", href: `#/jobs/${t.job.id}`, onclick: (e) => e.stopPropagation() }, "Log")
          : h("button", { class: "btn sm", disabled: !can, onclick: (e) => { e.stopPropagation(); runDialog(s, [t.id]); } }, icon("play", 12), "Process"))));
  }
  return card("Trials", `${s.trials.length} video${s.trials.length === 1 ? "" : "s"}`, [procSel],
    !can ? h("div", { class: "card-body", style: { paddingBottom: 0 } }, h("div", { class: "banner warn" }, icon("alert", 16),
      h("div", { class: "grow" }, !s.calibration ? "Calibrate the belt (step 3) before processing." : "Add the subject's height and mass (step 1) before processing."))) : null,
    h("div", { class: "table-wrap" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, all), h("th", {}, "Trial"), h("th", {}, "Status"),
        h("th", { class: "num", title: "Speed shown on the treadmill (from the file name or entered when processing)" }, "Treadmill m/s"),
        h("th", { class: "num", title: "Belt speed estimated from the stance foot (difference to the treadmill speed)" }, "Estimated m/s"),
        h("th", { class: "num" }, "Cadence"), h("th", { class: "num" }, "Stride m"), h("th", { class: "num" }, "Stance %"),
        h("th", {}))),
      tbody)),
    h("div", { class: "card-body" }, dropzone(s, reload)));
}

function statusCell(t) {
  const j = t.job;
  if (j && ACTIVE.includes(j.status)) {
    return h("div", { style: { display: "grid", gap: "5px", minWidth: "150px" } },
      h("div", { class: "row", style: { gap: "6px" } }, jobBadge(j), j.stage ? h("span", { class: "cell-sub" }, `${j.stage_index}/${j.stage_count} ${j.stage}`) : null),
      j.status === "running" ? progressBar(j) : null);
  }
  if (j && j.status === "failed") {
    return h("a", { href: `#/jobs/${j.id}`, title: j.error || "", onclick: (e) => e.stopPropagation() }, jobBadge(j));
  }
  if (t.processed) return h("span", { class: "badge good", title: fmt.date(t.processed_at) }, icon("check", 12), `Processed ${fmt.ago(t.processed_at)}`);
  if (j && j.status !== "done") return jobBadge(j);
  return h("span", { class: "badge" }, "Not processed");
}

// --------------------------------------------------------------- uploads
function pickFiles(s, reload) {
  const inp = h("input", { type: "file", multiple: true, accept: "video/*,.mov,.mp4,.avi,.mkv,.m4v", style: { display: "none" } });
  inp.onchange = () => uploadFiles(s, [...inp.files], reload);
  document.body.append(inp);
  inp.click();
  setTimeout(() => inp.remove(), 60000);
}
function uploadButton(s, reload) {
  return h("button", { class: "btn", onclick: () => pickFiles(s, reload) }, icon("upload", 15), "Add videos");
}
function dropzone(s, reload) {
  const list = h("div");
  const z = h("div", { class: "dropzone", tabindex: 0, role: "button",
    onclick: () => pickFiles(s, reload), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") pickFiles(s, reload); },
    ondragover: (e) => { e.preventDefault(); z.classList.add("over"); }, ondragleave: () => z.classList.remove("over"),
    ondrop: (e) => { e.preventDefault(); z.classList.remove("over"); uploadFiles(s, [...e.dataTransfer.files], reload, list); } },
  icon("upload", 22), h("div", {}, h("b", {}, "Drop videos here or click to browse"),
    h("div", { class: "small muted" }, "Copied into the subject's folder. Files already in that folder appear automatically.")));
  return h("div", {}, z, list);
}
async function uploadFiles(s, files, reload, list) {
  if (!files.length) return;
  list = list || document.querySelector(".dropzone + div") || h("div");
  let ok = 0;
  for (const f of files) {
    const bar = h("div", { class: "progress" }, h("div", { style: { width: "0%" } }));
    const status = h("span", { class: "small muted" }, "Uploading…");
    const row = h("div", { class: "upload-item" }, h("span", {}, f.name, h("span", { class: "muted" }, ` · ${fmt.bytes(f.size)}`)), bar, status);
    list.append(row);
    try {
      await uploadFile(`/api/subjects/${api.enc(s.id)}/videos/${api.enc(f.name)}`, f, (p) => { bar.firstChild.style.width = `${Math.round(p * 100)}%`; });
      status.textContent = "Done"; ok++;
    } catch (e) {
      status.textContent = e.message; status.style.color = "var(--bad-ink)";
    }
  }
  if (ok) { toast(`${ok} video${ok > 1 ? "s" : ""} added`, "", "good"); await reload(); }
}

// ----------------------------------------------------------- calibration
function calibrationCard(s) {
  const c = s.calibration;
  const href = `#/s/${encodeURIComponent(s.id)}/calibrate`;
  if (!c) {
    return card("Belt calibration", null, null, emptyState("target", "Not calibrated",
      "Pick a frame where the belt corners are visible and click them. Takes about a minute.",
      h("a", { class: "btn primary", href }, icon("target", 15), "Calibrate belt")));
  }
  return card("Belt calibration", fmt.ago(c.updated), [h("a", { class: "btn sm", href }, icon("target", 14), "Recalibrate")],
    h("div", { class: "card-body", style: { display: "grid", gridTemplateColumns: "minmax(0, 150px) 1fr", gap: "18px", alignItems: "start" } },
      c.has_preview ? h("a", { href: `/api/subjects/${api.enc(s.id)}/calibration.png`, target: "_blank", title: "Open full size" },
        h("img", { src: `/api/subjects/${api.enc(s.id)}/calibration.png?t=${c.updated}`, class: "figure", alt: "Calibration preview: belt grid projected on the frame" })) : h("div"),
      h("div", { style: { display: "grid", gap: "10px" } },
        h("dl", { class: "kv" },
          h("dt", {}, "Reprojection"), h("dd", {}, rmsBadge(c.rms_px)),
          h("dt", {}, "Belt"), h("dd", {}, `${fmt.n(c.belt_length_m, 2)} × ${fmt.n(c.belt_width_m, 2)} m`),
          h("dt", {}, "Camera height"), h("dd", {}, `${fmt.n(c.camera_height_m, 2)} m`),
          h("dt", {}, "Focal length"), h("dd", {}, `${fmt.n(c.focal_px, 0)} px ${c.focal_estimated ? "(estimated)" : "(intrinsics)"}`),
          h("dt", {}, "Landmarks"), h("dd", {}, `${c.landmarks.length}`),
          h("dt", {}, "Frame"), h("dd", {}, `${c.video || "–"} #${c.frame}`)),
        c.warning ? h("div", { class: "banner warn small" }, icon("alert", 15), h("div", { class: "grow" }, c.warning)) : null)));
}

function videosCard(s, reload) {
  const rows = s.videos.map((v) => {
    const role = select([["trial", "Trial"], ["checkerboard", "Checkerboard"]], v.role, {
      style: { width: "140px", height: "30px" },
      onchange: async (e) => { await api.patch(`/api/subjects/${api.enc(s.id)}`, { video_roles: { [v.name]: e.target.value } }); reload(); } });
    return h("tr", {}, h("td", {}, h("div", { class: "cell-main" }, v.name),
      h("div", { class: "cell-sub" }, `${fmt.dur(v.info?.duration_s)} · ${v.info?.width}×${v.info?.height} · ${fmt.bytes(v.size)}`)),
    h("td", { class: "num" }, role));
  });
  const boards = s.videos.filter((v) => v.role === "checkerboard");
  return card("All videos", "role decides what gets processed",
    boards.length ? [h("a", { class: "btn sm", href: "#/cameras", onclick: () => store("camera-prefill", { subject: s.id, video: boards[0].name }) }, icon("camera", 14), "Camera from checkerboard")] : null,
    s.videos.length ? h("div", { class: "table-wrap" }, h("table", { class: "t" }, h("tbody", {}, rows)))
      : h("div", { class: "card-body muted" }, "No videos yet."));
}

// ---------------------------------------------------------- run dialog
export async function runDialog(s, trialIds, onDone) {
  const defaults = await api.get("/api/config/default");
  const last = store("run-settings") || {};
  const d = {
    device: last.device ?? defaults.pose2d?.device ?? "cuda",
    mode: last.mode ?? defaults.pose2d?.mode ?? "balanced",
    belt: last.belt ?? defaults.belt_speed?.source ?? "refined",
    events: last.events ?? defaults.events?.method ?? "zeni",
    opensim: last.opensim ?? defaults.opensim?.enabled ?? true,
    hs: last.hs ?? defaults.events?.hs_offset_ms ?? 0,
    to: last.to ?? defaults.events?.to_offset_ms ?? 0,
    yaml: last.yaml ?? "",
  };
  const trials = trialIds.map((id) => s.trials.find((t) => t.id === id)).filter(Boolean);
  const speedInputs = {};
  const speedRows = trials.map((t) => {
    const inp = h("input", { type: "number", step: "0.01", min: 0, value: t.displayed_speed_m_s ?? t.speed_hint ?? "", placeholder: "optional", style: { width: "110px" } });
    speedInputs[t.id] = inp;
    return h("div", { class: "row", style: { justifyContent: "space-between" } },
      h("span", {}, h("b", {}, t.id), t.processed ? h("span", { class: "muted small" }, "  · results will be replaced") : null),
      h("div", { class: "input-unit", style: { width: "130px" } }, inp, h("span", {}, "m/s")));
  });
  const device = seg([["cuda", "GPU (CUDA)"], ["cpu", "CPU"]], d.device);
  const mode = seg([["lightweight", "Fast"], ["balanced", "Balanced"], ["performance", "Accurate"]], d.mode);
  const belt = seg([["refined", "Estimate from video"], ["known", "Use treadmill speed"]], d.belt);
  const events = select([["zeni", "Zeni (heel/toe vs pelvis)"], ["velocity", "Foot velocity"]], d.events);
  const opensim = h("input", { type: "checkbox", checked: d.opensim });
  const anyCached = trials.some((t) => t.processed);
  const force = h("input", { type: "checkbox", checked: false });
  const hs = h("input", { type: "number", step: 1, value: d.hs });
  const to = h("input", { type: "number", step: 1, value: d.to });
  const yaml = h("textarea", { rows: 4, placeholder: "# merged over configs/default.yaml, e.g.\nrefine:\n  iters: 800" }, d.yaml);

  modal({
    title: trials.length === 1 ? `Process ${trials[0].id}` : `Process ${trials.length} trials`,
    sub: "Runs in the background, one trial at a time. You can keep using the app.",
    okLabel: trials.length === 1 ? "Start processing" : `Queue ${trials.length} trials`,
    wide: true,
    body: [
      h("div", { class: "fieldset" }, h("div", { class: "legend" }, "Treadmill speed shown on the display"),
        h("div", { class: "small muted" }, "Used to check the estimated belt speed, or as the belt speed if you choose “Use treadmill speed”."),
        h("div", { style: { display: "grid", gap: "8px" } }, speedRows)),
      h("div", { class: "form-grid" },
        field("Compute device", device.el, "GPU needs the CUDA build of onnxruntime + PyTorch (see System)."),
        field("2D pose model", mode.el, "Accurate is slower; Balanced is the usual choice."),
        field("Belt speed", belt.el),
        field("Gait event method", events)),
      h("label", { class: "check" }, opensim, h("span", {}, "OpenSim scaling + inverse kinematics",
        h("span", { class: "help" }, "Joint angles and model-based events. Turn off if OpenSim is not installed."))),
      h("label", { class: "check" }, force, h("span", {}, "Re-run 2D pose detection",
        h("span", { class: "help" }, anyCached ? "Otherwise keypoints from the previous run are reused (much faster). Tick this after changing the pose model."
          : "Only matters for trials that were processed before."))),
      h("details", { class: "adv" }, h("summary", {}, icon("chevron", 14), "Advanced"),
        h("div", { class: "form-grid", style: { marginTop: "12px" } },
          field("Heel-strike offset", h("div", { class: "input-unit" }, hs, h("span", {}, "ms")), "Constant correction, e.g. from force plates"),
          field("Toe-off offset", h("div", { class: "input-unit" }, to, h("span", {}, "ms"))),
          h("div", { class: "full" }, field("Extra settings (YAML)", yaml, "Any key from configs/default.yaml.")))),
    ],
    onOk: async () => {
      const v = { device: device.value, mode: mode.value, belt: belt.value, events: events.value, opensim: opensim.checked,
        hs: Number(hs.value) || 0, to: Number(to.value) || 0, yaml: yaml.value };
      store("run-settings", v);
      const speeds = {};
      for (const [id, inp] of Object.entries(speedInputs)) if (inp.value !== "") speeds[id] = Number(inp.value);
      if (v.belt === "known") {
        const missing = trials.filter((t) => speeds[t.id] === undefined).map((t) => t.id);
        if (missing.length) throw new Error(`Enter the treadmill speed for ${missing.join(", ")}`);
      }
      const settings = {
        pose2d: { device: v.device, mode: v.mode },
        refine: { device: v.device },
        belt_speed: { source: v.belt, known_m_s: null },
        events: { method: v.events, source: v.opensim ? "opensim" : "refined", hs_offset_ms: v.hs, to_offset_ms: v.to },
        opensim: { enabled: v.opensim },
      };
      const r = await api.post(`/api/subjects/${api.enc(s.id)}/process`, {
        trials: trials.map((t) => t.id), settings, advanced_yaml: v.yaml, force: force.checked, displayed_speeds: speeds });
      const n = r.submitted.length;
      toast(n ? `Queued ${n} trial${n > 1 ? "s" : ""}` : "Nothing queued",
        r.skipped.length ? `Skipped: ${r.skipped.map((x) => x.trial).join(", ")} (already running)` : "Progress shows in the trials table.",
        n ? "info" : "warn", n ? { href: "#/jobs", label: "Open jobs" } : null);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      onDone?.();
    },
  });
}
