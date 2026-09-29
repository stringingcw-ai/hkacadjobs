import { assert, assertEquals, assertStringIncludes } from "@std/assert";
import { createHandler, type Deps } from "./handler.ts";
import { apiError, FakeClaude, fixtureJobs, MemoryUsage, personas, reply, SERVICE_KEY, testConfig } from "./testing.ts";

const USER_TOKEN = "user-access-token";
const ORIGIN = "https://www.hkacadjobs.org";

async function setup(
  opts: { script?: ConstructorParameters<typeof FakeClaude>[0]; env?: Record<string, string> } = {},
) {
  const claude = new FakeClaude(opts.script ?? []);
  const usage = new MemoryUsage();
  const logs: Record<string, unknown>[] = [];
  const jobs = await fixtureJobs();
  const jobRequests: (string[] | undefined)[] = [];
  const deps: Deps = {
    config: testConfig(opts.env),
    claude: () => claude,
    jobs: {
      get: (needIds) => {
        jobRequests.push(needIds);
        return Promise.resolve(jobs);
      },
    },
    usage,
    verifyUser: (token) => Promise.resolve(token === USER_TOKEN ? { id: "user-1", email: "u@example.com" } : null),
    log: (entry) => logs.push(entry),
  };
  return { handler: createHandler(deps), claude, usage, logs, jobs, jobRequests };
}

function post(body: unknown, token: string | null = USER_TOKEN, origin: string | null = ORIGIN): Request {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (origin) headers.Origin = origin;
  return new Request("https://project.supabase.co/functions/v1/match-jobs", {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const CV_TEXT = "Registered nurse and nurse educator. Email jane@example.com, phone +852 5555 0101. " +
  "Twelve years in acute wards; five years of clinical teaching and simulation training for nursing students. ".repeat(
    3,
  );

Deno.test("CORS: the site and localhost are allowed; other origins are refused", async () => {
  const { handler } = await setup();
  const preflight = await handler(
    new Request("https://x/functions/v1/match-jobs", { method: "OPTIONS", headers: { Origin: ORIGIN } }),
  );
  assertEquals(preflight.status, 204);
  assertEquals(preflight.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assertStringIncludes(preflight.headers.get("Access-Control-Allow-Headers")!, "authorization");
  const local = await handler(
    new Request("https://x/", { method: "OPTIONS", headers: { Origin: "http://localhost:8000" } }),
  );
  assertEquals(local.status, 204);
  const evil = await handler(post({ action: "profile", text: CV_TEXT }, USER_TOKEN, "https://evil.example"));
  assertEquals(evil.status, 403);
  const noLocal = await setup({ env: { ALLOW_LOCALHOST: "false" } });
  assertEquals(
    (await noLocal.handler(
      new Request("https://x/", { method: "OPTIONS", headers: { Origin: "http://localhost:8000" } }),
    )).status,
    403,
  );
  assertEquals((await handler(new Request("https://x/", { method: "GET", headers: { Origin: ORIGIN } }))).status, 405);
});

Deno.test("only signed-in users (and the alert run) may call", async () => {
  const { handler, claude } = await setup();
  for (const token of [null, "anon-key", "forged"]) {
    const res = await handler(post({ action: "profile", text: CV_TEXT }, token));
    assertEquals(res.status, 401);
    assertEquals((await res.json()).error, "sign_in_required");
  }
  assertEquals(claude.calls.length, 0);
});

Deno.test("the kill switch pauses everything", async () => {
  const { handler } = await setup({ env: { MATCH_ENABLED: "false" } });
  const res = await handler(post({ action: "profile", text: CV_TEXT }));
  assertEquals(res.status, 503);
  assertEquals((await res.json()).error, "paused");
});

Deno.test("bad requests are rejected before any Claude call", async () => {
  const { handler, claude } = await setup();
  assertEquals((await handler(post("{not json"))).status, 400);
  assertEquals((await handler(post({ action: "profile", url: "https://www.linkedin.com/in/x" }))).status, 400);
  assertEquals((await handler(post("x".repeat(70_000)))).status, 413);
  const res = await handler(post({ action: "profile", text: "short" }));
  assertEquals(await res.json(), {
    ok: false,
    error: "text_too_short",
    message: "That's too short for a CV. Please include your whole CV.",
  });
  assertEquals(claude.calls.length, 0);
});

Deno.test("daily limits and the budget stop requests before Claude is called", async () => {
  const { handler, claude, usage } = await setup();
  usage.today = { userProfiles: 3 };
  const limited = await handler(post({ action: "profile", text: CV_TEXT }));
  assertEquals(limited.status, 429);
  assertEquals((await limited.json()).message, "You can analyse up to 3 CVs a day. Please try again tomorrow.");
  usage.today = { siteCostUsd: 10.5 };
  assertEquals((await handler(post({ action: "profile", text: CV_TEXT }))).status, 503);
  usage.down = true;
  const down = await handler(post({ action: "profile", text: CV_TEXT }));
  assertEquals((await down.json()).error, "usage_unavailable");
  assertEquals(claude.calls.length, 0);
});

Deno.test("profile from CV text: contact details never reach Claude; usage is recorded", async () => {
  const nurse = (await personas()).find((p) => p.name === "nurse_educator")!;
  const { handler, claude, usage, logs } = await setup({
    script: [reply({ json: nurse.profile, input: 2_500, output: 600 })],
  });
  const res = await handler(post({ action: "profile", text: CV_TEXT }));
  assertEquals(res.status, 200);
  assertEquals(res.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assertEquals(await res.json(), { ok: true, profile: nurse.profile });
  const sent = claude.userText(0);
  assert(!sent.includes("jane@example.com") && !sent.includes("5555 0101"), sent);
  assertStringIncludes(sent, "[email]");
  assertEquals(usage.rows, [{
    user_id: "user-1",
    action: "profile",
    model: "claude-sonnet-5-5",
    input_tokens: 2_500,
    output_tokens: 600,
    cost_usd: 0.011,
    outcome: "ok",
  }]);
  const logged = JSON.stringify(logs);
  assert(!logged.includes("nurse") && !logged.includes("user-1") && !logged.includes("u@example.com"), logged);
});

Deno.test("profile from a web page: two Claude calls, usage added up", async () => {
  const profile = (await personas())[0].profile;
  const notes =
    "Research Associate in genomics since 2024; PhD in Bioinformatics (2024); single-cell RNA-seq pipelines. " +
    "Contact: alex@example.com";
  const { handler, claude, usage } = await setup({ script: [reply({ text: notes }), reply({ json: profile })] });
  const res = await handler(post({ action: "profile", url: "people.example.edu/alex" }));
  assertEquals(res.status, 200);
  assertEquals((claude.calls[0].tools![0] as { allowed_domains: string[] }).allowed_domains, ["people.example.edu"]);
  assert(!claude.userText(1).includes("alex@example.com"));
  assertEquals(usage.rows[0].input_tokens, 2_000);
  assertEquals(usage.rows[0].action, "profile");
});

Deno.test("an unreadable page is a 422, recorded as unreadable", async () => {
  const { handler, usage } = await setup({ script: [reply({ text: "UNREADABLE" })] });
  const res = await handler(post({ action: "profile", url: "https://example.org/me" }));
  assertEquals(res.status, 422);
  assertEquals((await res.json()).error, "url_unreadable");
  assertEquals(usage.rows[0].outcome, "unreadable");
});

Deno.test("Claude being overloaded is a 503 that doesn't count against the user", async () => {
  const { handler, usage } = await setup({ script: [apiError(529)] });
  const res = await handler(post({ action: "profile", text: CV_TEXT }));
  assertEquals(res.status, 503);
  assertEquals((await res.json()).error, "busy");
  assertEquals(usage.rows[0].outcome, "error");
  assertEquals(usage.rows[0].cost_usd, 0);
});

Deno.test("match: Claude sees at most 40 shortlisted jobs and only those come back", async () => {
  const nurse = (await personas()).find((p) => p.name === "nurse_educator")!;
  let offered: string[] = [];
  const script = [(params: { messages: { content: unknown }[] }) => {
    offered = [...String(params.messages[0].content).matchAll(/<job id="([^"]+)">/g)].map((m) => m[1]);
    return reply({
      json: {
        matches: [
          { job_id: "CUHK-4d0399b959", score: 90, why: "Your clinical teaching matches.", gaps: [] },
          { job_id: "NOT-OFFERED", score: 99, why: "Invented.", gaps: [] },
          { job_id: "HKMU-260008U", score: 66, why: "Your MSc may fall short of a PhD.", gaps: ["PhD"] },
        ],
        advice: "Highlight your simulation teaching.",
      },
    });
  }];
  const { handler, usage, jobs } = await setup({ script: script as never });
  const res = await handler(post({ action: "match", profile: nurse.profile, prefs: {} }));
  assertEquals(res.status, 200);
  const body = await res.json();
  assert(offered.length > 0 && offered.length <= 40);
  assert(offered.includes("CUHK-4d0399b959"));
  assertEquals(body.matches.map((m: { job_id: string }) => m.job_id), ["CUHK-4d0399b959", "HKMU-260008U"]);
  assertEquals(body.matches[1], {
    job_id: "HKMU-260008U",
    score: 66,
    fit: "possible",
    why: "Your MSc may fall short of a PhD.",
    gaps: ["PhD"],
  });
  assertEquals(body.advice, "Highlight your simulation teaching.");
  assertEquals(body.considered, offered.length);
  assertEquals(body.open_jobs, jobs.open.length);
  assertEquals(body.updated, jobs.updated);
  assertEquals(usage.rows[0].action, "match");
});

Deno.test("match with nothing relevant: no Claude call and nothing recorded", async () => {
  const base = (await personas())[0].profile;
  const profile = { ...base, disciplines: ["Zzyzx"], specialisms: ["quuxology"], skills: [], search_terms: ["xyzzy"] };
  const { handler, claude, usage } = await setup();
  const res = await handler(post({ action: "match", profile }));
  assertEquals(await res.json(), {
    ok: true,
    open_jobs: 169,
    updated: (await fixtureJobs()).updated,
    considered: 0,
    matches: [],
    advice: "",
  });
  assertEquals(claude.calls.length, 0);
  assertEquals(usage.rows.length, 0);
});

Deno.test("the alert run: service key, today's jobs only, high bar, own budget", async () => {
  const english = (await personas()).find((p) => p.name === "english_lecturer")!;
  const ranking = {
    matches: [
      { job_id: "HKU-537450", score: 88, why: "Your EAP teaching fits.", gaps: [] },
      { job_id: "HKU-537451", score: 60, why: "Below the alert bar.", gaps: [] },
    ],
    advice: "",
  };
  const { handler, claude, usage, jobRequests } = await setup({ script: [reply({ json: ranking })] });
  const onlyIds = ["HKU-537450", "HKU-537451", "LU-3075"];
  const res = await handler(post({ action: "match", profile: english.profile, only_ids: onlyIds }, SERVICE_KEY, null));
  assertEquals(res.status, 200);
  assertEquals(res.headers.get("Access-Control-Allow-Origin"), null);
  const body = await res.json();
  assertEquals(body.matches.map((m: { job_id: string }) => m.job_id), ["HKU-537450"]);
  assertEquals(jobRequests[0], onlyIds);
  const offered = [...claude.userText(0).matchAll(/<job id="([^"]+)">/g)].map((m) => m[1]).sort();
  assertEquals(offered, ["HKU-537450", "HKU-537451"]);
  assertStringIncludes(claude.userText(0), "Choose up to 5 positions");
  assertEquals(usage.rows[0].action, "alert");
  assertEquals(usage.rows[0].user_id, null);

  usage.today = { alertCostUsd: 3 };
  const over = await handler(post({ action: "match", profile: english.profile, only_ids: onlyIds }, SERVICE_KEY, null));
  assertEquals(over.status, 503);
});
