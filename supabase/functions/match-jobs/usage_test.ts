import { assertEquals, assertRejects } from "@std/assert";
import { costUsd } from "./models.ts";
import { testConfig } from "./testing.ts";
import { quotaError, supabaseUsageStore } from "./usage.ts";

const limits = testConfig().limits;
const quiet = { userProfiles: 0, userMatches: 0, siteCostUsd: 0, alertCostUsd: 0 };

Deno.test("default limits", () => {
  assertEquals(limits, { profilePerDay: 3, matchPerDay: 10, dailyBudgetUsd: 10, alertDailyBudgetUsd: 3 });
  assertEquals(testConfig({ USER_MATCH_PER_DAY: "4", DAILY_BUDGET_USD: "oops" }).limits.matchPerDay, 4);
  assertEquals(testConfig({ DAILY_BUDGET_USD: "oops" }).limits.dailyBudgetUsd, 10);
});

Deno.test("per-account daily limits and the site-wide budget", () => {
  assertEquals(quotaError("profile", "user", quiet, limits), null);
  assertEquals(quotaError("profile", "user", { ...quiet, userProfiles: 3 }, limits)?.code, "daily_limit");
  assertEquals(quotaError("match", "user", { ...quiet, userProfiles: 3 }, limits), null);
  assertEquals(quotaError("match", "user", { ...quiet, userMatches: 10 }, limits)?.status, 429);
  assertEquals(quotaError("match", "user", { ...quiet, siteCostUsd: 10 }, limits)?.code, "budget_reached");
  // The alert run has its own budget, and no per-account limits
  assertEquals(quotaError("match", "service", { ...quiet, siteCostUsd: 50, userMatches: 99 }, limits), null);
  assertEquals(quotaError("match", "service", { ...quiet, alertCostUsd: 3 }, limits)?.status, 503);
});

Deno.test("cost from token usage", () => {
  assertEquals(costUsd("claude-sonnet-5-5", { input: 1_000_000, output: 1_000_000, cacheWrite: 0, cacheRead: 0 }), 12);
  assertEquals(costUsd("claude-sonnet-5-5", { input: 0, output: 0, cacheWrite: 1_000_000, cacheRead: 1_000_000 }), 2.7);
  assertEquals(costUsd("claude-haiku-4-5", { input: 18_000, output: 5_000, cacheWrite: 0, cacheRead: 0 }), 0.043);
  assertEquals(costUsd("some-future-model", { input: 1_000_000, output: 0, cacheWrite: 0, cacheRead: 0 }), 10);
});

Deno.test("usage store talks to PostgREST with the service key", async () => {
  const sent: { url: string; init: RequestInit }[] = [];
  const store = supabaseUsageStore("https://p.supabase.co", "svc", (url, init) => {
    sent.push({ url: String(url), init: init! });
    return Promise.resolve(
      String(url).includes("rpc")
        ? Response.json({ user_profiles: 2, user_matches: "5", site_cost_usd: 1.5, alert_cost_usd: null })
        : new Response(null, { status: 201 }),
    );
  });
  assertEquals(await store.status("user-1"), { userProfiles: 2, userMatches: 5, siteCostUsd: 1.5, alertCostUsd: 0 });
  assertEquals(sent[0].url, "https://p.supabase.co/rest/v1/rpc/match_quota_status");
  assertEquals(JSON.parse(sent[0].init.body as string), { p_user_id: "user-1" });
  assertEquals((sent[0].init.headers as Record<string, string>).Authorization, "Bearer svc");

  const row = {
    user_id: null,
    action: "alert" as const,
    model: "claude-sonnet-5-5",
    input_tokens: 10,
    output_tokens: 2,
    cost_usd: 0.1,
    outcome: "ok" as const,
  };
  await store.record(row);
  assertEquals(sent[1].url, "https://p.supabase.co/rest/v1/match_usage");
  assertEquals(JSON.parse(sent[1].init.body as string), row);

  const broken = supabaseUsageStore(
    "https://p.supabase.co",
    "svc",
    () => Promise.resolve(new Response("no", { status: 404 })),
  );
  await assertRejects(() => broken.status(null), Error, "HTTP 404");
});
