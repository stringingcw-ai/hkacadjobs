// Quality check with the real Claude API: each test persona's CV (testdata/personas.json) goes
// through the same steps as the site — profile, shortlist over the live jobs.csv, ranking — and the
// results are printed for a person to judge. About US$0.08 per persona on Claude Sonnet 5.5.
//
//   ANTHROPIC_API_KEY=... deno task eval                   # all personas
//   ANTHROPIC_API_KEY=... deno task eval nurse_educator    # just one
//
// MATCH_MODEL and JOBS_CSV_URL work as in the function. Nothing is stored.

import Anthropic from "@anthropic-ai/sdk";
import { extractProfile, rankJobs } from "./claude.ts";
import { loadConfig } from "./config.ts";
import { JobsSource } from "./jobs.ts";
import { costUsd } from "./models.ts";
import { shortlist } from "./shortlist.ts";
import { addUsage } from "./types.ts";
import { cleanMatches, redactContacts, sanitizeProfile, USER_LIMIT } from "./validate.ts";

interface Persona {
  name: string;
  cv: string;
  relevant: string[];
}

const config = loadConfig((name) => Deno.env.get(name));
if (!config.anthropicApiKey) {
  console.error("Set ANTHROPIC_API_KEY to run the quality check.");
  Deno.exit(1);
}
const client = new Anthropic({ apiKey: config.anthropicApiKey });
const jobs = await new JobsSource({ url: config.jobsCsvUrl, fetch }).get();
const personas: Persona[] = JSON.parse(await Deno.readTextFile(new URL("./testdata/personas.json", import.meta.url)));
const wanted = new Set(Deno.args);
let total = 0;

for (const persona of personas.filter((p) => !wanted.size || wanted.has(p.name))) {
  const started = Date.now();
  const extracted = await extractProfile(client, config.model, redactContacts(persona.cv));
  const profile = sanitizeProfile(extracted.profile);
  if (!profile) {
    console.log(`\n══ ${persona.name}: Claude's profile did not match the schema`);
    continue;
  }
  const candidates = shortlist(jobs.index, profile, { limit: 40 });
  const ranked = await rankJobs(client, config.model, profile, candidates.map((c) => c.job), USER_LIMIT);
  const { matches, advice } = cleanMatches(ranked.ranking, new Set(candidates.map((c) => c.job.id)), USER_LIMIT, 0);
  const cost = costUsd(config.model, addUsage(extracted.usage, ranked.usage));
  total += cost;

  console.log(`\n══ ${persona.name} (${Math.round((Date.now() - started) / 1000)} s, US$${cost.toFixed(3)})`);
  console.log(`   ${profile.headline} | ${profile.role_type} | ${profile.suitable_ranks.join(", ")}`);
  console.log(`   ${profile.summary}`);
  console.log(`   terms: ${profile.search_terms.join(", ")}`);
  for (const m of matches) {
    const job = jobs.all.get(m.job_id)!;
    const labelled = persona.relevant.includes(m.job_id) ? "*" : " ";
    console.log(
      `  ${labelled}${String(m.score).padStart(3)} ${m.fit.padEnd(8)} ${job.title.slice(0, 70)} (${job.university})`,
    );
    console.log(`        ${m.why}${m.gaps.length ? `  Gaps: ${m.gaps.join("; ")}` : ""}`);
  }
  if (advice) console.log(`   Advice: ${advice}`);
}

console.log(
  `\nTotal US$${total.toFixed(2)} on ${config.model}; ${jobs.open.length} open jobs, updated ${jobs.updated}. ` +
    `* = a job labelled relevant in testdata/personas.json`,
);
