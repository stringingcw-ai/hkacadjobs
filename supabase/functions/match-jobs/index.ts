// Supabase Edge Function "match-jobs": analyses a signed-in user's CV or web page with Claude and
// suggests the open jobs that fit them best. Nothing from the CV is stored.
// Plan: CV_MATCH_PLAN.md. Setup and limits: README.md ("CV matching service").

import Anthropic from "@anthropic-ai/sdk";
import { loadConfig } from "./config.ts";
import { createHandler, type User } from "./handler.ts";
import { JobsSource } from "./jobs.ts";
import { isServiceKey, supabaseUsageStore } from "./usage.ts";

const config = loadConfig((name) => Deno.env.get(name));

function log(entry: Record<string, unknown>) {
  console.log(JSON.stringify({ fn: "match-jobs", ...entry }));
}

/** Checks an access token with Supabase Auth; anonymous sign-ins don't count as signed in. */
async function verifyUser(token: string): Promise<User | null> {
  const res = await fetch(`${config.supabaseUrl}/auth/v1/user`, {
    headers: { apikey: config.supabaseAnonKey, Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(8_000),
  });
  if (res.status >= 500) throw new Error(`Supabase Auth: HTTP ${res.status}`);
  if (!res.ok) return null;
  const user = await res.json();
  return user?.id && !user.is_anonymous ? { id: user.id, email: user.email ?? "" } : null;
}

let client: Anthropic | null = null;

Deno.serve(createHandler({
  config,
  claude: () => (client ??= new Anthropic({ apiKey: config.anthropicApiKey, maxRetries: 1 })),
  jobs: new JobsSource({ url: config.jobsCsvUrl, fetch, log: (message) => log({ event: "jobs", message }) }),
  usage: supabaseUsageStore(config.supabaseUrl, config.supabaseServiceKey),
  verifyUser,
  verifyServiceKey: (token) => isServiceKey(config.supabaseUrl, token),
  log,
}));
