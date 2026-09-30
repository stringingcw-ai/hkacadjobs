import { assert, assertEquals } from "@std/assert";
import { personas } from "./testing.ts";
import {
  checkUrl,
  cleanMatches,
  parsePrefs,
  parseRequest,
  redactContacts,
  sanitizeProfile,
  TEXT_MAX,
  USER_LIMIT,
} from "./validate.ts";

const CV = "Lecturer in nursing with ten years of clinical teaching experience. ".repeat(5);

Deno.test("profile requests need either CV text of a sensible length or a web address", () => {
  assertEquals(parseRequest({ action: "profile", text: `  ${CV}\r\n\r\n\r\n\r\nMore  ` }, "user"), {
    action: "profile",
    text: `${CV.trim()}\n\nMore`,
  });
  assertEquals(
    (parseRequest({ action: "profile", text: "Too short" }, "user") as { error: string }).error,
    "text_too_short",
  );
  assertEquals(
    (parseRequest({ action: "profile", text: "x".repeat(TEXT_MAX + 1) }, "user") as { error: string }).error,
    "text_too_long",
  );
  assertEquals((parseRequest({ action: "profile" }, "user") as { error: string }).error, "bad_request");
  assertEquals(
    (parseRequest({ action: "profile", text: CV, url: "https://a.example" }, "user") as { error: string }).error,
    "bad_request",
  );
  assertEquals(parseRequest({ action: "profile", url: "www.example.edu/~chan" }, "user"), {
    action: "profile",
    url: "https://www.example.edu/~chan",
  });
  assertEquals((parseRequest({ action: "delete" }, "user") as { error: string }).error, "invalid_action");
  assertEquals((parseRequest([1, 2], "user") as { error: string }).error, "bad_request");
});

Deno.test("web addresses: public http(s) pages only, and no LinkedIn", () => {
  assertEquals(checkUrl("https://people.example.edu/jdoe#top"), { url: "https://people.example.edu/jdoe" });
  for (
    const bad of [
      "ftp://example.com/cv",
      "http://localhost:3000",
      "http://192.168.1.10/cv",
      "https://intranet",
      "http://[::1]/",
      "https://user:pw@example.com",
      "https://example.com:8443/x",
      "http://printer.local/",
    ]
  ) {
    assertEquals((checkUrl(bad) as { error: string }).error, "url_invalid", bad);
  }
  for (const li of ["https://www.linkedin.com/in/someone", "hk.linkedin.com/in/someone", "https://lnkd.in/abc"]) {
    assertEquals((checkUrl(li) as { error: string }).error, "url_linkedin", li);
  }
});

Deno.test("contact details and personal particulars are removed; years and ids are kept", () => {
  const text = [
    "Email: jane.chan@example.com | Tel: +852 5555 0101 | (852) 2859-1234 | 9123 4567",
    "Date of birth: 1 January 1990",
    "出生日期：1990年5月1日",
    "Nationality: Martian",
    "HKID: A123456(7)",
    "PhD 2019-2023; ORCID 0000-0002-1825-0097; a 2,000-user network; HK$50,000 per month",
  ].join("\n");
  const out = redactContacts(text);
  for (
    const gone of [
      "jane.chan",
      "5555 0101",
      "2859-1234",
      "9123 4567",
      "1 January 1990",
      "1990年5月1日",
      "Martian",
      "A123456",
    ]
  ) {
    assert(!out.includes(gone), `still contains ${gone}: ${out}`);
  }
  for (const kept of ["2019-2023", "0000-0002-1825-0097", "2,000-user", "HK$50,000", "Date of birth: [removed]"]) {
    assert(out.includes(kept), `lost ${kept}: ${out}`);
  }
});

Deno.test("profiles from callers are cleaned; broken ones are rejected", async () => {
  const good = (await personas())[0].profile;
  assertEquals(sanitizeProfile(good), good);
  const messy = sanitizeProfile({
    ...good,
    years_experience: 99.4,
    suitable_ranks: ["Postdoctoral", "Emperor", "Postdoctoral"],
    search_terms: ["  genomics ", "Genomics", "", 42, "x".repeat(200)],
    extra: "ignored",
  })!;
  assertEquals(messy.years_experience, 60);
  assertEquals(messy.suitable_ranks, ["Postdoctoral"]);
  assertEquals(messy.search_terms, ["genomics", "x".repeat(80)]);
  assert(!("extra" in messy));
  assertEquals(sanitizeProfile({ ...good, role_type: "wizard" }), null);
  assertEquals(sanitizeProfile("profile"), null);
  const empty = { ...good, disciplines: [], specialisms: [], skills: [], search_terms: [] };
  assertEquals(
    (parseRequest({ action: "match", profile: empty }, "user") as { error: string }).error,
    "profile_invalid",
  );
});

Deno.test("match requests: users get fixed limits; the alert run can narrow the jobs", async () => {
  const profile = (await personas())[0].profile;
  const asUser = parseRequest(
    { action: "match", profile, prefs: { role_type: "both", unis: ["HKU", "Nowhere"] }, only_ids: ["X"], limit: 99 },
    "user",
  );
  assertEquals(asUser, {
    action: "match",
    profile,
    prefs: { role_type: "both", unis: ["HKU"] },
    limit: USER_LIMIT,
    minScore: 0,
  });
  const asService = parseRequest({ action: "match", profile, only_ids: ["HKU-1", 7], limit: 3 }, "service");
  assertEquals(asService, {
    action: "match",
    profile,
    prefs: { role_type: undefined, unis: [] },
    onlyIds: ["HKU-1"],
    limit: 3,
    minScore: 65,
  });
  assertEquals(parsePrefs(null), { role_type: undefined, unis: [] });
});

Deno.test("Claude's ranking is limited to the shortlist, de-duplicated and sorted", () => {
  const raw = {
    matches: [
      { job_id: "A", score: 72, why: "Your nursing teaching fits.", gaps: ["PhD", "Cantonese", "extra"] },
      { job_id: "B", score: 91.6, why: "Your clinical record fits.", gaps: [] },
      { job_id: "A", score: 99, why: "Duplicate", gaps: [] },
      { job_id: "Z", score: 95, why: "Not shortlisted", gaps: [] },
      { job_id: "C", score: 40, why: "Too weak", gaps: [] },
      { job_id: "D", score: 60, why: "", gaps: [] },
      { job_id: "E", score: 55, why: "  Adjacent field. ", gaps: "none" },
    ],
    advice: "Mention your simulation teaching.",
  };
  const { matches, advice } = cleanMatches(raw, new Set(["A", "B", "C", "D", "E"]), 12, 50);
  assertEquals(matches.map((m) => [m.job_id, m.score, m.fit]), [["B", 92, "strong"], ["A", 72, "good"], [
    "E",
    55,
    "possible",
  ]]);
  assertEquals(matches[1].gaps, ["PhD", "Cantonese"]);
  assertEquals(matches[2].gaps, []);
  assertEquals(advice, "Mention your simulation teaching.");
  assertEquals(cleanMatches(raw, new Set(["A", "B", "E"]), 1, 0).matches.map((m) => m.job_id), ["B"]);
  assertEquals(cleanMatches("nonsense", new Set(["A"]), 12, 0), { matches: [], advice: "" });
});
