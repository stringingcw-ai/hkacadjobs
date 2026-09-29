// HTTP handling: CORS, who is calling, daily limits, and the two actions.
//   POST {action: "profile", text | url}      → {ok, profile}
//   POST {action: "match", profile, prefs}    → {ok, matches, advice, considered, open_jobs, updated}
// Signed-in users only (a Supabase access token); the daily alert run calls with the service key.

import { type ClaudeClient, extractProfile, rankJobs, readWebPage } from "./claude.ts";
import type { Config } from "./config.ts";
import type { JobSet } from "./jobs.ts";
import { costUsd } from "./models.ts";
import { shortlist } from "./shortlist.ts";
import { addUsage, type ErrorCode, MatchError, NO_USAGE, type TokenUsage } from "./types.ts";
import { quotaError, type UsageOutcome, type UsageStore } from "./usage.ts";
import { cleanMatches, parseRequest, redactContacts, sanitizeProfile } from "./validate.ts";

export interface User {
  id: string;
  email: string;
}

export interface Deps {
  config: Config;
  claude: () => ClaudeClient;
  jobs: { get(needIds?: string[]): Promise<JobSet> };
  usage: UsageStore;
  /** The signed-in (non-anonymous) user behind an access token, or null */
  verifyUser: (token: string) => Promise<User | null>;
  log: (entry: Record<string, unknown>) => void;
}

/** Jobs Claude looks at closely for a user, and for one day's alert */
const SHORTLIST_SIZE = 40;
const ALERT_SHORTLIST_SIZE = 10;
const MAX_BODY_CHARS = 64_000;

const STATUS: Record<ErrorCode, number> = {
  sign_in_required: 401,
  origin_not_allowed: 403,
  method_not_allowed: 405,
  bad_request: 400,
  too_large: 413,
  invalid_action: 400,
  text_too_short: 400,
  text_too_long: 400,
  url_invalid: 400,
  url_linkedin: 400,
  profile_invalid: 400,
  paused: 503,
  daily_limit: 429,
  budget_reached: 503,
  refused: 422,
  url_unreadable: 422,
  busy: 503,
  upstream_error: 502,
  jobs_unavailable: 503,
  usage_unavailable: 503,
  internal: 500,
};

const MESSAGES: Partial<Record<ErrorCode, string>> = {
  sign_in_required: "Please sign in to use CV matching.",
  origin_not_allowed: "Requests from this site are not allowed.",
  method_not_allowed: "Use POST.",
  bad_request: "The request could not be read.",
  too_large: "The request is too large.",
  paused: "CV matching is paused at the moment. Please try again later.",
  refused: "We couldn't analyse this automatically. Please try pasting your CV as plain text.",
  url_unreadable: "We couldn't read that page. Please upload your CV or paste its text instead.",
  busy: "The matching service is busy. Please try again in a minute.",
  upstream_error: "Something went wrong while analysing. Please try again.",
  jobs_unavailable: "The job listings couldn't be loaded. Please try again shortly.",
  usage_unavailable: "CV matching is unavailable at the moment. Please try again later.",
  internal: "Something went wrong. Please try again.",
};

function reply(status: number, body: unknown, headers: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });
}

function fail(code: ErrorCode, headers: Record<string, string>, message?: string): Response {
  return reply(STATUS[code], { ok: false, error: code, message: message ?? MESSAGES[code] ?? code }, headers);
}

/** CORS headers for an allowed browser origin, {} for a request without one, null if refused. */
function corsHeaders(origin: string | null, config: Config): Record<string, string> | null {
  if (!origin) return {};
  const allowed = config.allowedOrigins.includes(origin) ||
    (config.allowLocalhost && /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin));
  if (!allowed) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function sameSecret(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

type Caller = { kind: "service" } | { kind: "user"; id: string };

async function identify(req: Request, deps: Deps): Promise<Caller | null> {
  const token = req.headers.get("authorization")?.match(/^Bearer\s+(\S+)$/i)?.[1];
  if (!token) return null;
  if (sameSecret(token, deps.config.supabaseServiceKey)) return { kind: "service" };
  const user = await deps.verifyUser(token);
  return user ? { kind: "user", id: user.id } : null;
}

export function createHandler(deps: Deps): (req: Request) => Promise<Response> {
  return async (req) => {
    const started = Date.now();
    const cors = corsHeaders(req.headers.get("origin"), deps.config);
    if (cors === null) return fail("origin_not_allowed", {});
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "POST") return fail("method_not_allowed", cors);
    if (!deps.config.enabled) return fail("paused", cors);

    let caller: Caller | null;
    try {
      caller = await identify(req, deps);
    } catch (err) {
      deps.log({ event: "auth_failed", error: String(err) });
      return fail("internal", cors);
    }
    if (!caller) return fail("sign_in_required", cors);

    const raw = await req.text();
    if (raw.length > MAX_BODY_CHARS) return fail("too_large", cors);
    let body: unknown;
    try {
      body = JSON.parse(raw);
    } catch {
      return fail("bad_request", cors);
    }
    const request = parseRequest(body, caller.kind);
    if ("error" in request) return fail(request.error, cors, request.message);

    let status;
    try {
      status = await deps.usage.status(caller.kind === "user" ? caller.id : null);
    } catch (err) {
      deps.log({ event: "usage_status_failed", error: String(err) });
      return fail("usage_unavailable", cors);
    }
    const blocked = quotaError(request.action, caller.kind, status, deps.config.limits);
    if (blocked) return fail(blocked.code, cors, blocked.message);

    const model = deps.config.model;
    const action = caller.kind === "service" ? "alert" : request.action;
    let usage: TokenUsage = NO_USAGE;
    let outcome: UsageOutcome = "ok";
    let calledClaude = false;
    try {
      if (request.action === "profile") {
        calledClaude = true;
        let text = request.text ?? "";
        if (request.url) {
          const page = await readWebPage(deps.claude(), model, request.url);
          usage = addUsage(usage, page.usage);
          text = page.notes;
        }
        const extracted = await extractProfile(deps.claude(), model, redactContacts(text));
        usage = addUsage(usage, extracted.usage);
        const profile = sanitizeProfile(extracted.profile);
        if (!profile) throw new MatchError("upstream_error", "Claude's profile did not match the schema");
        return reply(200, { ok: true, profile }, cors);
      }

      const jobs = await deps.jobs.get(request.onlyIds);
      const alert = caller.kind === "service";
      const candidates = shortlist(jobs.index, request.profile, {
        limit: alert ? ALERT_SHORTLIST_SIZE : SHORTLIST_SIZE,
        roleType: request.prefs.role_type,
        unis: request.prefs.unis,
        onlyIds: request.onlyIds,
        minMatched: alert ? 2 : 1,
      });
      const summary = { ok: true, open_jobs: jobs.open.length, updated: jobs.updated, considered: candidates.length };
      if (!candidates.length) return reply(200, { ...summary, matches: [], advice: "" }, cors);

      calledClaude = true;
      const ranked = await rankJobs(deps.claude(), model, request.profile, candidates.map((c) => c.job), request.limit);
      usage = addUsage(usage, ranked.usage);
      const { matches, advice } = cleanMatches(
        ranked.ranking,
        new Set(candidates.map((c) => c.job.id)),
        request.limit,
        request.minScore,
      );
      return reply(200, { ...summary, matches, advice }, cors);
    } catch (err) {
      const error = err instanceof MatchError ? err : new MatchError("internal", String(err));
      usage = addUsage(usage, error.usage);
      outcome = error.code === "refused" ? "refused" : error.code === "url_unreadable" ? "unreadable" : "error";
      if (outcome === "error") deps.log({ event: "error", action, code: error.code, detail: error.message });
      return fail(error.code, cors);
    } finally {
      const cost = costUsd(model, usage);
      if (calledClaude) {
        try {
          await deps.usage.record({
            user_id: caller.kind === "user" ? caller.id : null,
            action,
            model,
            input_tokens: usage.input + usage.cacheWrite + usage.cacheRead,
            output_tokens: usage.output,
            cost_usd: cost,
            outcome,
          });
        } catch (err) {
          deps.log({ event: "usage_record_failed", error: String(err) });
        }
      }
      // Never the CV, the profile or who asked
      deps.log({
        event: "request",
        action,
        outcome,
        ms: Date.now() - started,
        input_tokens: usage.input,
        output_tokens: usage.output,
        cost_usd: cost,
      });
    }
  };
}
