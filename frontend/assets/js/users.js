/* Hawkeyes — user accounts (admin only) */
"use strict";

let page = 1;
let pwTargetId = null;
let userModal, pwModal;

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;
  if (user.role !== "admin") { location.href = "/dashboard.html"; return; }

  userModal = new bootstrap.Modal("#userModal");
  pwModal = new bootstrap.Modal("#pwModal");

  document.getElementById("searchBox").addEventListener("input", debounce(() => { page = 1; loadUsers(); }, 400));
  document.getElementById("filterRole").addEventListener("change", () => { page = 1; loadUsers(); });
  document.getElementById("prevPage").addEventListener("click", () => { if (page > 1) { page--; loadUsers(); } });
  document.getElementById("nextPage").addEventListener("click", () => { page++; loadUsers(); });
  document.getElementById("userSaveBtn").addEventListener("click", saveUser);
  document.getElementById("pwSaveBtn").addEventListener("click", savePassword);

  await loadUsers();
});

async function loadUsers() {
  const body = document.getElementById("usersBody");
  try {
    const q = encodeURIComponent(document.getElementById("searchBox").value.trim());
    const role = document.getElementById("filterRole").value;
    const params = new URLSearchParams({ q, page, page_size: 20 });
    if (role) params.set("role", role);
    const data = await apiFetch(`/api/users?${params}`);
    renderUsers(data);
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    body.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Could not load users.</td></tr>`;
    page = Math.max(1, page - 1);
  }
}

function renderUsers({ items, total, page: p, page_size }) {
  const me = getStoredUser();
  document.getElementById("usersBody").innerHTML = items.length ? items.map(u => {
    const isSelf = u.id === me.id;
    return `<tr>
      <td><strong>${u.full_name}</strong>${isSelf ? " <span class='badge bg-info'>you</span>" : ""}</td>
      <td>${u.email}</td>
      <td>${roleBadge(u.role)}</td>
      <td>${u.is_active ? "<span class='badge bg-success'>active</span>"
                        : "<span class='badge bg-dark'>deactivated</span>"}</td>
      <td>${u.linked_patient_id ? `<a class="text-decoration-none" href="/patients.html?q=${u.email}">record →</a>` : "—"}</td>
      <td><small>${(u.created_at || "").slice(0, 10)}</small></td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-warning" title="Reset password"
          onclick="resetPassword(${u.id}, '${u.full_name}')"><i class="bi bi-key"></i></button>
        ${u.is_active && !isSelf ? `<button class="btn btn-sm btn-outline-danger" title="Deactivate"
          onclick="deactivateUser(${u.id}, '${u.full_name}')"><i class="bi bi-person-x"></i></button>` : ""}
      </td>
    </tr>`;
  }).join("")
  : `<tr><td colspan="7" class="text-center text-muted py-4">No accounts found.</td></tr>`;

  const last = Math.max(1, Math.ceil(total / page_size));
  document.getElementById("pageInfo").textContent = `Page ${p} of ${last} — ${total} accounts`;
  document.getElementById("prevPage").disabled = p <= 1;
  document.getElementById("nextPage").disabled = p >= last;
}

/* ---------- create ---------- */
function openCreateForm() {
  ["uName", "uEmail", "uPassword"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("uRole").value = "front_desk";
}

async function saveUser() {
  try {
    const out = await apiFetch("/api/users", {
      method: "POST",
      body: {
        full_name: document.getElementById("uName").value.trim(),
        email: document.getElementById("uEmail").value.trim().toLowerCase(),
        password: document.getElementById("uPassword").value,
        role: document.getElementById("uRole").value,
      },
    });
    alertBox(document.getElementById("pageAlert"), out.message, "success");
    userModal.hide();
    loadUsers();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

/* ---------- reset password ---------- */
function resetPassword(id, name) {
  pwTargetId = id;
  document.getElementById("pwTitle").textContent = `Reset password — ${name}`;
  document.getElementById("pwNew").value = "";
  pwModal.show();
}

async function savePassword() {
  const pw = document.getElementById("pwNew").value;
  if (pw.length < 8) {
    alertBox(document.getElementById("pageAlert"), "Password must be at least 8 characters.", "warning");
    return;
  }
  try {
    await apiFetch(`/api/users/${pwTargetId}`, { method: "PATCH", body: { new_password: pw } });
    alertBox(document.getElementById("pageAlert"), "Password reset.", "success");
    pwModal.hide();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

/* ---------- deactivate ---------- */
async function deactivateUser(id, name) {
  if (!confirm(`Deactivate ${name}? They will no longer be able to log in.`)) return;
  try {
    const out = await apiFetch(`/api/users/${id}`, { method: "DELETE" });
    alertBox(document.getElementById("pageAlert"), out.message, "success");
    loadUsers();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
