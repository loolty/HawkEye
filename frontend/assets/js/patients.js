/* Hawkeyes — patients management (staff roles) */
"use strict";

let page = 1;
let editingId = null;      // null = create, number = edit
let patientModal, historyModal;

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;
  if (user.role === "patient") { location.href = "/dashboard.html"; return; }

  patientModal = new bootstrap.Modal("#patientModal");
  historyModal = new bootstrap.Modal("#historyModal");

  document.getElementById("searchBox").addEventListener("input", debounce(() => { page = 1; loadPatients(); }, 400));
  document.getElementById("pageSize").addEventListener("change", () => { page = 1; loadPatients(); });
  document.getElementById("prevPage").addEventListener("click", () => { if (page > 1) { page--; loadPatients(); } });
  document.getElementById("nextPage").addEventListener("click", () => { page++; loadPatients(); });
  document.getElementById("patientSaveBtn").addEventListener("click", savePatient);
  document.getElementById("patientForm").addEventListener("submit", e => e.preventDefault());

  await loadPatients();
});

async function loadPatients() {
  const body = document.getElementById("patientsBody");
  try {
    const q = encodeURIComponent(document.getElementById("searchBox").value.trim());
    const size = document.getElementById("pageSize").value;
    const data = await apiFetch(`/api/patients?q=${q}&page=${page}&page_size=${size}`);
    renderPatients(data);
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    body.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Could not load patients.</td></tr>`;
    if (err.status === 403 || err.status === 404) page = Math.max(1, page - 1);
  }
}

function renderPatients({ items, total, page: p, page_size }) {
  const canEdit = ["admin", "front_desk"].includes(getStoredUser().role);
  const canArchive = getStoredUser().role === "admin";
  document.getElementById("patientsBody").innerHTML = items.length ? items.map(pt => `
    <tr>
      <td><span class="badge bg-dark-subtle text-dark">${pt.hk_patient_id}</span></td>
      <td><strong>${pt.last_name}, ${pt.first_name}</strong></td>
      <td>${pt.date_of_birth}</td>
      <td>${pt.sex || "—"}</td>
      <td>${pt.contact_number || "—"}</td>
      <td>${pt.email || "—"}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-secondary" title="Prescription history"
                onclick="viewHistory(${pt.id}, '${pt.first_name} ${pt.last_name}')">
          <i class="bi bi-eye"></i></button>
        ${canEdit ? `<button class="btn btn-sm btn-outline-primary" title="Edit"
                onclick='openEditForm(${JSON.stringify(pt)})'><i class="bi bi-pencil"></i></button>` : ""}
        ${canArchive ? `<button class="btn btn-sm btn-outline-danger" title="Archive"
                onclick="archivePatient(${pt.id}, '${pt.first_name} ${pt.last_name}')"><i class="bi bi-archive"></i></button>` : ""}
      </td>
    </tr>`).join("")
    : `<tr><td colspan="7" class="text-center text-muted py-4">No patients found.</td></tr>`;

  const last = Math.max(1, Math.ceil(total / page_size));
  document.getElementById("pageInfo").textContent = `Page ${p} of ${last} — ${total} patients`;
  document.getElementById("prevPage").disabled = p <= 1;
  document.getElementById("nextPage").disabled = p >= last;
}

/* ---------- create / edit ---------- */
function openCreateForm() {
  editingId = null;
  document.getElementById("patientModalTitle").textContent = "Register Patient";
  ["pFirst", "pLast", "pDob", "pContact", "pEmail", "pAddress"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("pSex").value = "";
}

function openEditForm(pt) {
  editingId = pt.id;
  document.getElementById("patientModalTitle").textContent = `Edit ${pt.first_name} ${pt.last_name}`;
  document.getElementById("pFirst").value = pt.first_name;
  document.getElementById("pLast").value = pt.last_name;
  document.getElementById("pDob").value = pt.date_of_birth;
  document.getElementById("pSex").value = pt.sex || "";
  document.getElementById("pContact").value = pt.contact_number || "";
  document.getElementById("pEmail").value = pt.email || "";
  document.getElementById("pAddress").value = "";
  patientModal.show();
}

async function savePatient() {
  const payload = {
    first_name: document.getElementById("pFirst").value.trim(),
    last_name: document.getElementById("pLast").value.trim(),
    date_of_birth: document.getElementById("pDob").value,
    sex: document.getElementById("pSex").value || null,
    contact_number: document.getElementById("pContact").value.trim() || null,
    email: document.getElementById("pEmail").value.trim() || null,
    address: document.getElementById("pAddress").value.trim() || null,
  };
  if (!payload.first_name || !payload.last_name || !payload.date_of_birth) {
    alertBox(document.getElementById("pageAlert"), "First name, last name and DOB are required.", "warning");
    return;
  }
  try {
    if (editingId) {
      await apiFetch(`/api/patients/${editingId}`, { method: "PUT", body: payload });
    } else {
      const created = await apiFetch("/api/patients", { method: "POST", body: payload });
      alertBox(document.getElementById("pageAlert"), created.message, "success");
    }
    patientModal.hide();
    loadPatients();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

async function archivePatient(id, name) {
  if (!confirm(`Archive ${name}? Their prescription history is preserved.`)) return;
  try {
    await apiFetch(`/api/patients/${id}`, { method: "DELETE" });
    loadPatients();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

/* ---------- prescription history (System Rule 4: OD/OS detail) ---------- */
async function viewHistory(id, name) {
  document.getElementById("historyTitle").textContent = `Prescription history — ${name}`;
  const body = document.getElementById("historyBody");
  body.innerHTML = `<div class="text-center text-muted py-4">Loading…</div>`;
  historyModal.show();
  try {
    const rows = await apiFetch(`/api/patients/${id}/prescriptions`);
    body.innerHTML = rows.length ? `
      <table class="table table-bordered text-center eye-col">
        <thead><tr><th>Exam Date</th><th>Eye</th><th>Sphere</th><th>Cylinder</th><th>Axis</th><th>Add</th><th>Optometrist</th><th>Lens</th></tr></thead>
        <tbody>${rows.flatMap(r => [
          rxRow(r, r.exam_date, "OD", r.od_sphere, r.od_cylinder, r.od_axis, r.od_add, r),
          rxRow(r, "", "OS", r.os_sphere, r.os_cylinder, r.os_axis, r.os_add, r),
        ]).join("")}</tbody>
      </table>`
      : `<div class="text-center text-muted py-4">No prescriptions on record.</div>`;
  } catch (err) {
    body.innerHTML = `<div class="alert alert-danger m-3">${firstError(err)}</div>`;
  }
}

function rxRow(r, firstCell, eye, sphere, cyl, axis, add, meta) {
  return `<tr>
    <td rowspan="1">${firstCell ? (firstCell.slice(0, 10)) : ""}</td>
    <td class="fw-bold">${eye}</td>
    <td class="rx-badge">${fmtNum(sphere)}</td>
    <td class="rx-badge">${fmtNum(cyl)}</td>
    <td class="rx-badge">${fmtAxis(axis)}</td>
    <td class="rx-badge">${fmtNum(add)}</td>
    <td>${meta.optometrist || "—"}</td>
    <td>${(meta.lens_type || "—").replace("_", " ")}</td>
  </tr>`;
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
