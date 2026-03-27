const csrfToken = document.body.dataset.csrfToken || "";
const statusBox = document.getElementById("app-status");

function setStatus(message, isError = false) {
  if (!statusBox) return;
  statusBox.textContent = message;
  statusBox.style.color = isError ? "#ff9a9a" : "";
}

async function apiRequest(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, { ...options, headers });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `Request failed (${response.status})`);
  }
  return payload;
}

document.getElementById("logout-button")?.addEventListener("click", async () => {
  try {
    await apiRequest("/api/session/logout", { method: "POST" });
    window.location.href = "/";
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("disclosure-button")?.addEventListener("click", async () => {
  try {
    await apiRequest("/api/profile/acknowledge-disclosures", { method: "POST" });
    window.location.reload();
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelectorAll(".checkout-button").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const payload = await apiRequest("/api/billing/create-checkout-session", {
        method: "POST",
        body: JSON.stringify({ billing_cycle: button.dataset.cycle }),
      });
      window.location.href = payload.url;
    } catch (error) {
      setStatus(error.message, true);
    }
  });
});

document.getElementById("billing-portal-button")?.addEventListener("click", async () => {
  try {
    const payload = await apiRequest("/api/billing/create-portal-session", { method: "POST" });
    window.location.href = payload.url;
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("watchlist-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = document.getElementById("watchlist-name").value.trim();
  const symbols = document
    .getElementById("watchlist-symbols")
    .value.split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
  try {
    await apiRequest("/api/watchlists", {
      method: "POST",
      body: JSON.stringify({ name, symbols }),
    });
    window.location.reload();
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("rebuild-portfolio-button")?.addEventListener("click", async () => {
  try {
    await apiRequest("/api/model-portfolio/rebuild", { method: "POST" });
    window.location.reload();
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("refresh-market-button")?.addEventListener("click", async () => {
  try {
    await apiRequest("/api/admin/refresh-market", { method: "POST" });
    setStatus("Market state refreshed.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("profile-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const payload = Object.fromEntries(formData.entries());
  try {
    await apiRequest("/api/profile", { method: "POST", body: JSON.stringify(payload) });
    setStatus("Profile saved.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("password-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const payload = Object.fromEntries(formData.entries());
  try {
    await apiRequest("/api/account/change-password", { method: "POST", body: JSON.stringify(payload) });
    event.currentTarget.reset();
    setStatus("Password updated.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.getElementById("admin-user-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const payload = Object.fromEntries(formData.entries());
  try {
    await apiRequest("/api/admin/users", { method: "POST", body: JSON.stringify(payload) });
    window.location.reload();
  } catch (error) {
    setStatus(error.message, true);
  }
});
