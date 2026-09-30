// The open jobs, read from the site's own jobs.csv (written daily by scraper/scraper.py).

import { parse } from "@std/csv";
import { buildIndex, type JobIndex } from "./shortlist.ts";
import { MatchError } from "./types.ts";

export interface Job {
  id: string;
  title: string;
  rank: string;
  university: string;
  university_full: string;
  department: string;
  deadline: string;
  deadline_note: string;
  position_type: string;
  date_added: string;
  is_new: boolean;
  /** From the AI summary's sections (see scraper/summaries.py) */
  duties: string[];
  requirements: string[];
  appointment: string;
  /** Start of a raw description that was never summarised */
  other: string;
}

/** Same markers as descriptionHtml() in index.html: text from a bot check, not the ad. */
const BOT_MARKERS = ["security check", "not a bot", "verify that you are", "cloudflare", "complete the security"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function squash(text: string | undefined): string {
  return (text ?? "").replace(/\s+/g, " ").trim();
}

/** Today's date in Hong Kong, the calendar the scraper uses. */
export function hkDate(now: Date): string {
  return new Date(now.getTime() + 8 * 3600_000).toISOString().slice(0, 10);
}

/** The rule in is_active() in scraper/generate_job_pages.py: open unless its deadline date has passed. */
export function isOpen(job: Pick<Job, "deadline">, today: string): boolean {
  return !(ISO_DATE.test(job.deadline) && job.deadline < today);
}

/** Splits a summary's `**Section**` + `•` bullets format; anything else is kept as raw text. */
export function parseDescription(
  raw: string | undefined,
): Pick<Job, "duties" | "requirements" | "appointment" | "other"> {
  const text = (raw ?? "").trim();
  const out = { duties: [] as string[], requirements: [] as string[], appointment: "", other: "" };
  if (!text || BOT_MARKERS.some((m) => text.toLowerCase().includes(m))) return out;
  if (!(text.includes("**") && text.includes("•"))) {
    out.other = squash(text).slice(0, 1500);
    return out;
  }
  for (const block of text.split(/\n\s*\n/)) {
    const [first, ...rest] = block.split("\n");
    const header = first.replaceAll("**", "").trim().toLowerCase();
    const bullets = rest.map((l) => l.trim()).filter((l) => l.startsWith("•"))
      .map((l) => squash(l.replace(/^•\s*/, ""))).filter((b) => b && b.toLowerCase() !== "not specified");
    if (header.startsWith("duties")) out.duties = bullets;
    else if (header.startsWith("requirements")) out.requirements = bullets;
    else if (header.startsWith("appointment")) out.appointment = bullets.join("; ");
  }
  return out;
}

export function parseJobsCsv(text: string): Job[] {
  const rows = parse(text, { skipFirstRow: true }) as Record<string, string | undefined>[];
  return rows.filter((r) => r.id?.trim() && r.title?.trim()).map((r) => ({
    id: r.id!.trim(),
    title: squash(r.title),
    rank: squash(r.rank),
    university: squash(r.university),
    university_full: squash(r.university_full),
    department: squash(r.department),
    deadline: squash(r.deadline),
    deadline_note: squash(r.deadline_note),
    position_type: squash(r.position_type),
    date_added: squash(r.date_added),
    is_new: squash(r.is_new).toUpperCase() === "TRUE",
    ...parseDescription(r.description),
  }));
}

export interface JobSet {
  /** Every row of jobs.csv, including jobs whose deadline passed in the last 14 days */
  all: Map<string, Job>;
  /** Jobs still open today, with their search index */
  open: Job[];
  index: JobIndex;
  today: string;
  /** Latest date_added, i.e. the day of the last scrape */
  updated: string;
  loadedAt: number;
}

export interface JobsSourceOptions {
  url: string;
  fetch: typeof fetch;
  ttlMs?: number;
  now?: () => Date;
  log?: (message: string) => void;
}

/**
 * Loads jobs.csv and keeps it in memory for `ttlMs` (the function's instance is reused between
 * requests). Refetches, bypassing the CDN cache, when asked for job ids it doesn't know yet,
 * e.g. just after the daily data refresh.
 */
export class JobsSource {
  #cache: JobSet | null = null;
  #lastRefetch = 0;

  constructor(private readonly opts: JobsSourceOptions) {}

  async get(needIds: string[] = []): Promise<JobSet> {
    const now = this.opts.now?.() ?? new Date();
    const ttl = this.opts.ttlMs ?? 30 * 60_000;
    let set = this.#cache;
    if (!set || now.getTime() - set.loadedAt > ttl || set.today !== hkDate(now)) {
      set = await this.#load(false, now);
    }
    if (needIds.some((id) => !set!.all.has(id)) && now.getTime() - this.#lastRefetch > 60_000) {
      this.#lastRefetch = now.getTime();
      set = await this.#load(true, now);
    }
    return set;
  }

  async #load(bustCache: boolean, now: Date): Promise<JobSet> {
    const url = bustCache
      ? `${this.opts.url}${this.opts.url.includes("?") ? "&" : "?"}v=${now.getTime()}`
      : this.opts.url;
    try {
      const res = await this.opts.fetch(url, { signal: AbortSignal.timeout(20_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const jobs = parseJobsCsv(await res.text());
      if (!jobs.length) throw new Error("no jobs in the file");
      const today = hkDate(now);
      const open = jobs.filter((j) => isOpen(j, today));
      this.#cache = {
        all: new Map(jobs.map((j) => [j.id, j])),
        open,
        index: buildIndex(open),
        today,
        updated: jobs.reduce((max, j) => (j.date_added > max ? j.date_added : max), ""),
        loadedAt: now.getTime(),
      };
      return this.#cache;
    } catch (err) {
      // Yesterday's list is better than none
      if (this.#cache) {
        this.opts.log?.(`jobs.csv reload failed, using the cached copy: ${err}`);
        return this.#cache;
      }
      throw new MatchError("jobs_unavailable", `Could not load jobs.csv: ${err}`);
    }
  }
}
