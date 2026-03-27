const authStatus = document.getElementById("auth-status");

function updateAuthStatus(message, isError = false) {
  if (!authStatus) return;
  authStatus.textContent = message;
  authStatus.style.color = isError ? "#ff9a9a" : "";
}

async function submitJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

document.getElementById("login-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const nextPath = document.getElementById("next-path")?.value || "/dashboard";
    await submitJson("/api/session/login", {
      username: document.getElementById("username").value,
      password: document.getElementById("password").value,
      next_path: nextPath,
    });
    window.location.href = nextPath;
  } catch (error) {
    updateAuthStatus(error.message, true);
  }
});

document.getElementById("signup-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await submitJson("/api/session/signup", {
      full_name: document.getElementById("full-name").value,
      username: document.getElementById("signup-username").value,
      email: document.getElementById("signup-email").value,
      password: document.getElementById("signup-password").value,
    });
    window.location.href = "/dashboard";
  } catch (error) {
    updateAuthStatus(error.message, true);
  }
});

document.getElementById("forgot-password-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await submitJson("/api/session/forgot-password", {
      email: document.getElementById("forgot-email").value,
    });
    updateAuthStatus("If the account exists, a reset flow is now available.");
  } catch (error) {
    updateAuthStatus(error.message, true);
  }
});
