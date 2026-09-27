"""Temporary: live check of structured summaries (direct + batch)."""
import csv, time
import summaries
rows = list(csv.DictReader(open("jobs.csv", encoding="utf-8")))
rows = [r for r in rows if len(r["description"]) > 400][:12]
text, extras = summaries.summarise_job(rows[0]["description"], rows[0]["title"], rows[0]["department"])
print("DIRECT OK:", text.startswith("**Duties"), extras)
print(text[:600])
jobs = [{"id": r["id"], "title": r["title"], "department": r["department"], "description": r["description"],
         "deadline": "", "deadline_note": "", "salary": "", "start_date": ""} for r in rows[1:11]]
summaries.BATCH_MAX_WAIT = 15 * 60
t = time.time()
summaries.summarise_jobs(jobs)
print(f"BATCH took {time.time() - t:.0f}s; structured: {sum(j['description'].startswith('**Duties') for j in jobs)}/10")
for j in jobs[:3]:
    print("-", j["id"], "| salary:", j["salary"], "| start:", j["start_date"], "| deadline:", j["deadline"])
