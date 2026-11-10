// Thin fetch wrapper: JSON in/out, readable errors.

async function req(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

export const api = {
  get: (u) => req("GET", u),
  post: (u, b = {}) => req("POST", u, b),
  patch: (u, b) => req("PATCH", u, b),
  enc: encodeURIComponent,
};

// Streamed upload with progress (XHR has upload progress events; fetch doesn't).
export function uploadFile(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("PUT", url);
    x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    x.onload = () => {
      if (x.status >= 200 && x.status < 300) resolve(JSON.parse(x.responseText));
      else {
        let msg = `${x.status}`;
        try { msg = JSON.parse(x.responseText).detail || msg; } catch (e) { /* ignore */ }
        reject(new Error(msg));
      }
    };
    x.onerror = () => reject(new Error("Upload failed (connection lost)"));
    x.send(file);
  });
}
