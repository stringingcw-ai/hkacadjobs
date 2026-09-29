// Picks the open jobs most likely to fit a profile, before Claude looks at them closely.
// Keyword scoring (BM25F) over each job's title, department and the ad's appointment, duties
// and requirements, with the profile's topics as the query, then adjusted for rank.

import type { Job } from "./jobs.ts";
import { ACADEMIC_RANKS, type Profile, type RoleType } from "./types.ts";

const CJK = "\\p{Script=Han}\\p{Script=Hiragana}\\p{Script=Katakana}\\p{Script=Hangul}";
/** A run of CJK characters, or a run of other letters and digits (keeping "c++", "c#") */
const TOKEN_RE = new RegExp(`[${CJK}]+|(?:(?![${CJK}])[\\p{L}\\p{N}])+[+#]*`, "gu");
const CJK_START = new RegExp(`^[${CJK}]`, "u");

// Only words that carry no meaning in a job ad; common but meaningful words ("research",
// "it") are left to the IDF weighting.
const STOPWORDS = new Set(
  (
    "a an and are as at be by for from has have in into is its of on or that the their this to " +
    "was were will with within etc eg ie able ability abilities applicant applicants candidate " +
    "candidates excellent good strong relevant related including preferably preferred required " +
    "requirement requirements responsible responsibilities duty duties qualification " +
    "qualifications experience experienced other various must should may"
  ).split(" "),
);

function stem(word: string): string {
  if (word.length > 4 && word.endsWith("ies")) return word.slice(0, -3) + "y";
  if (word.length > 3 && word.endsWith("s") && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
  return word;
}

/** Lowercased word stems; Chinese, Japanese and Korean text becomes overlapping character pairs. */
export function tokenize(text: string): string[] {
  const out: string[] = [];
  for (const [token] of text.normalize("NFKC").toLowerCase().matchAll(TOKEN_RE)) {
    if (CJK_START.test(token)) {
      const chars = [...token];
      if (chars.length === 1) out.push(token);
      for (let i = 0; i + 1 < chars.length; i++) out.push(chars[i] + chars[i + 1]);
    } else if (!STOPWORDS.has(token)) {
      out.push(stem(token));
    }
  }
  return out;
}

function normalize(text: string): string {
  return text.normalize("NFKC").toLowerCase();
}

// ── Index ──────────────────────────────────────────────────────────────────────

interface Field {
  tf: Map<string, number>;
  len: number;
}

interface Doc {
  job: Job;
  /** title, department, ad text */
  fields: [Field, Field, Field];
  text: [string, string, string];
}

export interface JobIndex {
  docs: Doc[];
  df: Map<string, number>;
  avgLen: [number, number, number];
}

const FIELD_WEIGHT = [3, 2, 1];
const FIELD_B = [0.3, 0.3, 0.75];
const K1 = 1.2;

function field(text: string): Field {
  const tokens = tokenize(text);
  const tf = new Map<string, number>();
  for (const t of tokens) tf.set(t, (tf.get(t) ?? 0) + 1);
  return { tf, len: tokens.length };
}

function adText(job: Job): string {
  return [job.appointment, ...job.duties, ...job.requirements, job.other].filter(Boolean).join("\n");
}

export function buildIndex(jobs: Job[]): JobIndex {
  const docs: Doc[] = jobs.map((job) => {
    const text: [string, string, string] = [job.title, job.department, adText(job)];
    return {
      job,
      fields: [field(text[0]), field(text[1]), field(text[2])],
      text: [normalize(text[0]), normalize(text[1]), normalize(text[2])],
    };
  });
  const df = new Map<string, number>();
  for (const doc of docs) {
    const seen = new Set<string>();
    for (const f of doc.fields) for (const t of f.tf.keys()) seen.add(t);
    for (const t of seen) df.set(t, (df.get(t) ?? 0) + 1);
  }
  const avg = (i: number) => docs.reduce((sum, d) => sum + d.fields[i].len, 0) / Math.max(1, docs.length) || 1;
  return { docs, df, avgLen: [avg(0), avg(1), avg(2)] };
}

// ── Query ──────────────────────────────────────────────────────────────────────

interface Query {
  tokens: Map<string, number>;
  phrases: { re: RegExp; weight: number }[];
}

/** How much each part of the profile counts when searching */
const TERM_WEIGHTS: [keyof Profile, number][] = [
  ["specialisms", 1.5],
  ["disciplines", 1.2],
  ["search_terms", 1],
  ["skills", 0.6],
];

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A multi-word term matched as a whole phrase (plural allowed); CJK terms match anywhere. */
function phraseRe(phrase: string): RegExp {
  const body = phrase.split(" ").map(escapeRe).join("\\s+");
  return CJK_START.test(phrase)
    ? new RegExp(body, "u")
    : new RegExp(`(?<![\\p{L}\\p{N}])${body}(?:e?s)?(?![\\p{L}\\p{N}])`, "u");
}

export function buildQuery(profile: Profile): Query {
  const tokens = new Map<string, number>();
  const phrases = new Map<string, number>();
  for (const [key, weight] of TERM_WEIGHTS) {
    for (const term of profile[key] as string[]) {
      const toks = tokenize(term);
      if (!toks.length) continue;
      // A term's words share its weight, so "single-cell RNA sequencing" doesn't outweigh
      // "bioinformatics"; the whole phrase earns its own bonus below.
      const w = weight / toks.length;
      for (const t of new Set(toks)) tokens.set(t, Math.min(3, (tokens.get(t) ?? 0) + w));
      if (toks.length > 1) {
        const text = normalize(term).replace(/\s+/g, " ").trim();
        phrases.set(text, Math.max(phrases.get(text) ?? 0, weight));
      }
    }
  }
  return { tokens, phrases: [...phrases].map(([p, weight]) => ({ re: phraseRe(p), weight })) };
}

// ── Scoring ────────────────────────────────────────────────────────────────────

function scoreDoc(doc: Doc, index: JobIndex, query: Query): { score: number; matched: number } {
  const n = index.docs.length;
  let score = 0;
  let matched = 0;
  for (const [token, weight] of query.tokens) {
    const df = index.df.get(token);
    if (!df) continue;
    let tf = 0;
    for (let i = 0; i < 3; i++) {
      const count = doc.fields[i].tf.get(token);
      if (count) {
        tf += FIELD_WEIGHT[i] * count /
          (1 - FIELD_B[i] + FIELD_B[i] * doc.fields[i].len / index.avgLen[i]);
      }
    }
    if (!tf) continue;
    matched++;
    const idf = Math.log(1 + (n - df + 0.5) / (df + 0.5));
    score += weight * idf * tf / (K1 + tf);
  }
  for (const { re, weight } of query.phrases) {
    if (re.test(doc.text[0]) || re.test(doc.text[1])) {
      score += 2 * weight;
      matched++;
    } else if (re.test(doc.text[2])) {
      score += 0.75 * weight;
      matched++;
    }
  }
  return { score, matched };
}

/** Jobs at a rank the profile doesn't suit still count, at a discount: rank labels are guessed from titles. */
function rankFactor(rank: string, suitable: ReadonlySet<string>): number {
  if (!suitable.size || suitable.has(rank)) return 1;
  if (rank === "Lecturer" && suitable.has("Senior Lecturer/Lecturer")) return 1; // older label
  if (!rank || rank === "Other") return 0.8;
  return 0.5;
}

/** "Other" covers both kinds of post, so it passes either role filter. */
function roleAllows(rank: string, role: RoleType): boolean {
  if (role === "both" || !rank || rank === "Other") return true;
  return role === "academic" ? ACADEMIC_RANKS.has(rank) : !ACADEMIC_RANKS.has(rank);
}

export interface ShortlistOptions {
  limit: number;
  /** Overrides the profile's role type */
  roleType?: RoleType;
  /** Institution codes; empty means all */
  unis?: string[];
  /** Only consider these job ids (the daily alert run passes the day's new jobs) */
  onlyIds?: string[];
  /** Minimum number of query terms a job must match */
  minMatched?: number;
}

export interface Candidate {
  job: Job;
  score: number;
  matched: number;
}

export function shortlist(index: JobIndex, profile: Profile, opts: ShortlistOptions): Candidate[] {
  const query = buildQuery(profile);
  const role = opts.roleType ?? profile.role_type;
  const unis = opts.unis?.length ? new Set(opts.unis) : null;
  const only = opts.onlyIds ? new Set(opts.onlyIds) : null;
  const suitable = new Set<string>(profile.suitable_ranks);
  const minMatched = opts.minMatched ?? 1;
  const out: Candidate[] = [];
  for (const doc of index.docs) {
    const { job } = doc;
    if (only && !only.has(job.id)) continue;
    if (unis && !unis.has(job.university)) continue;
    if (!roleAllows(job.rank, role)) continue;
    const { score, matched } = scoreDoc(doc, index, query);
    if (score <= 0 || matched < minMatched) continue;
    out.push({ job, score: score * rankFactor(job.rank, suitable), matched });
  }
  out.sort((a, b) =>
    b.score - a.score || b.job.date_added.localeCompare(a.job.date_added) || a.job.id.localeCompare(b.job.id)
  );
  return out.slice(0, opts.limit);
}
