// Checks what callers send, and cleans what Claude sends back, before either is used.

import {
  CAREER_STAGES,
  DEGREES,
  type ErrorCode,
  type Fit,
  type Match,
  type Prefs,
  type Profile,
  type Rank,
  RANKS,
  ROLE_TYPES,
  UNIVERSITIES,
} from "./types.ts";

export const TEXT_MIN = 200;
export const TEXT_MAX = 40_000;
/** Matches returned to a signed-in user */
export const USER_LIMIT = 12;

export type ParsedRequest =
  | { action: "profile"; text: string; url?: undefined }
  | { action: "profile"; url: string; text?: undefined }
  | { action: "match"; profile: Profile; prefs: Prefs; onlyIds?: string[]; limit: number; minScore: number };

export interface Invalid {
  error: ErrorCode;
  message: string;
}

function str(value: unknown, max: number): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "";
}

/** Trimmed, de-duplicated strings, at most `maxItems` of them */
function list(value: unknown, maxItems: number, maxLen = 80): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of value) {
    const s = str(item, maxLen);
    if (s && !seen.has(s.toLowerCase())) {
      seen.add(s.toLowerCase());
      out.push(s);
      if (out.length >= maxItems) break;
    }
  }
  return out;
}

function oneOf<T extends string>(value: unknown, options: readonly T[]): T | null {
  return typeof value === "string" && (options as readonly string[]).includes(value) ? (value as T) : null;
}

function intIn(value: unknown, min: number, max: number, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(max, Math.max(min, Math.round(value)))
    : fallback;
}

// ── CV text ────────────────────────────────────────────────────────────────────

export function cleanText(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    // deno-lint-ignore no-control-regex
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .replace(/<\/?document>/gi, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const EMAIL = /[\p{L}\p{N}._%+-]+@[\p{L}\p{N}-]+(?:\.[\p{L}\p{N}-]+)*\.\p{L}{2,}/gu;
const HKID = /\b[A-Z]{1,2}\d{6}\s?\(?[0-9A]\)?/g;
const PERSONAL_LINE =
  /(\b(?:date of birth|d\.o\.b\.?|dob|age|gender|sex|marital status|nationality|religion|hkid(?: no\.?| number)?|passport(?: no\.?| number)?|id card(?: no\.?| number)?)|出生日期|年齡|性別|國籍|婚姻狀況|宗教|身份證(?:號碼)?)[ \t]*[:：][^\n]*/gi;
const INTL_PHONE = /\+\s?\d[\d\s().-]{6,}\d/g;
const HK_PHONE = /(?<![\d-])(?:\(?852\)?[\s-]?)?([2-9]\d{3})[\s-]?(\d{4})(?![\d-])/g;
const YEAR = /^(19|20)\d\d$/;

/**
 * Removes contact details and personal particulars that matching never needs: email
 * addresses, phone numbers, HKID numbers and lines such as "Date of birth: …". The site
 * does this in the browser too; this is the backstop.
 */
export function redactContacts(text: string): string {
  return text
    .replace(EMAIL, "[email]")
    .replace(HKID, "[id]")
    .replace(PERSONAL_LINE, (_m, label: string) => `${label}: [removed]`)
    .replace(INTL_PHONE, (m) => {
      const digits = m.replace(/\D/g, "").length;
      return digits >= 8 && digits <= 15 ? "[phone]" : m;
    })
    // An 8-digit Hong Kong number, but not a year range such as 2019-2023
    .replace(HK_PHONE, (m, a: string, b: string) => (YEAR.test(a) && YEAR.test(b) ? m : "[phone]"));
}

// ── Web address ────────────────────────────────────────────────────────────────

const BAD_URL: Invalid = {
  error: "url_invalid",
  message: "Enter the address of your personal or academic web page, e.g. https://www.example.com/about",
};

/** A public http(s) page; LinkedIn is not supported. */
export function checkUrl(raw: string): { url: string } | Invalid {
  let text = raw.trim();
  if (!text || text.length > 500) return BAD_URL;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `https://${text}`;
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return BAD_URL;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return BAD_URL;
  if (url.username || url.password || (url.port && url.port !== "80" && url.port !== "443")) return BAD_URL;
  const host = url.hostname.toLowerCase();
  if (host === "linkedin.com" || host.endsWith(".linkedin.com") || host === "lnkd.in") {
    return {
      error: "url_linkedin",
      message: "LinkedIn profiles can't be read here. Please upload your CV or paste its text instead.",
    };
  }
  if (
    !host.includes(".") || host.startsWith("[") || /^\d+(\.\d+){3}$/.test(host) ||
    /(^|\.)(localhost|local|internal|lan|home|corp)$/.test(host)
  ) return BAD_URL;
  url.hash = "";
  return { url: url.toString() };
}

// ── Profile and preferences ────────────────────────────────────────────────────

/** A profile from a caller (possibly edited on the site), or null if it isn't one. */
export function sanitizeProfile(input: unknown): Profile | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const p = input as Record<string, unknown>;
  const career_stage = oneOf(p.career_stage, CAREER_STAGES);
  const highest_degree = oneOf(p.highest_degree, DEGREES);
  const role_type = oneOf(p.role_type, ROLE_TYPES);
  if (!career_stage || !highest_degree || !role_type) return null;
  const ranks = Array.isArray(p.suitable_ranks)
    ? [...new Set(p.suitable_ranks.filter((r): r is Rank => (RANKS as readonly unknown[]).includes(r)))]
    : [];
  return {
    looks_like_cv: p.looks_like_cv !== false,
    headline: str(p.headline, 150),
    summary: str(p.summary, 800),
    career_stage,
    highest_degree,
    years_experience: intIn(p.years_experience, 0, 60, 0),
    role_type,
    suitable_ranks: ranks,
    disciplines: list(p.disciplines, 6),
    specialisms: list(p.specialisms, 15),
    skills: list(p.skills, 20),
    languages: list(p.languages, 8, 40),
    search_terms: list(p.search_terms, 50),
  };
}

export function hasTopics(p: Profile): boolean {
  return p.disciplines.length + p.specialisms.length + p.search_terms.length + p.skills.length > 0;
}

export function parsePrefs(input: unknown): Prefs {
  const p = input && typeof input === "object" ? (input as Record<string, unknown>) : {};
  const unis = Array.isArray(p.unis)
    ? [...new Set(p.unis.filter((u): u is string => UNIVERSITIES.has(u as string)))]
    : [];
  return { role_type: oneOf(p.role_type, ROLE_TYPES) ?? undefined, unis };
}

// ── Requests ───────────────────────────────────────────────────────────────────

export function parseRequest(body: unknown, caller: "user" | "service"): ParsedRequest | Invalid {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { error: "bad_request", message: "Send a JSON object." };
  }
  const b = body as Record<string, unknown>;
  if (b.action === "profile") {
    const hasText = typeof b.text === "string" && b.text.trim() !== "";
    const hasUrl = typeof b.url === "string" && b.url.trim() !== "";
    if (hasText === hasUrl) return { error: "bad_request", message: "Send either your CV text or a web address." };
    if (hasUrl) {
      const checked = checkUrl(b.url as string);
      return "error" in checked ? checked : { action: "profile", url: checked.url };
    }
    const text = cleanText(b.text as string);
    if (text.length < TEXT_MIN) {
      return { error: "text_too_short", message: "That's too short for a CV. Please include your whole CV." };
    }
    if (text.length > TEXT_MAX) {
      return { error: "text_too_long", message: "Your CV is too long. Please shorten it to about 15 pages." };
    }
    return { action: "profile", text };
  }
  if (b.action === "match") {
    const profile = sanitizeProfile(b.profile);
    if (!profile || !hasTopics(profile)) {
      return {
        error: "profile_invalid",
        message: "Your profile is missing or incomplete. Please analyse your CV again.",
      };
    }
    const prefs = parsePrefs(b.prefs);
    if (caller === "service") {
      const onlyIds = Array.isArray(b.only_ids)
        ? b.only_ids.filter((id): id is string => typeof id === "string" && id.length <= 100).slice(0, 500)
        : undefined;
      return {
        action: "match",
        profile,
        prefs,
        onlyIds,
        limit: intIn(b.limit, 1, 20, 5),
        minScore: intIn(b.min_score, 0, 100, 65),
      };
    }
    return { action: "match", profile, prefs, limit: USER_LIMIT, minScore: 0 };
  }
  return { error: "invalid_action", message: 'action must be "profile" or "match".' };
}

// ── Claude's ranking ───────────────────────────────────────────────────────────

function fitFor(score: number): Fit {
  return score >= 85 ? "strong" : score >= 70 ? "good" : "possible";
}

/**
 * Keeps only jobs that were on the shortlist, once each, best first. The fit label is
 * derived from the score so the two always agree.
 */
export function cleanMatches(
  raw: unknown,
  allowed: ReadonlySet<string>,
  limit: number,
  minScore: number,
): { matches: Match[]; advice: string } {
  const r = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const seen = new Set<string>();
  const matches: Match[] = [];
  for (const item of Array.isArray(r.matches) ? r.matches : []) {
    if (!item || typeof item !== "object") continue;
    const m = item as Record<string, unknown>;
    const id = typeof m.job_id === "string" ? m.job_id.trim() : "";
    if (!allowed.has(id) || seen.has(id)) continue;
    const score = intIn(m.score, 0, 100, 0);
    const why = str(m.why, 400);
    if (score < minScore || !why) continue;
    seen.add(id);
    matches.push({ job_id: id, score, fit: fitFor(score), why, gaps: list(m.gaps, 2, 160) });
  }
  matches.sort((a, b) => b.score - a.score);
  return { matches: matches.slice(0, limit), advice: str(r.advice, 300) };
}
