// DOM + UI helpers. All text goes through textContent (never innerHTML with data).

export function h(tag, attrs, ...children) {
  const el = tag === "svg" || SVG_TAGS.has(tag) ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k in el && !(el instanceof SVGElement) && typeof v !== "string") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  append(el, children);
  return el;
}
const SVG_TAGS = new Set(["path", "g", "line", "rect", "circle", "polyline", "polygon", "text", "defs", "clipPath",
  "linearGradient", "stop", "title", "tspan"]);

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

// ------------------------------------------------------------------- icons
const ICONS = {
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  camera: "M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  cpu: "M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 9h6v6H9z",
  check: "M20 6L9 17l-5-5",
  x: "M18 6L6 18M6 6l12 12",
  alert: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  play: "M6 4l14 8-14 8z",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  chevron: "M9 18l6-6-6-6",
  left: "M15 18l-6-6 6-6",
  plus: "M12 5v14M5 12h14",
  target: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  refresh: "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15",
  edit: "M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  video: "M23 7l-7 5 7 5zM3 5h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  loader: "M21 12a9 9 0 1 1-6.22-8.56",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42",
  moon: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
  trash: "M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
  zap: "M13 2L3 14h9l-1 8 10-12h-9z",
  stop: "M6 6h12v12H6z",
};

export function icon(name, size = 16, cls = "") {
  const s = h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", class: cls, "aria-hidden": "true" });
  s.append(h("path", { d: ICONS[name] || ICONS.info }));
  return s;
}

// --------------------------------------------------------------- formatting
export const fmt = {
  n(v, d = 2) { return v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d); },
  pct(v, d = 1) { return v === null || v === undefined ? "–" : `${Number(v).toFixed(d)} %`; },
  dur(s) {
    if (s === null || s === undefined) return "–";
    s = Math.round(s);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return `${m}m ${String(r).padStart(2, "0")}s`;
    return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
  },
  ago(t) {
    if (!t) return "–";
    const d = Date.now() / 1000 - t;
    if (d < 45) return "just now";
    if (d < 3600) return `${Math.round(d / 60)} min ago`;
    if (d < 86400) return `${Math.round(d / 3600)} h ago`;
    return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  },
  date(t) { return t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–"; },
  bytes(b) {
    if (!b) return "–";
    const u = ["B", "KB", "MB", "GB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(i ? 1 : 0)} ${u[i]}`;
  },
};

// ---------------------------------------------------------------- statuses
const JOB_STATUS = {
  queued: ["Queued", "", "list"], running: ["Running", "run", "loader"], done: ["Done", "good", "check"],
  failed: ["Failed", "bad", "alert"], cancelled: ["Cancelled", "", "x"], interrupted: ["Interrupted", "warn", "alert"],
};
export function jobBadge(job, withPct = true) {
  const [label, cls, ic] = JOB_STATUS[job.status] || [job.status, "", "info"];
  const pct = job.status === "running" && withPct && job.progress != null ? ` ${Math.round(job.progress * 100)}%` : "";
  return h("span", { class: `badge ${cls}` }, icon(ic, 12, job.status === "running" ? "spin" : ""), label + pct);
}
export function progressBar(job) {
  const ind = job.status === "running" && job.progress == null;
  return h("div", { class: `progress${ind ? " indeterminate" : ""}` },
    h("div", { style: { width: `${Math.round((job.progress || 0) * 100)}%` } }));
}

// quality chip for reprojection / checkerboard RMS (px)
export function rmsBadge(rms, good = 1.0, ok = 2.5) {
  if (rms === null || rms === undefined) return h("span", { class: "badge" }, "–");
  const cls = rms <= good ? "good" : rms <= ok ? "warn" : "bad";
  const ic = rms <= good ? "check" : "alert";
  return h("span", { class: `badge ${cls}`, title: "RMS reprojection error" }, icon(ic, 12), `${rms.toFixed(2)} px`);
}

// ------------------------------------------------------------------- toast
export function toast(title, body = "", kind = "info", action = null, ms = 6000) {
  const colors = { good: "var(--good)", bad: "var(--bad)", warn: "var(--warn)", info: "var(--accent)" };
  const ic = { good: "check", bad: "alert", warn: "alert", info: "info" }[kind];
  const el = h("div", { class: "toast", role: "status" },
    h("span", { style: { color: colors[kind] } }, icon(ic, 18)),
    h("div", { class: "grow" }, h("div", { class: "title" }, title), body ? h("div", { class: "ink2" }, body) : null,
      action ? h("div", {}, h("a", { href: action.href, onclick: () => el.remove() }, action.label)) : null),
    h("button", { class: "btn ghost sm icon", "aria-label": "Dismiss", onclick: () => el.remove() }, icon("x", 14)));
  document.getElementById("toasts").append(el);
  if (ms) setTimeout(() => el.remove(), ms);
}

// ------------------------------------------------------------------- modal
export function modal({ title, sub, body, okLabel = "Save", onOk, wide = false, okDanger = false }) {
  const err = h("span", { class: "err" });
  const ok = h("button", { class: `btn ${okDanger ? "danger" : "primary"}` }, okLabel);
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const back = h("div", { class: "modal-back", onmousedown: (e) => { if (e.target === back) close(); } },
    h("div", { class: `modal${wide ? " wide" : ""}`, role: "dialog", "aria-modal": "true" },
      h("div", { class: "modal-head" }, h("div", {}, h("h2", {}, title), sub ? h("div", { class: "sub" }, sub) : null),
        h("button", { class: "btn ghost sm icon", "aria-label": "Close", onclick: close }, icon("x", 16))),
      h("div", { class: "modal-body" }, body),
      h("div", { class: "modal-foot" }, err, h("button", { class: "btn", onclick: close }, "Cancel"), ok)));
  ok.addEventListener("click", async () => {
    err.textContent = ""; ok.disabled = true;
    try { if ((await onOk()) !== false) close(); } catch (e) { err.textContent = e.message; } finally { ok.disabled = false; }
  });
  document.addEventListener("keydown", onKey);
  document.body.append(back);
  const first = back.querySelector("input, select, textarea");
  if (first) setTimeout(() => first.focus(), 30);
  return { close };
}

// ------------------------------------------------------------- form bits
export function field(label, input, help) {
  return h("label", { class: "field" }, label, input, help ? h("span", { class: "help" }, help) : null);
}
export function numInput(value, unit, attrs = {}) {
  const inp = h("input", { type: "number", step: "any", value: value ?? "", ...attrs });
  return { el: unit ? h("div", { class: "input-unit" }, inp, h("span", {}, unit)) : inp, input: inp };
}
export function select(options, value, attrs = {}) {
  const s = h("select", attrs, options.map(([v, l]) => h("option", { value: v }, l)));
  if (value !== undefined && value !== null) s.value = value;
  return s;
}
export function seg(options, value, onChange) {
  const el = h("div", { class: "seg", role: "radiogroup" });
  const set = (v) => { value = v; [...el.children].forEach((b) => b.classList.toggle("on", b.dataset.v === v)); onChange?.(v); };
  options.forEach(([v, l]) => el.append(h("button", { type: "button", dataset: { v }, role: "radio", onclick: () => set(v) }, l)));
  set(value);
  return { el, get value() { return value; }, set };
}

export function card(title, hint, actions, ...body) {
  return h("section", { class: "card" },
    title ? h("div", { class: "card-head" }, h("h2", {}, title, hint ? h("span", { class: "hint" }, "  ", hint) : null),
      actions ? h("div", { class: "actions" }, actions) : null) : null,
    ...body);
}

export function emptyState(ic, title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "empty-icon" }, icon(ic, 22)), h("h2", {}, title),
    text ? h("p", { class: "muted", style: { maxWidth: "460px" } }, text) : null, action || null);
}

export function crumbs(...items) {
  const el = h("div", { class: "crumbs" });
  items.forEach((it, i) => {
    if (i) el.append(icon("chevron", 12));
    el.append(it.href ? h("a", { href: it.href }, it.label) : h("span", {}, it.label));
  });
  return el;
}

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(`humotech-${key}`));
    localStorage.setItem(`humotech-${key}`, JSON.stringify(value));
  } catch (e) { return undefined; }
}
