export const SITE = "https://nexus.union.edu";
const LOGIN_URL = `${SITE}/login/index.php`;
const LAUNCH_PATH = "/admin/tool/mobile/launch.php";
const API_URL = `${SITE}/webservice/rest/server.php`;
const MAX_LAUNCH_HTML_CHARS = 1_000_000;
const MAX_SITE_INFO_CHARS = 1_000_000;
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
  if (!/^\d{18}$/.test(passport)) throw new Error("Invalid login attempt");
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
    if (attributes.has(name)) throw new Error("Invalid Nexus response");
    attributes.set(name, match[2] ?? match[3]);
  }
  return attributes;
}

export function extractLaunchUrl(html) {
  if (typeof html !== "string" || html.length > MAX_LAUNCH_HTML_CHARS) {
    throw new Error("Invalid Nexus response");
  }
  const matches = [];
  for (const tag of html.match(/<a\b[^>]{0,4096}>/gi) ?? []) {
    const attributes = anchorAttributes(tag);
    if (attributes.get("id") === "launchapp") matches.push(attributes.get("href"));
  }
  if (matches.length !== 1 || !matches[0]) throw new Error("Nexus login was not completed");
  return matches[0];
}

export function parseLaunchPayload(launchUrl, passport) {
  const prefix = "moodlemobile://token=";
  if (typeof launchUrl !== "string" || !launchUrl.startsWith(prefix)) {
    throw new Error("Invalid Nexus launch response");
  }
  const encoded = launchUrl.slice(prefix.length);
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded) || encoded.length % 4 !== 0) {
    throw new Error("Invalid Nexus launch response");
  }

  let decoded;
  try {
    const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("Invalid Nexus launch response");
  }
  const fields = decoded.split(":::");
  if (fields.length < 2 || fields.length > 3) throw new Error("Invalid Nexus launch response");
  const [siteHash, token] = fields;
  fields.fill("");
  decoded = "";
  if (siteHash !== md5(`${SITE}${passport}`) || !/^[A-Za-z0-9]{16,128}$/.test(token)) {
    throw new Error("Nexus response did not match this login attempt");
  }
  return token;
}

async function readBoundedText(response, maximumBytes) {
  const declaredLength = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    await response.body?.cancel?.();
    throw new Error("Nexus response exceeded the size limit");
  }
  if (!response.body?.getReader) {
    const text = await response.text();
    if (new TextEncoder().encode(text).length > maximumBytes) {
      throw new Error("Nexus response exceeded the size limit");
    }
    return text;
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
        throw new Error("Nexus response exceeded the size limit");
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

export async function fetchLaunchPage(passport, fetchImpl = fetch, signal) {
  const response = await fetchImpl(buildLaunchUrl(passport), {
    method: "GET",
    credentials: "include",
    redirect: "error",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error("Nexus login check failed");
  const html = await readBoundedText(response, MAX_LAUNCH_HTML_CHARS);
  return extractLaunchUrl(html);
}

export async function validateToken(token, fetchImpl = fetch, signal) {
  const body = new URLSearchParams({
    wstoken: token,
    wsfunction: "core_webservice_get_site_info",
    moodlewsrestformat: "json",
  });
  const response = await fetchImpl(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error("Nexus API check failed");
  const text = await readBoundedText(response, MAX_SITE_INFO_CHARS);
  let info;
  try {
    info = JSON.parse(text);
  } catch {
    throw new Error("Invalid Nexus API response");
  }
  if (
    !info ||
    info.exception ||
    !Number.isInteger(info.userid) ||
    typeof info.fullname !== "string" ||
    !Array.isArray(info.functions) ||
    new URL(info.siteurl).origin !== SITE
  ) {
    throw new Error("Nexus API access is unavailable");
  }
  const availableFunctions = new Set(
    info.functions.map((item) => item?.name).filter((name) => typeof name === "string"),
  );
  const missingFunctions = REQUIRED_FUNCTIONS.filter((name) => !availableFunctions.has(name));
  if (missingFunctions.length) {
    const error = new Error("Nexus API access is incomplete");
    error.code = "UNSUPPORTED_API";
    error.missingFunctions = missingFunctions;
    throw error;
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
