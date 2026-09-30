// Per-account daily limits and the site-wide daily budget, kept in the match_usage table
// (supabase/2026-10-cv-match.sql). Only the service role can read or write that table.

import type { Limits } from "./config.ts";
import type { ErrorCode } from "./types.ts";

export type UsageAction = "profile" | "match" | "alert";
export type UsageOutcome = "ok" | "refused" | "unreadable" | "error";

export interface UsageRow {
  /** null for the daily alert run */
  user_id: string | null;
  action: UsageAction;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  outcome: UsageOutcome;
}

/** Today's use (Hong Kong day), from match_quota_status() */
export interface QuotaStatus {
  userProfiles: number;
  userMatches: number;
  siteCostUsd: number;
  alertCostUsd: number;
}

export interface UsageStore {
  status(userId: string | null): Promise<QuotaStatus>;
  record(row: UsageRow): Promise<void>;
}

export function supabaseUsageStore(baseUrl: string, serviceKey: string, fetchFn: typeof fetch = fetch): UsageStore {
  const headers = {
    apikey: serviceKey,
    Authorization: `Bearer ${serviceKey}`,
    "Content-Type": "application/json",
  };
  return {
    async status(userId) {
      const res = await fetchFn(`${baseUrl}/rest/v1/rpc/match_quota_status`, {
        method: "POST",
        headers,
        body: JSON.stringify({ p_user_id: userId }),
        signal: AbortSignal.timeout(8_000),
      });
      if (!res.ok) throw new Error(`match_quota_status: HTTP ${res.status} ${await res.text()}`);
      const d = await res.json();
      return {
        userProfiles: Number(d?.user_profiles) || 0,
        userMatches: Number(d?.user_matches) || 0,
        siteCostUsd: Number(d?.site_cost_usd) || 0,
        alertCostUsd: Number(d?.alert_cost_usd) || 0,
      };
    },
    async record(row) {
      const res = await fetchFn(`${baseUrl}/rest/v1/match_usage`, {
        method: "POST",
        headers: { ...headers, Prefer: "return=minimal" },
        body: JSON.stringify(row),
        signal: AbortSignal.timeout(8_000),
      });
      if (!res.ok) throw new Error(`match_usage insert: HTTP ${res.status} ${await res.text()}`);
    },
  };
}

export interface QuotaError {
  status: number;
  code: ErrorCode;
  message: string;
}

/** Why this request may not run now, or null if it may. */
export function quotaError(
  action: "profile" | "match",
  caller: "user" | "service",
  status: QuotaStatus,
  limits: Limits,
): QuotaError | null {
  if (caller === "service") {
    return status.alertCostUsd >= limits.alertDailyBudgetUsd
      ? { status: 503, code: "budget_reached", message: "Today's budget for match alerts has been used." }
      : null;
  }
  if (status.siteCostUsd >= limits.dailyBudgetUsd) {
    return {
      status: 503,
      code: "budget_reached",
      message: "CV matching has reached its limit for today. Please try again tomorrow.",
    };
  }
  if (action === "profile" && status.userProfiles >= limits.profilePerDay) {
    return {
      status: 429,
      code: "daily_limit",
      message: `You can analyse up to ${limits.profilePerDay} CVs a day. Please try again tomorrow.`,
    };
  }
  if (action === "match" && status.userMatches >= limits.matchPerDay) {
    return {
      status: 429,
      code: "daily_limit",
      message: `You can run up to ${limits.matchPerDay} matches a day. Please try again tomorrow.`,
    };
  }
  return null;
}
