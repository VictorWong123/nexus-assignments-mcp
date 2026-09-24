import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  SITE,
  REQUIRED_FUNCTIONS,
  buildLaunchUrl,
  extractLaunchUrl,
  fetchLaunchPage,
  generatePassport,
  md5,
  parseLaunchPayload,
  validateToken,
} from "./login.js";

function launchPayload(passport, token = "a".repeat(32), site = SITE) {
  return `moodlemobile://token=${btoa(`${md5(`${site}${passport}`)}:::${token}:::discard-me`)}`;
}

function hasCode(code) {
  return (error) => error.code === code;
}

function apiResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  };
}

test("MD5 matches standard vectors used by Moodle's passport check", () => {
  assert.equal(md5(""), "d41d8cd98f00b204e9800998ecf8427e");
  assert.equal(md5("abc"), "900150983cd24fb0d6963f7d28e17f72");
});

test("passport and launch URL are fixed to Nexus mobile login", () => {
  const passport = generatePassport({
    getRandomValues(array) {
      array.fill(42);
      return array;
    },
  });
  assert.match(passport, /^\d{18}$/);
  const url = new URL(buildLaunchUrl(passport));
  assert.equal(url.origin, SITE);
  assert.equal(url.pathname, "/admin/tool/mobile/launch.php");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    service: "moodle_mobile_app",
    passport,
    urlscheme: "moodlemobile",
    confirmed: "1",
  });
});

test("extracts one launch link and rejects missing or ambiguous responses", () => {
  const url = "moodlemobile://token=YWJjZA==";
  assert.equal(extractLaunchUrl(`<main><a href="${url}" id="launchapp">Open</a></main>`), url);
  assert.throws(() => extractLaunchUrl("<p>Sign in</p>"), hasCode("LAUNCH_LINK_MISSING"));
  assert.throws(
    () => extractLaunchUrl(`<a id="launchapp" href="${url}"></a><a href="${url}" id="launchapp"></a>`),
    hasCode("LAUNCH_LINK_AMBIGUOUS"),
  );
});

test("accepts the matching Moodle payload and rejects wrong site or passport", () => {
  const passport = "123456789012345678";
  assert.equal(parseLaunchPayload(launchPayload(passport), passport), "a".repeat(32));
  assert.throws(
    () => parseLaunchPayload(launchPayload(passport, "a".repeat(32), "https://evil.example"), passport),
    hasCode("PAYLOAD_MISMATCH"),
  );
  assert.throws(
    () => parseLaunchPayload(launchPayload(passport), "876543210987654321"),
    hasCode("PAYLOAD_MISMATCH"),
  );
  assert.throws(
    () => parseLaunchPayload("https://example.com/token=x", passport),
    hasCode("PAYLOAD_SCHEME"),
  );
  assert.throws(
    () => parseLaunchPayload("moodlemobile://token=%%%", passport),
    hasCode("PAYLOAD_ENCODING"),
  );
});

test("fetches the launch page with the signed-in Nexus session and no redirects or cache", async () => {
  const passport = "123456789012345678";
  const launchUrl = launchPayload(passport);
  let request;
  assert.equal(
    await fetchLaunchPage(passport, async (url, options) => {
      request = { url, options };
      return {
        ok: true,
        text: async () => `<a id="launchapp" href="${launchUrl}">Open</a>`,
      };
    }),
    launchUrl,
  );
  assert.equal(new URL(request.url).origin, SITE);
  assert.equal(request.options.credentials, "include");
  assert.equal(request.options.redirect, "error");
  assert.equal(request.options.cache, "no-store");
});

test("stops reading an oversized Nexus response", async () => {
  const passport = "123456789012345678";
  await assert.rejects(
    fetchLaunchPage(passport, async () => ({
      ok: true,
      headers: new Headers(),
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(1_000_001));
          controller.close();
        },
      }),
    })),
    hasCode("LAUNCH_SIZE"),
  );
});

test("validates identity with a no-cache, no-cookie, non-redirecting POST", async () => {
  let request;
  const result = await validateToken("a".repeat(32), async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      async text() {
        return JSON.stringify({
          userid: 7,
          fullname: "Student Example",
          sitename: "Nexus",
          siteurl: SITE,
          functions: REQUIRED_FUNCTIONS.map((name) => ({ name })),
        });
      },
    };
  });
  assert.deepEqual(result, {
    name: "Student Example",
    site: "Nexus",
    siteUrl: SITE,
    functionCount: REQUIRED_FUNCTIONS.length,
    requiredFunctionCount: REQUIRED_FUNCTIONS.length,
  });
  assert.equal(request.url, `${SITE}/webservice/rest/server.php`);
  assert.equal(request.options.redirect, "error");
  assert.equal(request.options.cache, "no-store");
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.body.get("wstoken"), "a".repeat(32));
  assert.equal(request.options.body.get("wsfunction"), "core_webservice_get_site_info");
});

test("reports required APIs missing from a valid student's token", async () => {
  await assert.rejects(
    validateToken("a".repeat(32), async () => ({
      ok: true,
      text: async () => JSON.stringify({
        userid: 7,
        fullname: "Student Example",
        sitename: "Nexus",
        siteurl: SITE,
        functions: [{ name: "core_webservice_get_site_info" }],
      }),
    })),
    (error) =>
      error.code === "API_FUNCTIONS" &&
      error.missingFunctions.includes("mod_assign_get_assignments"),
  );
});

test("reports API fetch, HTTP, JSON, Moodle, identity, and cancellation stages", async () => {
  await assert.rejects(
    validateToken("a".repeat(32), async () => { throw new TypeError("secret"); }),
    hasCode("API_FETCH"),
  );
  await assert.rejects(
    validateToken("a".repeat(32), async () => apiResponse("", 503)),
    (error) => error.code === "API_HTTP" && error.status === 503,
  );
  await assert.rejects(
    validateToken("a".repeat(32), async () => apiResponse("not-json")),
    hasCode("API_JSON"),
  );
  await assert.rejects(
    validateToken("a".repeat(32), async () =>
      apiResponse(JSON.stringify({ exception: "moodle_exception", message: "secret" }))),
    hasCode("API_MOODLE"),
  );
  await assert.rejects(
    validateToken("a".repeat(32), async () =>
      apiResponse(JSON.stringify({ userid: "wrong", fullname: "Student", siteurl: SITE, functions: [] }))),
    hasCode("API_IDENTITY"),
  );
  const cancelled = new DOMException("Cancelled", "AbortError");
  await assert.rejects(validateToken("a".repeat(32), async () => { throw cancelled; }), {
    name: "AbortError",
  });
});

test("manifest grants only the fixed Nexus host and no sensitive browser permissions", async () => {
  const manifest = JSON.parse(await readFile(new URL("./manifest.json", import.meta.url)));
  assert.deepEqual(manifest.host_permissions, [`${SITE}/*`]);
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.permissions, undefined);
  assert.equal(manifest.content_scripts, undefined);
  for (const forbidden of ["cookies", "scripting", "tabs", "webRequest", "<all_urls>"]) {
    assert.doesNotMatch(JSON.stringify(manifest), new RegExp(forbidden.replace(/[<>]/g, "\\$&")));
  }
});
