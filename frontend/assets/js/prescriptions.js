/* Hawkeyes — prescriptions (staff create/edit/list; patient read-only) */
"use strict";

let editingRxId = null;

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;

  const isStaff = ["admin", "optometrist"].includes(user.role);
  if (isStaff) {
    document.getElementById("rxFormCard").classList.remove("d-none");
    document.getElementById("rxForm").addEventListener("submit", saveRx);
    await loadPatientOptions();
  } else {
    document.getElementById("thPatient").textContent = "My Rx";
    document.getElementById("rxListHeader").textContent = "My Prescription History";
  }
  await loadRx();
});

/* staff: populate patient dropdown */
async function loadPatientOptions() {
  try {
    const data = await apiFetch("/api/patients?page=1&page_size=100");
    document.getElementById("rxPatient").innerHTML =
      `<option value="">— select patient —</option>` +
      data.items.map(pt =>
        `<option value="${pt.id}">${pt.last_name}, ${pt.first_name} (${pt.hk_patient_id})</option>`)
        .join("");
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

async function loadRx() {
  const user = getStoredUser();
  const body = document.getElementById("rxBody");
  const colCount = user.role === "patient" ? 11 : 12;
  try {
    const rows = user.role === "patient"
      ? await apiFetch("/api/prescriptions/my")
      : await apiFetch("/api/prescriptions/recent?limit=30");
    body.innerHTML = rows.length ? rows.map(r => `
      <tr>
        <td>${(r.exam_date || "").slice(0, 10)}</td>
        ${user.role === "patient" ? "" :
          `<td class="text-start">${r.patient_name}<br><span class="text-muted small">${r.hk_patient_id}</span></td>`}
        <td class="rx-badge">${fmtNum(r.od_sphere)}</td>
        <td class="rx-badge">${fmtNum(r.od_cylinder)}</td>
        <td class="rx-badge">${fmtAxis(r.od_axis)}</td>
        <td class="rx-badge">${fmtNum(r.od_add)}</td>
        <td class="rx-badge">${fmtNum(r.os_sphere)}</td>
        <td class="rx-badge">${fmtNum(r.os_cylinder)}</td>
        <td class="rx-badge">${fmtAxis(r.os_axis)}</td>
        <td class="rx-badge">${fmtNum(r.os_add)}</td>
        <td class="text-start">${r.optometrist || "—"}</td>
        ${user.role === "patient" ? "" :
          `<td class="text-end">
            <button class="btn btn-sm btn-outline-secondary" title="View details"
              onclick='viewRx(${JSON.stringify(r)})'>Details</button>
            ${user.role === "admin" ?
              `<button class="btn btn-sm btn-outline-danger" title="Archive"
                onclick="archiveRx(${r.id})">Archive</button>` : ""}
          </td>`}
      </tr>`).join("")
      : `<tr><td colspan="${colCount}" class="text-muted py-4">No prescriptions found.</td></tr>`;
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

/* ---------- create / update ---------- */
function eyePayload(prefix) {
  const cyl = parseFloat(document.getElementById(`${prefix}Cylinder`).value) || 0;
  const axisRaw = document.getElementById(`${prefix}Axis`).value;
  const addRaw = document.getElementById(`${prefix}Add`).value;
  return {
    sphere: parseFloat(document.getElementById(`${prefix}Sphere`).value),
    cylinder: cyl,
    axis: axisRaw === "" ? null : parseInt(axisRaw, 10),
    add: addRaw === "" ? null : parseFloat(addRaw),
  };
}

async function saveRx(e) {
  e.preventDefault();
  const patientId = parseInt(document.getElementById("rxPatient").value, 10);
  if (!patientId) {
    alertBox(document.getElementById("pageAlert"), "Select a patient first.", "warning"); return;
  }
  const payload = {
    patient_id: patientId,
    od: eyePayload("od"),
    os: eyePayload("os"),
    pupillary_distance: document.getElementById("rxPd").value
      ? parseFloat(document.getElementById("rxPd").value) : null,
    lens_type: document.getElementById("rxLens").value || null,
    notes: document.getElementById("rxNotes").value.trim() || null,
  };
  try {
    if (editingRxId) await apiFetch(`/api/prescriptions/${editingRxId}`, { method: "PUT", body: payload });
    else {
      const out = await apiFetch("/api/prescriptions", { method: "POST", body: payload });
      alertBox(document.getElementById("pageAlert"), out.message, "success");
    }
    editingRxId = null;
    resetRxForm();
    loadRx();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

function resetRxForm() {
  ["odSphere", "odCylinder", "odAxis", "odAdd", "osSphere", "osCylinder", "osAxis",
   "osAdd", "rxPd", "rxNotes"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("odCylinder").value = "0.00";
  document.getElementById("osCylinder").value = "0.00";
  document.getElementById("rxLens").value = "";
  document.getElementById("rxSaveBtn").textContent = "Save Rx";
}

function viewRx(r) {
  // Prefill the form for editing (optometrist/admin only pages reach here)
  document.getElementById("rxPatient").value = r.patient_id;
  putEye("od", r); putEye("os", r);
  document.getElementById("rxPd").value = r.pupillary_distance ?? "";
  document.getElementById("rxLens").value = r.lens_type || "";
  document.getElementById("rxNotes").value = r.notes || "";
  editingRxId = r.id;
  document.getElementById("rxSaveBtn").textContent = "Update Rx";
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function putEye(p, r) {
  document.getElementById(`${p}Sphere`).value = fmtNum(r[`${p}_sphere`], 2) === "—" ? "" :
    Number(r[`${p}_sphere`]).toFixed(2);
  document.getElementById(`${p}Cylinder`).value =
    r[`${p}_cylinder`] === null ? "0.00" : Number(r[`${p}_cylinder`]).toFixed(2);
  document.getElementById(`${p}Axis`).value = r[`${p}_axis`] ?? "";
  document.getElementById(`${p}Add`).value = r[`${p}_add`] ?? "";
}

async function archiveRx(id) {
  if (!confirm("Archive this prescription? It will be hidden but audit-tracked.")) return;
  try {
    await apiFetch(`/api/prescriptions/${id}`, { method: "DELETE" });
    loadRx();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}
