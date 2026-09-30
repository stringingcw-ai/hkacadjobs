// Settings, read from the function's secrets (Supabase → Edge Functions → Secrets).

export interface Limits {
  /** CV analyses per account per Hong Kong day */
  profilePerDay: number;
  /** Match runs per account per Hong Kong day */
  matchPerDay: number;
  /** Site-wide Claude spend per day for users, in US$ */
  dailyBudgetUsd: number;
  /** Claude spend per day for the daily match-alert run, in US$ */
  alertDailyBudgetUsd: number;
}

export interface Config {
  enabled: boolean;
  model: string;
  jobsCsvUrl: string;
  allowedOrigins: string[];
  allowLocalhost: boolean;
  limits: Limits;
  anthropicApiKey: string;
  supabaseUrl: string;
  supabaseAnonKey: string;
  supabaseServiceKey: string;
}

export const DEFAULT_MODEL = "claude-sonnet-5-5";

const DEFAULT_LIMITS: Limits = {
  profilePerDay: 3,
  matchPerDay: 10,
  dailyBudgetUsd: 10,
  alertDailyBudgetUsd: 3,
};

function number(value: string | undefined, fallback: number): number {
  const n = Number.parseFloat(value ?? "");
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

function flag(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value.trim() === "") return fallback;
  return !["false", "0", "no", "off"].includes(value.trim().toLowerCase());
}

export function loadConfig(env: (name: string) => string | undefined): Config {
  return {
    enabled: flag(env("MATCH_ENABLED"), true),
    model: env("MATCH_MODEL")?.trim() || DEFAULT_MODEL,
    jobsCsvUrl: env("JOBS_CSV_URL")?.trim() || "https://www.hkacadjobs.org/jobs.csv",
    allowedOrigins: (env("ALLOWED_ORIGINS") ?? "https://www.hkacadjobs.org,https://hkacadjobs.org")
      .split(",").map((o) => o.trim().replace(/\/+$/, "")).filter(Boolean),
    allowLocalhost: flag(env("ALLOW_LOCALHOST"), true),
    limits: {
      profilePerDay: number(env("USER_PROFILE_PER_DAY"), DEFAULT_LIMITS.profilePerDay),
      matchPerDay: number(env("USER_MATCH_PER_DAY"), DEFAULT_LIMITS.matchPerDay),
      dailyBudgetUsd: number(env("DAILY_BUDGET_USD"), DEFAULT_LIMITS.dailyBudgetUsd),
      alertDailyBudgetUsd: number(env("ALERT_DAILY_BUDGET_USD"), DEFAULT_LIMITS.alertDailyBudgetUsd),
    },
    anthropicApiKey: env("ANTHROPIC_API_KEY") ?? "",
    // Provided to every Edge Function by Supabase
    supabaseUrl: (env("SUPABASE_URL") ?? "").replace(/\/+$/, ""),
    supabaseAnonKey: env("SUPABASE_ANON_KEY") ?? "",
    supabaseServiceKey: env("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  };
}
