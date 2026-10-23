/* Hawkeyes — dashboard (role-aware) */
"use strict";

document.addEventListener("DOMContentLoaded", async () => {
  const user = initProtectedPage();
  if (!user) return;
  document.getElementById("welcomeTitle").textContent =
    `Welcome, ${user.full_name.split(" ")[0]} (${user.role})`;

  try {
    if (user.role === "patient") await loadPatientHome(user);
    else await loadStaffHome();
  } catch (err) {
    if (!err.silent) alertBox(document.getElementById("pageAlert"), firstError(err));
  }
});

/* ---------- staff ---------- */
async function loadStaffHome() {
  document.getElementById("staffStats").classList.remove("d-none");
  const stats = await apiFetch("/api/stats/clinic");
  const tiles = document.querySelectorAll("#staffStats .display-6");
  [stats.total_patients, stats.total_prescriptions, stats.today_appointments,
   stats.upcoming_followups, stats.audits_today]
    .forEach((v, i) => { if (tiles[i]) tiles[i].textContent = v; });

  const appts = await apiFetch("/api/appointments?upcoming_only=true");
  document.getElementById("upcomingHeader").textContent = "Upcoming Appointments";
  fillUpcoming(appts.slice(0, 6));

  const recent = await apiFetch("/api/prescriptions/recent?limit=5");
  const panel = document.getElementById("rxPanel");
  panel.innerHTML = recentTable(recent);
}

/* ---------- online patient ---------- */
async function loadPatientHome(user) {
  [document.getElementById("statTile0")].forEach(el => el && el.remove());

  const [record, rx, appts] = await Promise.all([
    apiFetch("/api/patients/me"),
    apiFetch("/api/prescriptions/my"),
    apiFetch("/api/appointments?upcoming_only=true"),
  ]);

  document.getElementById("welcomeTitle").innerHTML +=
    `<span class="fs-6 text-muted ms-2">Hawkeyes ID: ${record.hk_patient_id}</span>`;
  document.getElementById("upcomingHeader").textContent = "My Upcoming Appointments";
  if (!appts.length) {
    document.getElementById("upcomingBody").innerHTML =
      `<tr><td colspan="4" class="text-center text-muted py-4">
        No upcoming visits — <a href="/appointments.html">book one</a></td></tr>`;
  } else {
    fillUpcoming(appts.slice(0, 6));
  }

  document.getElementById("rxHeader").textContent = "My Latest Prescription";
  const panel = document.getElementById("rxPanel");
  panel.innerHTML = rx.length
    ? rxCard(rx[0])
    : `<div class="text-center text-muted py-3">No prescription on record yet.</div>`;
}

/* ---------- render helpers ---------- */
function fillUpcoming(list) {
  document.getElementById("upcomingBody").innerHTML = list.length
    ? list.map(a => `<tr>
        <td>${a.appointment_date}</td>
        <td>${(a.start_time || "").slice(0, 5)}</td>
        <td>${a.patient_name}</td>
        <td>${statusBadge(a.status)}</td>
      </tr>`).join("")
    : `<tr><td colspan="4" class="text-center text-muted py-4">Nothing upcoming.</td></tr>`;
}

function recentTable(rows) {
  return rows.length
    ? `<table class="table table-sm table-hover mb-0 align-middle">
        <thead><tr><th>Date</th><th>Patient</th><th>OD (Sphere/Cyl/Ax/Add)</th><th>OS (Sphere/Cyl/Ax/Add)</th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td>${(r.exam_date || "").slice(0, 10)}</td>
          <td>${r.patient_name}<br><span class="text-muted small">${r.hk_patient_id}</span></td>
          <td class="rx-badge">${fmtNum(r.od_sphere,2)} / ${fmtNum(r.od_cylinder,2)} / ${fmtAxis(r.od_axis)} / ${fmtNum(r.od_add,2)}</td>
          <td class="rx-badge">${fmtNum(r.os_sphere,2)} / ${fmtNum(r.os_cylinder,2)} / ${fmtAxis(r.os_axis)} / ${fmtNum(r.os_add,2)}</td>
        </tr>`).join("")}</tbody></table>`
    : `<div class="text-center text-muted py-4">No prescriptions recorded yet.</div>`;
}

function rxCard(r) {
  return `<div class="p-3">
    <div class="d-flex justify-content-between mb-2">
      <span class="text-muted small">Exam: ${(r.exam_date || "").slice(0, 10)}</span>
      <span class="text-muted small">${r.optometrist || ""}</span>
    </div>
    <table class="table table-bordered table-sm text-center mb-2">
      <thead><tr><th></th><th>Sphere</th><th>Cylinder</th><th>Axis</th><th>Add</th></tr></thead>
      <tbody>
        <tr><td class="fw-bold">OD</td>
          <td>${fmtNum(r.od_sphere,2)}</td><td>${fmtNum(r.od_cylinder,2)}</td>
          <td>${fmtAxis(r.od_axis)}</td><td>${fmtNum(r.od_add,2)}</td></tr>
        <tr><td class="fw-bold">OS</td>
          <td>${fmtNum(r.os_sphere,2)}</td><td>${fmtNum(r.os_cylinder,2)}</td>
          <td>${fmtAxis(r.os_axis)}</td><td>${fmtNum(r.os_add,2)}</td></tr>
      </tbody>
    </table>
    <p class="small text-muted mb-0">${r.notes ? "Notes: " + r.notes : ""}</p>
  </div>`;
}
