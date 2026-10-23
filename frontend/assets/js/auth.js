/* Hawkeyes — login + identity-link registration */
"use strict";

const HOME_BY_ROLE = { admin: "/dashboard.html", optometrist: "/dashboard.html",
                       front_desk: "/dashboard.html", patient: "/dashboard.html" };

/* If a valid session exists, skip the login screen. */
window.addEventListener("DOMContentLoaded", () => {
  if (getToken() && getStoredUser()) window.location.href = "dashboard.html";
  if (qs("expired")) {
    alertBox(document.getElementById("loginAlert"),
      "Your session expired. Please log in again.", "warning");
  }
});

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const alertEl = document.getElementById("loginAlert");
  const btn = document.getElementById("loginBtn");
  btn.disabled = true;
  try {
    const data = await apiFetch("/api/auth/login", {
      method: "POST",
      body: {
        email: document.getElementById("loginEmail").value.trim(),
        password: document.getElementById("loginPassword").value,
      },
    });
    saveSession(data.token, data.user);
    window.location.href = HOME_BY_ROLE[data.user.role] || "dashboard.html";
  } catch (err) {
    alertBox(alertEl, firstError(err));
    btn.disabled = false;
  }
});

document.getElementById("registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const alertEl = document.getElementById("loginAlert");
  const btn = document.getElementById("registerBtn");
  btn.disabled = true;
  try {
    const data = await apiFetch("/api/auth/register", {
      method: "POST",
      body: {
        full_name: document.getElementById("regName").value.trim(),
        email: document.getElementById("regEmail").value.trim(),
        password: document.getElementById("regPassword").value,
        hk_patient_id: document.getElementById("regHkId").value.trim().toUpperCase(),
        date_of_birth: document.getElementById("regDob").value,
      },
    });
    saveSession(data.token, data.user);
    window.location.href = "dashboard.html";
  } catch (err) {
    alertBox(alertEl, firstError(err));
    btn.disabled = false;
  }
});
