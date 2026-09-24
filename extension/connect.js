import {
  fetchLaunchPage,
  generatePassport,
  loginUrl,
  parseLaunchPayload,
  validateToken,
} from "./login.js";

const consent = document.querySelector("#consent");
const start = document.querySelector("#start");
const finish = document.querySelector("#finish");
const cancel = document.querySelector("#cancel");
const status = document.querySelector("#status");
const NETWORK_TIMEOUT_MS = 30_000;
let attempt = null;

function show(message, kind = "") {
  status.textContent = message;
  status.className = kind;
  status.focus();
}

function errorMessage(error) {
  const messages = {
    LOGIN_ATTEMPT: "Chrome could not start a valid Nexus login attempt.",
    LAUNCH_FETCH: "Chrome could not retrieve the Nexus mobile-login result. A network failure and a blocked redirect look the same here.",
    LAUNCH_HTTP: "Nexus rejected the mobile-login request.",
    LAUNCH_SIZE: "Nexus returned an unexpectedly large mobile-login page.",
    LAUNCH_BODY: "Chrome could not read the Nexus mobile-login page.",
    LAUNCH_HTML: "Nexus returned an invalid mobile-login page.",
    LAUNCH_LINK_MISSING: "Nexus returned a page without the mobile-app connection link.",
    LAUNCH_LINK_AMBIGUOUS: "Nexus returned more than one mobile-app connection link.",
    PAYLOAD_SCHEME: "Nexus returned an unexpected mobile-app link type.",
    PAYLOAD_ENCODING: "Nexus returned a malformed mobile-app credential.",
    PAYLOAD_MISMATCH: "The Nexus credential did not match this login attempt.",
    API_FETCH: "Chrome could not reach the Nexus API.",
    API_HTTP: "Nexus rejected the API validation request.",
    API_SIZE: "Nexus returned an unexpectedly large API response.",
    API_BODY: "Chrome could not read the Nexus API response.",
    API_JSON: "Nexus returned an invalid API response.",
    API_MOODLE: "Nexus returned an error during API validation.",
    API_IDENTITY: "Nexus did not return a valid Union student identity.",
    API_FUNCTIONS: "Nexus did not grant every API required by this connector.",
  };
  const code = Object.hasOwn(messages, error?.code) ? error.code : "UNKNOWN";
  let message = `${messages[code] ?? "The Nexus connection failed at an unknown stage."} [${code}]`;
  if ((code === "LAUNCH_HTTP" || code === "API_HTTP") && error.status !== null) {
    message += ` HTTP ${error.status}`;
  }
  if (code === "API_FUNCTIONS") {
    message += `\nMissing required APIs:\n${error.missingFunctions.join("\n")}`;
  }
  return message;
}

function clearAttempt(target = attempt) {
  target?.controller.abort();
  if (attempt === target) attempt = null;
  finish.disabled = true;
  cancel.disabled = true;
  start.disabled = false;
}

start.addEventListener("click", async () => {
  if (!consent.checked) {
    show("Please confirm that you want to run the connection test.", "error");
    return;
  }
  clearAttempt();
  const active = {
    passport: generatePassport(),
    controller: new AbortController(),
    loginWindowId: null,
  };
  attempt = active;
  start.disabled = true;
  finish.disabled = false;
  cancel.disabled = false;
  show("Sign in through the Nexus window, then return here.");
  try {
    const loginWindow = await chrome.windows.create({
      url: loginUrl(),
      type: "popup",
      width: 620,
      height: 760,
    });
    if (attempt !== active) {
      if (loginWindow.id !== undefined) await chrome.windows.remove(loginWindow.id);
      return;
    }
    active.loginWindowId = loginWindow.id ?? null;
  } catch {
    if (attempt === active) {
      clearAttempt(active);
      show("Chrome could not open the Nexus login window.", "error");
    }
  }
});

finish.addEventListener("click", async () => {
  const active = attempt;
  if (!active) return;
  finish.disabled = true;
  show("Checking Nexus access…");
  let token = "";
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    active.controller.abort();
  }, NETWORK_TIMEOUT_MS);
  try {
    const launchUrl = await fetchLaunchPage(active.passport, fetch, active.controller.signal);
    token = parseLaunchPayload(launchUrl, active.passport);
    const result = await validateToken(token, fetch, active.controller.signal);
    if (attempt !== active || active.controller.signal.aborted) return;
    show(
      `Connected as ${result.name}\n${result.site} (${result.siteUrl})\nAll ${result.requiredFunctionCount} required APIs are available (${result.functionCount} total)`,
      "success",
    );
  } catch (error) {
    if (attempt !== active) return;
    if (timedOut) {
      show("Nexus took too long to respond. Start a new connection test.", "error");
    } else if (error?.name !== "AbortError") {
      show(errorMessage(error), "error");
    }
  } finally {
    clearTimeout(timeout);
    token = "";
    if (attempt === active) clearAttempt(active);
  }
});

cancel.addEventListener("click", async () => {
  const active = attempt;
  const windowId = active?.loginWindowId ?? null;
  clearAttempt(active);
  if (windowId !== null) {
    try {
      await chrome.windows.remove(windowId);
    } catch {
      // The student may already have closed the login window.
    }
  }
  show("Connection test cancelled. No Nexus credential was kept.");
});

window.addEventListener("pagehide", () => clearAttempt());
