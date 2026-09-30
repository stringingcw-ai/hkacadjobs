import { assert, assertEquals, assertRejects } from "@std/assert";
import { hkDate, isOpen, JobsSource, parseDescription, parseJobsCsv } from "./jobs.ts";
import { fixtureCsv, TODAY } from "./testing.ts";

Deno.test("hkDate uses Hong Kong time", () => {
  assertEquals(hkDate(new Date("2026-09-29T15:59:00Z")), "2026-09-29");
  assertEquals(hkDate(new Date("2026-09-29T16:00:00Z")), "2026-09-30");
});

Deno.test("a job is open until its deadline date has passed", () => {
  assert(isOpen({ deadline: "" }, TODAY));
  assert(isOpen({ deadline: TODAY }, TODAY));
  assert(isOpen({ deadline: "Open until filled" }, TODAY));
  assert(!isOpen({ deadline: "2026-09-28" }, TODAY));
});

Deno.test("summaries are split into sections; 'Not specified' is dropped", () => {
  const d = parseDescription(
    "**Duties & Responsibilities**\n• Teach nursing\n• Supervise students\n\n" +
      "**Requirements & Qualifications**\n• A PhD in nursing\n\n" +
      "**Appointment**\n• Full-time, 3 years\n\n**Key Dates**\n• Not specified",
  );
  assertEquals(d, {
    duties: ["Teach nursing", "Supervise students"],
    requirements: ["A PhD in nursing"],
    appointment: "Full-time, 3 years",
    other: "",
  });
});

Deno.test("raw ads are kept as text, and bot-check pages are ignored", () => {
  assertEquals(
    parseDescription("We are looking for a  lecturer\nin law.").other,
    "We are looking for a lecturer in law.",
  );
  assertEquals(parseDescription("Please complete the security check to continue"), {
    duties: [],
    requirements: [],
    appointment: "",
    other: "",
  });
});

Deno.test("jobs.csv is parsed into jobs", async () => {
  const jobs = parseJobsCsv(await fixtureCsv());
  assertEquals(jobs.length, 172);
  const job = jobs.find((j) => j.id === "CUHK-4d0399b959")!;
  assertEquals(job.title, "Lecturer(s)");
  assertEquals(job.rank, "Senior Lecturer/Lecturer");
  assertEquals(job.department, "The Nethersole School of Nursing");
  assert(job.duties[0].startsWith("Teach nursing students"));
  assertEquals(typeof job.is_new, "boolean");
});

function source(csv: () => string, clock: { now: Date }, fetched: string[]) {
  return new JobsSource({
    url: "https://example.test/jobs.csv",
    fetch: (url) => {
      fetched.push(String(url));
      const body = csv();
      return Promise.resolve(body ? new Response(body) : new Response("gone", { status: 404 }));
    },
    now: () => clock.now,
    ttlMs: 30 * 60_000,
  });
}

Deno.test("jobs are cached, closed jobs left out, and reloaded after 30 minutes", async () => {
  const csv = await fixtureCsv();
  const clock = { now: new Date(`${TODAY}T04:00:00Z`) };
  const fetched: string[] = [];
  const jobs = source(() => csv, clock, fetched);
  const set = await jobs.get();
  assertEquals(set.all.size, 172);
  assertEquals(set.open.length, 169);
  assert(!set.open.some((j) => j.id === "POLYU-260904007"));
  assertEquals(set.today, TODAY);
  await jobs.get();
  assertEquals(fetched.length, 1);
  clock.now = new Date(clock.now.getTime() + 31 * 60_000);
  await jobs.get();
  assertEquals(fetched.length, 2);
});

Deno.test("unknown job ids trigger one cache-busting reload a minute", async () => {
  const csv = await fixtureCsv();
  const clock = { now: new Date(`${TODAY}T04:00:00Z`) };
  const fetched: string[] = [];
  const jobs = source(() => csv, clock, fetched);
  await jobs.get(["CUHK-4d0399b959"]);
  assertEquals(fetched.length, 1);
  await jobs.get(["NEW-1"]);
  assertEquals(fetched.length, 2);
  assert(/\?v=\d+$/.test(fetched[1]));
  await jobs.get(["NEW-1"]);
  assertEquals(fetched.length, 2);
});

Deno.test("a failed reload keeps the cached jobs; with no cache it is an error", async () => {
  const csv = await fixtureCsv();
  const clock = { now: new Date(`${TODAY}T04:00:00Z`) };
  let body = csv;
  const jobs = source(() => body, clock, []);
  await jobs.get();
  body = "";
  clock.now = new Date(clock.now.getTime() + 60 * 60_000);
  assertEquals((await jobs.get()).open.length, 169);

  const empty = source(() => "", clock, []);
  await assertRejects(() => empty.get(), Error, "Could not load jobs.csv");
});
