/* Hawkeyes — appointments (book / list / status manage) */
"use strict";

const TIME_SLOTS = (() => {
  const slots = [];
  for (let h = 8; h <= 17; h++) {          // clinic hours 08:00–17:30
    slots.push(`${String(h).padStart(2, "0")}:00`, `${String(h).padStart(2, "0")}:30`);
  }
  return slots;
})();

let OPTOMETRISTS = [];

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;

  const isPatient = user.role === "patient";
  const isStaff = ["admin", "front_desk"].includes(user.role);

  document.getElementById("bookHeader").textContent =
    isPatient ? "Book My Appointment" : "Book for a Patient (walk-in)";
  document.getElementById("apptDate").min = new Date().toISOString().slice(0, 10);
  document.getElementById("apptTime").innerHTML =
    TIME_SLOTS.map(t => `<option value="${t}:00">${t}</option>`).join("");
  document.getElementById("apptForm").addEventListener("submit", book);

  if (isPatient) {
    // Patients book against their own linked clinic record. Disable the picker
    // (not just hide it) so the required field cannot block form submission.
    document.getElementById("patientPickCol").classList.add("d-none");
    const patientPick = document.getElementById("apptPatient");
    patientPick.required = false;
    patientPick.disabled = true;
    document.getElementById("optomPickCol").classList.add("d-none");
    document.getElementById("todayOnlyWrap").classList.add("d-none");
  } else {
    await Promise.all([loadPatientOptions(), loadOptometristOptions()]);
  }

  if (!isPatient) {
    document.getElementById("apptTabs").classList.remove("d-none");
    document.getElementById("fuDays").addEventListener("change", loadFollowUps);
    document.querySelector('[data-bs-target="#tabFollowUps"]')
      .addEventListener("shown.bs.tab", loadFollowUps);
    document.getElementById("schDate").value = todayLocal();
    document.getElementById("schOptom").addEventListener("change", loadSchedule);
    document.getElementById("schDate").addEventListener("change", loadSchedule);
    document.querySelector('[data-bs-target="#tabSchedule"]')
      .addEventListener("shown.bs.tab", loadSchedule);
  }

  document.getElementById("todayOnly").addEventListener("change", loadAppointments);
  await loadAppointments();
});

async function loadPatientOptions() {
  try {
    const data = await apiFetch("/api/patients?page=1&page_size=100");
    document.getElementById("apptPatient").innerHTML =
      `<option value="">— select patient —</option>` +
      data.items.map(pt =>
        `<option value="${pt.id}">${pt.last_name}, ${pt.first_name} (${pt.hk_patient_id})</option>`)
        .join("");
  } catch (err) { alertBox(document.getElementById("pageAlert"), firstError(err)); }
}

async function loadOptometristOptions() {
  try {
    OPTOMETRISTS = await apiFetch("/api/appointments/optometrists");
    document.getElementById("apptOptom").innerHTML =
      `<option value="">— unassigned —</option>` +
      OPTOMETRISTS.map(o => `<option value="${o.id}">${o.full_name}</option>`).join("");

    // Schedule tab: desk/admin may pick any optometrist; optometrists see only self.
    const sch = document.getElementById("schOptom");
    sch.innerHTML = OPTOMETRISTS.map(o =>
      `<option value="${o.id}">${o.full_name}</option>`).join("");
    const me = getStoredUser();
    if (me && me.role === "optometrist") {
      sch.value = String(me.id);
      sch.disabled = true;
    }
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

async function book(e) {
  e.preventDefault();
  const user = getStoredUser();
  const payload = {
    appointment_date: document.getElementById("apptDate").value,
    start_time: document.getElementById("apptTime").value,
    purpose: document.getElementById("apptPurpose").value.trim(),
  };
  if (user.role !== "patient") {
    payload.patient_id = parseInt(document.getElementById("apptPatient").value, 10) || null;
    payload.optometrist_id = parseInt(document.getElementById("apptOptom").value, 10) || null;
    if (!payload.patient_id) {
      alertBox(document.getElementById("pageAlert"), "Select a patient.", "warning"); return;
    }
  }
  try {
    const out = await apiFetch("/api/appointments", { method: "POST", body: payload });
    alertBox(document.getElementById("pageAlert"), out.message, "success");
    document.getElementById("apptPurpose").value = "";
    refreshAppointmentViews();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
  }
}

async function loadAppointments() {
  const body = document.getElementById("apptBody");
  const user = getStoredUser();
  const isPatient = user.role === "patient";
  try {
    const today = document.getElementById("todayOnly").checked;
    const dateParam = today ? `?date=${new Date().toISOString().slice(0, 10)}` : "?upcoming_only=true";
    const rows = await apiFetch("/api/appointments" + dateParam);

    body.innerHTML = rows.length ? rows.map(a => `
      <tr>
        <td>${a.appointment_date}</td>
        <td>${(a.start_time || "").slice(0, 5)}</td>
        <td class="text-start">${a.patient_name}<br><span class="text-muted small">${a.hk_patient_id}</span></td>
        <td>${optometristCell(a, user)}</td>
        <td>${a.purpose}</td>
        <td><span class="badge bg-${a.source === "online" ? "info" : "secondary"}">${a.source.replace("_", " ")}</span></td>
        <td>${statusBadge(a.status)}</td>
        <td class="text-end" id="actions-${a.id}">
          ${actionButtons(a, user, isPatient)}
        </td>
      </tr>`).join("")
      : `<tr><td colspan="8" class="text-muted text-center py-4">No appointments found.</td></tr>`;
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    body.innerHTML = `<tr><td colspan="8" class="text-muted text-center py-4">Could not load appointments.</td></tr>`;
  }
}

async function loadFollowUps() {
  const body = document.getElementById("fuBody");
  const user = getStoredUser();
  const days = document.getElementById("fuDays").value;
  body.innerHTML = `<tr><td colspan="8" class="text-muted text-center py-4">Loading…</td></tr>`;
  try {
    const rows = await apiFetch(`/api/appointments/follow-ups?days=${days}`);
    body.innerHTML = rows.length ? rows.map(a => `
      <tr>
        <td><span class="badge bg-light text-dark">${a.days_away} day${a.days_away === 1 ? "" : "s"}</span></td>
        <td>${a.appointment_date}</td>
        <td>${(a.start_time || "").slice(0, 5)}</td>
        <td class="text-start">${a.patient_name}<br><span class="text-muted small">${a.hk_patient_id}</span></td>
        <td>${optometristCell(a, user)}</td>
        <td>${a.purpose}</td>
        <td>${statusBadge(a.status)}</td>
        <td>${reminderBadge(a)}</td>
      </tr>`).join("")
      : `<tr><td colspan="8" class="text-muted text-center py-4">No follow-ups in the next ${days} day${days === "1" ? "" : "s"}.</td></tr>`;
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    body.innerHTML = `<tr><td colspan="8" class="text-muted text-center py-4">Could not load follow-ups.</td></tr>`;
  }
}

function reminderBadge(a) {
  return a.reminded_at
    ? `<span class="badge bg-success" title="Reminder sent ${fmtDT(a.reminded_at)}">Sent</span>`
    : `<span class="badge bg-secondary">Pending</span>`;
}

function optometristCell(a, user) {
  const name = a.optometrist_name || "<span class='text-muted'>unassigned</span>";
  const canAssign = ["admin", "front_desk"].includes(user.role) &&
                    ["pending", "confirmed"].includes(a.status);
  if (!canAssign || !OPTOMETRISTS.length) return name;
  return `<select class="form-select form-select-sm" style="min-width: 170px;"
            onchange="assignOptometrist(${a.id}, this.value)">
      <option value="">— unassigned —</option>
      ${OPTOMETRISTS.map(o =>
        `<option value="${o.id}"${o.id === a.optometrist_id ? " selected" : ""}>${o.full_name}</option>`).join("")}
    </select>`;
}

async function assignOptometrist(id, value) {
  try {
    await apiFetch(`/api/appointments/${id}/optometrist`, {
      method: "PUT",
      body: { optometrist_id: value ? parseInt(value, 10) : null },
    });
    refreshAppointmentViews();
  } catch (err) {
    alertBox(document.getElementById("pageAlert"), firstError(err));
    refreshAppointmentViews();  // put the select back on the server value
  }
}

async function loadSchedule() {
  const body = document.getElementById("schBody");
  const sel = document.getElementById("schOptom");
  const date = document.getElementById("schDate").value;
  const optomId = parseInt(sel.value, 10);
  if (!optomId) {
    body.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-4">No optometrist accounts are available.</td></tr>`;
    return;
  }
  if (!date) {
    body.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-4">Choose a date.</td></tr>`;
    return;
  }
  const doctor = sel.options[sel.selectedIndex]?.textContent || "this optometrist";
  body.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-4">Loading…</td></tr>`;
  try {
    const rows = await apiFetch(`/api/appointments?date=${date}`);
    const assigned = rows.filter(a => a.optometrist_id === optomId);
    body.innerHTML = assigned.length ? assigned.map(a => `
      <tr>
        <td>${(a.start_time || "").slice(0, 5)}</td>
        <td class="text-start">${a.patient_name}<br><span class="text-muted small">${a.hk_patient_id}</span></td>
        <td>${a.purpose}</td>
        <td>${statusBadge(a.status)}</td>
      </tr>`).join("")
      : `<tr><td colspan="4" class="text-muted text-center py-4">No appointments assigned to ${doctor} on this date.</td></tr>`;
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
    body.innerHTML = `<tr><td colspan="4" class="text-muted text-center py-4">Could not load the schedule.</td></tr>`;
  }
}

function refreshAppointmentViews() {
  loadAppointments();
  if (document.getElementById("tabFollowUps").classList.contains("active")) loadFollowUps();
  if (document.getElementById("tabSchedule").classList.contains("active")) loadSchedule();
}

function actionButtons(a, user, isPatient) {
  const btn = (label, cls, fn, on = true) =>
    on ? `<button class="btn btn-sm btn-${cls}" onclick="${fn}">${label}</button>` : "";

  if (["completed", "cancelled"].includes(a.status)) return "";

  let html = "";
  if (["admin", "front_desk"].includes(user.role)) {
    html += btn("Confirm", "outline-primary", `setStatus(${a.id}, 'confirmed')`);
  }
  if (user.role === "optometrist" || ["admin", "front_desk"].includes(user.role)) {
    if (a.optometrist_id) html += btn("Complete", "outline-success", `setStatus(${a.id}, 'completed')`,
                                      user.role !== "optometrist" || a.optometrist_id === user.id);
  }
  html += btn("Cancel", "outline-danger", `cancelAppt(${a.id})`,
              isPatient ? a.status === "pending" || a.source === "online" : true);
  if (["admin"].includes(user.role) && a.status !== "completed") {
    html += btn("No-show", "outline-secondary", `setStatus(${a.id}, 'no_show')`);
  }
  return html || "<span class='text-muted small'>—</span>";
}

async function setStatus(id, status) {
  try {
    const body = { status };
    await apiFetch(`/api/appointments/${id}/status`, { method: "PUT", body });
    loadAppointments();
  } catch (err) { alertBox(document.getElementById("pageAlert"), firstError(err)); }
}

async function cancelAppt(id) {
  if (!confirm("Cancel this appointment?")) return;
  try {
    await apiFetch(`/api/appointments/${id}`, { method: "DELETE" });
    loadAppointments();
  } catch (err) { alertBox(document.getElementById("pageAlert"), firstError(err)); }
}
