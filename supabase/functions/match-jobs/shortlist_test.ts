import { assert, assertEquals } from "@std/assert";
import { shortlist, tokenize } from "./shortlist.ts";
import { fixtureJobs, personas } from "./testing.ts";
import { ACADEMIC_RANKS } from "./types.ts";

Deno.test("tokenize: lowercase stems without filler words; CJK as character pairs", () => {
  assertEquals(tokenize("Professors of Nursing Studies"), ["professor", "nursing", "study"]);
  assertEquals(tokenize("C++ and C# developers"), ["c++", "c#", "developer"]);
  assertEquals(tokenize("實驗室助理"), ["實驗", "驗室", "室助", "助理"]);
  assertEquals(tokenize("IT 支援"), ["it", "支援"]);
});

Deno.test("each persona's relevant jobs rank near the top of the fixture", async () => {
  const jobs = await fixtureJobs();
  for (const p of await personas()) {
    const ids = shortlist(jobs.index, p.profile, { limit: 20 }).map((c) => c.job.id);
    const missing = p.relevant.filter((id) => !ids.includes(id));
    assertEquals(missing, [], `${p.name}: relevant jobs missing from the top 20`);
    const top10 = p.relevant.filter((id) => ids.slice(0, 10).includes(id));
    assert(top10.length * 2 >= p.relevant.length, `${p.name}: only ${top10.length} relevant jobs in the top 10`);
  }
});

Deno.test("the role type filters by rank; 'Other' passes both ways", async () => {
  const jobs = await fixtureJobs();
  const all = await personas();
  const it = all.find((p) => p.name === "it_systems_administrator")!;
  for (const c of shortlist(jobs.index, it.profile, { limit: 40 })) {
    assert(c.job.rank === "Other" || !ACADEMIC_RANKS.has(c.job.rank), `${c.job.id} is ${c.job.rank}`);
  }
  const nurse = all.find((p) => p.name === "nurse_educator")!;
  for (const c of shortlist(jobs.index, nurse.profile, { limit: 40 })) {
    assert(!c.job.rank || ACADEMIC_RANKS.has(c.job.rank), `${c.job.id} is ${c.job.rank}`);
  }
  const both = shortlist(jobs.index, nurse.profile, { limit: 40, roleType: "both" });
  assert(both.some((c) => c.job.rank === "Non-Academic"));
});

Deno.test("institution and job-id filters, and a minimum number of matched terms", async () => {
  const jobs = await fixtureJobs();
  const english = (await personas()).find((p) => p.name === "english_lecturer")!;
  const hku = shortlist(jobs.index, english.profile, { limit: 40, unis: ["HKU"] });
  assert(hku.length > 0 && hku.every((c) => c.job.university === "HKU"));
  const only = shortlist(jobs.index, english.profile, { limit: 40, onlyIds: ["HKU-537450", "LU-3075"] });
  assertEquals(only.map((c) => c.job.id), ["HKU-537450"]);
  const strict = shortlist(jobs.index, english.profile, { limit: 200, minMatched: 5 });
  assert(strict.every((c) => c.matched >= 5));
  assert(strict.length < shortlist(jobs.index, english.profile, { limit: 200 }).length);
});

Deno.test("a profile about nothing in the listings matches nothing", async () => {
  const jobs = await fixtureJobs();
  const base = (await personas())[0].profile;
  const profile = {
    ...base,
    disciplines: ["Zzyzx"],
    specialisms: ["quuxology"],
    skills: [],
    search_terms: ["xyzzy"],
  };
  assertEquals(shortlist(jobs.index, profile, { limit: 40 }), []);
});
