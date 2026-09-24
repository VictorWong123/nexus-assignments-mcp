export const SITE = "https://nexus.union.edu";
const LOGIN_URL = `${SITE}/login/index.php`;
const LAUNCH_PATH = "/admin/tool/mobile/launch.php";
const API_URL = `${SITE}/webservice/rest/server.php`;
const MAX_LAUNCH_HTML_CHARS = 1_000_000;
const MAX_SITE_INFO_CHARS = 1_000_000;
const MAX_ENCODED_PAYLOAD_CHARS = 4_096;
const BLOCKED_LAUNCH_SCHEMES = new Set([
  "about",
  "chrome",
  "chrome-extension",
  "data",
  "devtools",
  "file",
  "http",
  "https",
  "javascript",
  "view-source",
]);
export const REQUIRED_FUNCTIONS = Object.freeze([
  "core_calendar_get_calendar_events",
  "core_course_get_contents",
  "core_course_get_enrolled_courses_by_timeline_classification",
  "core_webservice_get_site_info",
  "gradereport_overview_get_course_grades",
  "gradereport_user_get_grade_items",
  "mod_assign_get_assignments",
  "mod_assign_get_submission_status",
  "mod_forum_get_discussion_posts",
  "mod_forum_get_forum_discussions",
  "mod_forum_get_forums_by_courses",
  "mod_quiz_get_quizzes_by_courses",
]);

function connectionError(code, details = {}) {
  const error = new Error("Nexus connection failed");
  error.code = code;
  Object.assign(error, details);
  return error;
}

function responseStatus(response) {
  return Number.isInteger(response?.status) && response.status >= 100 && response.status <= 599
    ? response.status
    : null;
}

function add32(a, b) {
  return (a + b) >>> 0;
}

function rotateLeft(value, count) {
  return ((value << count) | (value >>> (32 - count))) >>> 0;
}

export function md5(value) {
  const source = new TextEncoder().encode(value);
  const length = Math.ceil((source.length + 9) / 64) * 64;
  const bytes = new Uint8Array(length);
  bytes.set(source);
  bytes[source.length] = 0x80;
  const bitLength = BigInt(source.length) * 8n;
  for (let index = 0; index < 8; index += 1) {
    bytes[length - 8 + index] = Number((bitLength >> BigInt(index * 8)) & 0xffn);
  }

  const shifts = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
  ];
  const constants = Array.from(
    { length: 64 },
    (_, index) => Math.floor(Math.abs(Math.sin(index + 1)) * 2 ** 32) >>> 0,
  );
  let h0 = 0x67452301;
  let h1 = 0xefcdab89;
  let h2 = 0x98badcfe;
  let h3 = 0x10325476;

  for (let offset = 0; offset < bytes.length; offset += 64) {
    const words = new Uint32Array(16);
    for (let index = 0; index < 16; index += 1) {
      const start = offset + index * 4;
      words[index] =
        bytes[start] |
        (bytes[start + 1] << 8) |
        (bytes[start + 2] << 16) |
        (bytes[start + 3] << 24);
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;

    for (let index = 0; index < 64; index += 1) {
      let mixed;
      let word;
      if (index < 16) {
        mixed = (b & c) | (~b & d);
        word = index;
      } else if (index < 32) {
        mixed = (d & b) | (~d & c);
        word = (5 * index + 1) % 16;
      } else if (index < 48) {
        mixed = b ^ c ^ d;
        word = (3 * index + 5) % 16;
      } else {
        mixed = c ^ (b | ~d);
        word = (7 * index) % 16;
      }
      const next = d;
      d = c;
      c = b;
      b = add32(
        b,
        rotateLeft(
          add32(add32(add32(a, mixed >>> 0), constants[index]), words[word]),
          shifts[index],
        ),
      );
      a = next;
    }

    h0 = add32(h0, a);
    h1 = add32(h1, b);
    h2 = add32(h2, c);
    h3 = add32(h3, d);
  }

  return [h0, h1, h2, h3]
    .flatMap((word) => [word, word >>> 8, word >>> 16, word >>> 24])
    .map((byte) => (byte & 0xff).toString(16).padStart(2, "0"))
    .join("");
}

export function generatePassport(random = crypto) {
  let passport = "";
  while (passport.length < 18) {
    const bytes = random.getRandomValues(new Uint8Array(18));
    for (const byte of bytes) {
      if (byte < 250 && passport.length < 18) passport += String(byte % 10);
    }
  }
  return passport;
}

export function buildLaunchUrl(passport) {
  if (!/^\d{18}$/.test(passport)) throw connectionError("LOGIN_ATTEMPT");
  const url = new URL(LAUNCH_PATH, SITE);
  url.search = new URLSearchParams({
    service: "moodle_mobile_app",
    passport,
    urlscheme: "moodlemobile",
    confirmed: "1",
  });
  return url.toString();
}

function anchorAttributes(tag) {
  const attributes = new Map();
  const pattern = /([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
  for (const match of tag.matchAll(pattern)) {
    const name = match[1].toLowerCase();
    if (attributes.has(name)) throw connectionError("LAUNCH_HTML");
    attributes.set(name, match[2] ?? match[3]);
  }
  return attributes;
}

export function extractLaunchUrl(html) {
  if (typeof html !== "string" || html.length > MAX_LAUNCH_HTML_CHARS) {
    throw connectionError("LAUNCH_HTML");
  }
  const matches = [];
  for (const tag of html.match(/<a\b[^>]{0,4096}>/gi) ?? []) {
    const attributes = anchorAttributes(tag);
    if (attributes.get("id") === "launchapp") matches.push(attributes.get("href"));
  }
  if (matches.length === 0 || !matches[0]) throw connectionError("LAUNCH_LINK_MISSING");
  if (matches.length > 1) throw connectionError("LAUNCH_LINK_AMBIGUOUS");
  return matches[0];
}

export function parseLaunchPayload(launchUrl, passport) {
  const prefix =
    typeof launchUrl === "string"
      ? /^([A-Za-z][A-Za-z0-9+.-]{0,63}):\/\/token=/.exec(launchUrl)
      : null;
  if (!prefix || BLOCKED_LAUNCH_SCHEMES.has(prefix[1].toLowerCase())) {
    throw connectionError("PAYLOAD_SCHEME");
  }
  const encoded = launchUrl.slice(prefix[0].length);
  const encodedMatch = /^[A-Za-z0-9+/]+={0,2}$/.exec(encoded);
  if (
    encoded.length > MAX_ENCODED_PAYLOAD_CHARS ||
    !encodedMatch ||
    encodedMatch[0] !== encoded ||
    encoded.length % 4 !== 0
  ) {
    throw connectionError("PAYLOAD_ENCODING");
  }

  let decoded;
  try {
    const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw connectionError("PAYLOAD_ENCODING");
  }
  const fields = decoded.split(":::");
  if (fields.length < 2 || fields.length > 3) throw connectionError("PAYLOAD_ENCODING");
  const [siteHash, token] = fields;
  fields.fill("");
  decoded = "";
  if (siteHash !== md5(`${SITE}${passport}`)) throw connectionError("PAYLOAD_MISMATCH");
  if (!/^[A-Za-z0-9]{16,128}$/.test(token)) throw connectionError("PAYLOAD_ENCODING");
  return token;
}

async function readBoundedText(response, maximumBytes, stage) {
  const declaredLength = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    await response.body?.cancel?.();
    throw connectionError(`${stage}_SIZE`);
  }
  if (!response.body?.getReader) {
    try {
      const text = await response.text();
      if (new TextEncoder().encode(text).length > maximumBytes) {
        throw connectionError(`${stage}_SIZE`);
      }
      return text;
    } catch (error) {
      if (error?.code) throw error;
      throw connectionError(`${stage}_BODY`);
    }
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let received = 0;
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      if (received > maximumBytes) {
        await reader.cancel();
        throw connectionError(`${stage}_SIZE`);
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } catch (error) {
    if (error?.code) throw error;
    try {
      await reader.cancel();
    } catch {
      // The response stream may already be closed.
    }
    throw connectionError(`${stage}_BODY`);
  } finally {
    reader.releaseLock();
  }
}

export async function fetchLaunchPage(passport, fetchImpl = fetch, signal) {
  let response;
  try {
    response = await fetchImpl(buildLaunchUrl(passport), {
      method: "GET",
      credentials: "include",
      redirect: "error",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw connectionError("LAUNCH_FETCH");
  }
  if (!response.ok) {
    throw connectionError("LAUNCH_HTTP", { status: responseStatus(response) });
  }
  const html = await readBoundedText(response, MAX_LAUNCH_HTML_CHARS, "LAUNCH");
  return extractLaunchUrl(html);
}

export async function validateToken(token, fetchImpl = fetch, signal) {
  const body = new URLSearchParams({
    wstoken: token,
    wsfunction: "core_webservice_get_site_info",
    moodlewsrestformat: "json",
  });
  let response;
  try {
    response = await fetchImpl(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw connectionError("API_FETCH");
  }
  if (!response.ok) throw connectionError("API_HTTP", { status: responseStatus(response) });
  const text = await readBoundedText(response, MAX_SITE_INFO_CHARS, "API");
  let info;
  try {
    info = JSON.parse(text);
  } catch {
    throw connectionError("API_JSON");
  }
  if (info?.exception) throw connectionError("API_MOODLE");
  let siteOrigin = null;
  try {
    siteOrigin = new URL(info?.siteurl).origin;
  } catch {
    // Identity validation below reports the fixed local diagnostic.
  }
  if (
    !info ||
    !Number.isInteger(info.userid) ||
    typeof info.fullname !== "string" ||
    !Array.isArray(info.functions) ||
    siteOrigin !== SITE
  ) {
    throw connectionError("API_IDENTITY");
  }
  const availableFunctions = new Set(
    info.functions.map((item) => item?.name).filter((name) => typeof name === "string"),
  );
  const missingFunctions = REQUIRED_FUNCTIONS.filter((name) => !availableFunctions.has(name));
  if (missingFunctions.length) {
    throw connectionError("API_FUNCTIONS", { missingFunctions });
  }
  return {
    name: info.fullname,
    site: info.sitename || "Union Nexus",
    siteUrl: SITE,
    functionCount: info.functions.length,
    requiredFunctionCount: REQUIRED_FUNCTIONS.length,
  };
}

export function loginUrl() {
  return LOGIN_URL;
}
