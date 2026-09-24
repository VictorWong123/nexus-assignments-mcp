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
    } else if (error?.code === "UNSUPPORTED_API") {
      show(
        `Connected, but Nexus did not grant the APIs required by this connector:\n${error.missingFunctions.join("\n")}`,
        "error",
      );
    } else if (error?.name !== "AbortError") {
      show("Connection failed. Sign in to Nexus and start a new test.", "error");
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
