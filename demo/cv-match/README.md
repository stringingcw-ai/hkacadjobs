# CV matching demo video

`cv-matching-demo.mp4` (1 min 29 s, 1280×720, no sound) walks through "✨ Find jobs that fit your CV" on the real
site: the intro, signing up by email, uploading a PDF CV (with the contact details removed), checking and
editing the profile, the "Jobs that fit you" list, and "Why this may suit you" in a job's panel.

`cv-matching-demo-short.mp4` (28 s, no captions, for social media such as Threads) starts signed in and shows
only the main steps: the button, uploading the CV, the profile, the matches and a job's "Why this may suit you".

**What is real and what is scripted.** The page, the listings and cv-match.js are the site's own, and the PDF is
read in the browser as usual. Sign-in, the database and the `match-jobs` function are stand-ins, so no email
is sent and Claude isn't called:
- `supabase-stub.js` replaces supabase-js;
- `api.js` holds the function's answers. The profile is the `comp_bio_postdoc` test persona's, and the eight
  matches, with their reasons and gaps, are written by hand from jobs listed on 1 Oct 2026. Refresh the
  job IDs in `api.js` once those jobs close.

The end card says "Demo with a sample CV".

## Recording it again

```sh
python3 -m http.server 8000          # in the repository, in another terminal
npm install --no-save playwright     # if it isn't installed
node demo/cv-match/record.js         # writes demo/cv-match/out/raw.webm
node demo/cv-match/record.js --shots # or: screenshots of each step in out/shots, no video
node demo/cv-match/record.js --short # the short cut: writes demo/cv-match/out/raw-short.webm
```

The short cut skips the page's opening animation and plays at 1.12× speed:

```sh
ffmpeg -i demo/cv-match/out/raw-short.webm -vf "trim=start=3.9:end=34.9,setpts=(PTS-STARTPTS)/1.12,fps=30,\
fade=t=in:st=0:d=0.3,fade=t=out:st=27.1:d=0.5,format=yuv420p" -an -c:v libx264 -preset slow -crf 18 \
-movflags +faststart demo/cv-match/cv-matching-demo-short.mp4
```

For the full video:

the script prints the timings `cutFrom` and `cutTo` around the reload after the sign-in link. The page is
still loading between those times. Cut that part out and encode, adjusting the trim times to the frames of the
new recording:

```sh
ffmpeg -i demo/cv-match/out/raw.webm -filter_complex "\
[0:v]trim=start=0.5:end=24.6,setpts=PTS-STARTPTS,fps=25[a];\
[0:v]trim=start=25.75:end=90.6,setpts=PTS-STARTPTS,fps=25[b];\
[a][b]xfade=transition=fade:duration=0.35:offset=23.75,fade=t=in:st=0:d=0.4,fade=t=out:st=87.9:d=0.7,format=yuv420p[v]" \
-map "[v]" -c:v libx264 -preset slow -crf 18 -movflags +faststart demo/cv-match/cv-matching-demo.mp4
```

If the browser can't reach Google Fonts (as in a Claude Code cloud session), put the CSS in `out/fonts/css.css`
and each font file in `out/fonts/<first 16 hex of md5(url + "\n")>.woff2`. The script serves them from there.
