// Shared types, and the site's labels the matcher must agree with.

/** Rank labels shown on the site (RANK_OPTIONS in index.html). */
export const RANKS = [
  "Senior Management",
  "Professor",
  "Associate Professor",
  "Assistant Professor",
  "Tenure-Track",
  "Postdoctoral",
  "Senior Lecturer/Lecturer",
  "Research Assistant/Associate",
  "Teaching Assistant",
  "Non-Academic",
] as const;
export type Rank = (typeof RANKS)[number];

/** Ranks the site counts as academic (ACADEMIC_RANKS in index.html). */
export const ACADEMIC_RANKS: ReadonlySet<string> = new Set([
  "Professor",
  "Associate Professor",
  "Assistant Professor",
  "Tenure-Track",
  "Postdoctoral",
  "Senior Lecturer/Lecturer",
  "Lecturer",
  "Senior Management",
  "Teaching Assistant",
  "Research Assistant/Associate",
  "Other",
]);

/** Institution codes (UNI_ORDER in index.html). */
export const UNIVERSITIES: ReadonlySet<string> = new Set([
  "HKU",
  "HKUST",
  "CUHK",
  "CityU",
  "PolyU",
  "HKBU",
  "LU",
  "EdUHK",
  "HKMU",
  "HKSYU",
  "HSU",
  "SFU",
  "HKUSPACE",
  "CPCE",
  "THEI",
  "VTC",
  "HKCHC",
]);

export const CAREER_STAGES = ["student", "early_career", "mid_career", "senior", "executive"] as const;
export const DEGREES = ["none", "secondary", "sub_degree", "bachelor", "master", "doctorate"] as const;
export const ROLE_TYPES = ["academic", "non_academic", "both"] as const;
export const FITS = ["strong", "good", "possible"] as const;

export type RoleType = (typeof ROLE_TYPES)[number];
export type Fit = (typeof FITS)[number];

/** What Claude understood from a CV. Never holds names, contact details or personal characteristics. */
export interface Profile {
  looks_like_cv: boolean;
  headline: string;
  summary: string;
  career_stage: (typeof CAREER_STAGES)[number];
  highest_degree: (typeof DEGREES)[number];
  years_experience: number;
  role_type: RoleType;
  suitable_ranks: Rank[];
  disciplines: string[];
  specialisms: string[];
  skills: string[];
  languages: string[];
  search_terms: string[];
}

/** Choices the user makes on top of their profile. */
export interface Prefs {
  role_type?: RoleType;
  unis: string[];
}

export interface Match {
  job_id: string;
  score: number;
  fit: Fit;
  why: string;
  gaps: string[];
}

export interface TokenUsage {
  input: number;
  output: number;
  cacheWrite: number;
  cacheRead: number;
}

export const NO_USAGE: TokenUsage = { input: 0, output: 0, cacheWrite: 0, cacheRead: 0 };

export function addUsage(a: TokenUsage, b: TokenUsage): TokenUsage {
  return {
    input: a.input + b.input,
    output: a.output + b.output,
    cacheWrite: a.cacheWrite + b.cacheWrite,
    cacheRead: a.cacheRead + b.cacheRead,
  };
}

export type ErrorCode =
  | "sign_in_required"
  | "origin_not_allowed"
  | "method_not_allowed"
  | "bad_request"
  | "too_large"
  | "invalid_action"
  | "text_too_short"
  | "text_too_long"
  | "url_invalid"
  | "url_linkedin"
  | "profile_invalid"
  | "paused"
  | "daily_limit"
  | "budget_reached"
  | "refused"
  | "url_unreadable"
  | "busy"
  | "upstream_error"
  | "jobs_unavailable"
  | "usage_unavailable"
  | "internal";

/** A failure with a code the site can show a message for. `usage` is what Claude billed before it. */
export class MatchError extends Error {
  constructor(
    readonly code: ErrorCode,
    message?: string,
    readonly usage: TokenUsage = NO_USAGE,
  ) {
    super(message ?? code);
    this.name = "MatchError";
  }
}
