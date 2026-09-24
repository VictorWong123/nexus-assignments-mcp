import assert from "node:assert/strict";
import test from "node:test";
import { REQUIRED_FUNCTIONS, SITE, md5 } from "./login.js";

class FakeElement {
  constructor() {
    this.listeners = new Map();
    this.checked = false;
    this.disabled = false;
    this.textContent = "";
    this.className = "";
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener);
  }

  click() {
    return this.listeners.get("click")();
  }

  focus() {}
}

function launchResponse(url, scheme = "openlms") {
  const passport = new URL(url).searchParams.get("passport");
  const payload = btoa(`${md5(`${SITE}${passport}`)}:::${"a".repeat(32)}`);
  return {
    ok: true,
    text: async () => `<a id="launchapp" href="${scheme}://token=${payload}">Open</a>`,
  };
}

async function runFailure(name, fetchImpl) {
  const elements = Object.fromEntries(
    ["consent", "start", "finish", "cancel", "status"].map((id) => [id, new FakeElement()]),
  );
  elements.consent.checked = true;
  globalThis.document = {
    querySelector(selector) {
      return elements[selector.slice(1)];
    },
  };
  globalThis.window = { addEventListener() {} };
  globalThis.chrome = {
    windows: {
      create: async () => ({ id: 7 }),
      remove: async () => {},
    },
  };
  globalThis.fetch = fetchImpl;
  await import(`./connect.js?case=${name}`);
  await elements.start.click();
  await elements.finish.click();
  return elements.status.textContent;
}

test("connection UI reports the failing stage without exposing raw errors", async () => {
  const launchNetwork = await runFailure("launch-network", async () => {
    throw new TypeError("secret browser failure detail");
  });
  assert.match(launchNetwork, /\[LAUNCH_FETCH\]/);
  assert.doesNotMatch(launchNetwork, /secret browser failure detail/);

  const launchHttp = await runFailure("launch-http", async () => ({ ok: false, status: 403 }));
  assert.match(launchHttp, /\[LAUNCH_HTTP\].*403/s);

  let call = 0;
  const apiJson = await runFailure("api-json", async (url) => {
    call += 1;
    return call === 1 ? launchResponse(url) : { ok: true, text: async () => "not-json" };
  });
  assert.match(apiJson, /\[API_JSON\]/);
});

test("connection UI accepts a branded inert launch scheme after fixed Nexus API validation", async () => {
  let call = 0;
  const status = await runFailure("branded-success", async (url) => {
    call += 1;
    if (call === 1) return launchResponse(url, "OPENLMS");
    return {
      ok: true,
      text: async () => JSON.stringify({
        userid: 7,
        fullname: "Student Example",
        sitename: "Nexus",
        siteurl: SITE,
        functions: REQUIRED_FUNCTIONS.map((name) => ({ name })),
      }),
    };
  });
  assert.match(status, /^Connected as Student Example/);
  assert.match(status, /All 12 required APIs are available/);
});
