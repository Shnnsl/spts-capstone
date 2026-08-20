const API_BASE = window.SPTS_CONFIG.API_BASE_URL.replace(/\/$/, "");

const SPTS_AUTH_KEYS = Object.freeze({
  accessToken: "spts_access_token",
  currentUser: "spts_current_user",
  loginMessage: "spts_login_message"
});

async function login(identifier, password) {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: identifier.trim(),
      password
    })
  });

  if (!response.ok) {
    throw new Error(
      response.status === 401
        ? "Invalid username or password."
        : "Unable to sign in. Please try again."
    );
  }

  const session = await response.json();
  localStorage.setItem(SPTS_AUTH_KEYS.accessToken, session.access_token);

  try {
    const user = await fetchCurrentUser();
    saveSession(session.access_token, user);
    return user;
  } catch (error) {
    clearSession();
    throw error;
  }
}

function logout() {
  clearSession();
  window.location.replace("login.html");
}

function getAccessToken() {
  return localStorage.getItem(SPTS_AUTH_KEYS.accessToken);
}

function getStoredUser() {
  const storedUser = localStorage.getItem(SPTS_AUTH_KEYS.currentUser);
  if (!storedUser) return null;

  try {
    return JSON.parse(storedUser);
  } catch {
    localStorage.removeItem(SPTS_AUTH_KEYS.currentUser);
    return null;
  }
}

function saveSession(token, user) {
  localStorage.setItem(SPTS_AUTH_KEYS.accessToken, token);
  localStorage.setItem(SPTS_AUTH_KEYS.currentUser, JSON.stringify(user));
}

function clearSession() {
  localStorage.removeItem(SPTS_AUTH_KEYS.accessToken);
  localStorage.removeItem(SPTS_AUTH_KEYS.currentUser);
  localStorage.removeItem(SPTS_AUTH_KEYS.loginMessage);
}

async function fetchCurrentUser() {
  const response = await authenticatedFetch(`${API_BASE}/auth/me`);
  if (!response.ok) {
    throw new Error("Unable to validate the current session.");
  }

  const user = await response.json();
  const token = getAccessToken();
  if (token) saveSession(token, user);
  return user;
}

function isAuthenticated() {
  return Boolean(getAccessToken());
}

function normalizeRole(role) {
  return String(role || "").trim().toUpperCase();
}

async function authenticatedFetch(url, options = {}) {
  const token = getAccessToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers
  });

  if (response.status === 401) {
    clearSession();
    localStorage.setItem(
      SPTS_AUTH_KEYS.loginMessage,
      "Your session has expired. Please sign in again."
    );

    if (!window.location.pathname.endsWith("/login.html")) {
      window.location.replace("login.html");
    }
  }

  return response;
}

async function requireLogin() {
  if (!isAuthenticated()) {
    window.location.replace("login.html");
    return null;
  }

  try {
    const user = await fetchCurrentUser();
    revealProtectedPage();
    displayCurrentUser(user);
    return user;
  } catch {
    clearSession();
    window.location.replace("login.html");
    return null;
  }
}

async function requireRole(allowedRoles) {
  const user = await requireLogin();
  if (!user) return null;

  const normalizedRole = normalizeRole(user.role);
  const normalizedAllowedRoles = allowedRoles.map(normalizeRole);

  if (!normalizedAllowedRoles.includes(normalizedRole)) {
    localStorage.setItem(
      SPTS_AUTH_KEYS.loginMessage,
      "You do not have permission to access that dashboard."
    );
    redirectByRole(user);
    return null;
  }

  return user;
}

function redirectByRole(user) {
  const destinations = {
    LINE_WORKSTATION: "line.html",
    SUPERVISOR: "supervisor.html",
    MANAGER: "manager.html",
    ADMINISTRATOR: "admin.html"
  };

  const destination = destinations[normalizeRole(user?.role)] || "line.html";
  const currentPage = window.location.pathname.split("/").pop();

  if (currentPage !== destination) {
    window.location.replace(destination);
  }
}

function displayCurrentUser(user = getStoredUser()) {
  if (!user) return;

  document.querySelectorAll("[data-current-user]").forEach((element) => {
    element.textContent = [
      user.full_name || user.username,
      `@${user.username}`,
      user.role
    ].join(" · ");
  });

  document.querySelectorAll("[data-password-warning]").forEach((element) => {
    element.hidden = !user.must_change_password;
  });
}

function revealProtectedPage() {
  document.body?.classList.remove("auth-pending");
}
