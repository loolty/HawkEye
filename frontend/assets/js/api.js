/* ============================================================
   Hawkeyes — shared Fetch API layer
   * adds the JWT bearer token to every call
   * normalizes errors and 401 → login redirect
   * page bootstrap helpers (guard + navbar)
   ============================================================ */
"use strict";

const TOKEN_KEY = "hk_token";
const USER_KEY = "hk_user";

/* ---------- token / identity helpers ---------- */
function getToken()      { return localStorage.getItem(TOKEN_KEY); }
function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
  catch { return null; }
}
function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
function logout() { clearSession(); window.location.href = "/index.html"; }

/* ---------- core fetch wrapper ---------- */
/**
 * apiFetch(path, options) → parsed JSON (or null for 204).
 * Throws Error with .status and .detail on non-2xx responses.
 */
async function apiFetch(path, { method = "GET", body = null, headers = {} } = {}) {
  const opts = { method, headers: { ...headers } };
  const token = getToken();
  if (token) opts.headers["Authorization"] = `Bearer ${token}`;
  if (body !== null && method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.headers.body = undefined;
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(path, opts);

  if (res.status === 401) {           // session expired / invalid
    clearSession();
    window.location.href = "/index.html?expired=1";
    throw Object.assign(new Error("Session expired"), { status: 401, silent: true });
  }

  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson && res.status !== 204 ? await res.json() : null;

  if (!res.ok) {
    const detail = (data && (data.detail?.[0]?.msg || data.detail)) ||
                   `Request failed (${res.status})`;
    throw Object.assign(new Error(detail), { status: res.status, detail });
  }
  return data;
}

/* ---------- error surfaces ---------- */
function alertBox(el, message, type = "danger") {
  if (!el) { console.warn("alertBox target missing:", message); return; }
  el.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
}
function firstError(e) {
  // pydantic validation errors arrive as arrays in .detail
  if (Array.isArray(e.detail)) return e.detail.map(d => d.msg).join("; ");
  return e.message || "Unexpected error.";
}

/* ---------- page bootstrap for protected pages ---------- */
const NAV_ITEMS = {  // href, label, allowed roles (undefined = all staff+patient)
  "/dashboard.html":      { label: "Dashboard", roles: null },
  "/patients.html":       { label: "Patients",  roles: ["admin", "optometrist", "front_desk"] },
  "/prescriptions.html":  { label: "Prescriptions", roles: ["admin", "optometrist", "patient"] },
  "/appointments.html":   { label: "Appointments",  roles: null },
  "/audit.html":          { label: "Audit Logs",    roles: ["admin"] },
  "/users.html":          { label: "Accounts",      roles: ["admin"] },
};

/**
 * Guard the page and render the shared navbar. Returns the user, or null
 * (already redirected to login).
 */
function initProtectedPage() {
  const user = getStoredUser();
  if (!getToken() || !user) { window.location.href = "/index.html"; return null; }

  const current = location.pathname.split("/").pop() || "dashboard.html";
  const meta = NAV_ITEMS["/" + current];
  if (meta && meta.roles && !meta.roles.includes(user.role)) {
    // wrong-role access: send them to their own dashboard
    window.location.href = "/dashboard.html";
    return null;
  }

  const mount = document.getElementById("hk-navbar");
  if (mount) {
    const links = Object.entries(NAV_ITEMS)
      .filter(([, m]) => !m.roles || m.roles.includes(user.role))
      .map(([href, m]) =>
        `<li class="nav-item"><a class="nav-link ${('' + href === '/' + current) ? "active" : ""}"
            href="${href}">${m.label}</a></li>`).join("");
    mount.innerHTML = `
      <nav class="navbar navbar-expand-lg navbar-light hk-navbar">
        <div class="container">
          <a class="navbar-brand" href="/${current}"><span class="hk-logo hk-logo-sm" style="width: 36px; height: 36px; font-size: 0.9rem; border-radius: 10px;">HK</span> Hawkeyes</a>
          <button class="navbar-toggler border-0" data-bs-toggle="collapse" data-bs-target="#navMain">
            <span class="navbar-toggler-icon"></span></button>
          <div class="collapse navbar-collapse" id="navMain">
            <ul class="navbar-nav me-auto">${links}</ul>
            <span class="navbar-text me-3 d-none d-md-inline">
              ${user.full_name} <span class="badge bg-secondary">${user.role}</span>
            </span>
            <button class="btn btn-sm" onclick="logout()">Logout</button>
          </div>
        </div>
      </nav>`;
  }
  return user;
}

/* ---------- misc helpers ---------- */
function fmtDT(value) { return value ? new Date(value).toLocaleString() : "—"; }
function fmtNum(v, d = 2)  { return (v === null || v === undefined) ? "—" : Number(v).toFixed(d); }
function fmtAxis(v) { return (v === null || v === undefined) ? "—" : `${v}°`; }
function roleBadge(role) {
  const colors = { admin: "danger", optometrist: "info", front_desk: "warning", patient: "success" };
  return `<span class="badge bg-${colors[role] || "secondary"}">${role}</span>`;
}
function statusBadge(status) {
  return `<span class="badge st-${status.replace(" ", "_")}">${status.replace("_", " ")}</span>`;
}
function qs(name) { return new URLSearchParams(location.search).get(name); }
