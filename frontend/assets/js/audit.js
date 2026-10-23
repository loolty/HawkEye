/* Hawkeyes — audit trail viewer (admin only) */
"use strict";

let page = 1;

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;
  if (user.role !== "admin") { location.href = "/dashboard.html"; return; }

  document.getElementById("filterAction").addEventListener("change", () => { page = 1; loadAudit(); });
  document.getElementById("filterTable").addEventListener("change", () => { page = 1; loadAudit(); });
  document.getElementById("prevPage").addEventListener("click", () => { if (page > 1) { page--; loadAudit(); } });
  document.getElementById("nextPage").addEventListener("click", () => { page++; loadAudit(); });

  await loadAudit();
});

async function loadAudit() {
  const body = document.getElementById("auditBody");
  try {
    const action = document.getElementById("filterAction").value;
    const table = document.getElementById("filterTable").value;
    const params = new URLSearchParams({ page, page_size: 50 });
    if (action) params.set("action", action);
    if (table) params.set("table_name", table);

    const { items, total, page: p, page_size } = await apiFetch(`/api/audit-logs?${params}`);
    body.innerHTML = items.length ? items.map(a => `
      <tr>
        <td><small>${fmtDT(a.timestamp)}</small></td>
        <td>${a.user_name || "<em class='text-muted'>system/unauth</em>"}<br>${a.user_role ? roleBadge(a.user_role) : ""}</td>
        <td><span class="badge bg-${actionColor(a.action)}">${a.action}</span></td>
        <td>${a.table_name}${a.record_id ? ` #${a.record_id}` : ""}</td>
        <td>${a.record_id ?? "—"}</td>
        <td><code class="small">${a.ip_address || "—"}</code></td>
        <td><small>${a.details ? detailCell(a.details) : "—"}</small></td>
      </tr>`).join("")
      : `<tr><td colspan="7" class="text-muted text-center py-4">No audit entries match.</td></tr>`;

    const last = Math.max(1, Math.ceil(total / page_size));
    document.getElementById("pageInfo").textContent = `Page ${p} of ${last} — ${total} entries`;
    document.getElementById("prevPage").disabled = p <= 1;
    document.getElementById("nextPage").disabled = p >= last;
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    page = Math.max(1, page - 1);
    body.innerHTML = `<tr><td colspan="7" class="text-muted text-center py-4">Could not load audit logs.</td></tr>`;
  }
}

function actionColor(action) {
  return { CREATE: "success", UPDATE: "primary", READ: "secondary",
           DELETE: "danger", LOGIN: "info", ACCESS_DENIED: "warning" }[action] || "dark";
}

function detailCell(json) {
  try {
    const obj = typeof json === "string" ? JSON.parse(json) : json;
    const text = JSON.stringify(obj);
    return text.length > 60 ? `<span title="${escapeHtml(text)}">${escapeHtml(text.slice(0, 60))}…</span>`
                            : escapeHtml(text);
  } catch { return escapeHtml(String(json)); }
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
