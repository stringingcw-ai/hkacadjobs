# Vendored libraries

Third-party code used by `cv-match.js` to read CVs in the browser. It's loaded only
when someone picks a file, and it's served from this site, so no CV
goes to a CDN. The files are copied unchanged from the npm packages below. The only change is the
file names, where `.mjs` became `.js`: GitHub Pages and local test servers then always serve them as
JavaScript.

| Files | Package | Licence |
| --- | --- | --- |
| `pdfjs/pdf.min.js`, `pdfjs/pdf.worker.min.js` | [`pdfjs-dist@6.3.289`](https://www.npmjs.com/package/pdfjs-dist/v/6.3.289), `legacy/build/pdf.min.mjs` and `legacy/build/pdf.worker.min.mjs` (the legacy build supports older browsers such as older iPhones) | Apache-2.0, `pdfjs/LICENSE` |
| `pdfjs/cmaps/*.bcmap` | the same package, `cmaps/`: character maps pdf.js needs to read some Chinese, Japanese and Korean PDFs | see `pdfjs/cmaps/LICENSE` |
| `mammoth/mammoth.browser.min.js` | [`mammoth@1.13.0`](https://www.npmjs.com/package/mammoth/v/1.13.0), `mammoth.browser.min.js` (reads .docx files) | BSD-2-Clause, `mammoth/LICENSE` |

SHA-256 of the scripts:

```
f401927e692efc7735e0cd528c490d0dd31b7f0972c122b7040df805be45cce4  pdfjs/pdf.min.js
a33cfe728c584fdba4fcc1fd54bcdc2f9f2f13889ddbb5b2bd1d0f8cbe49b84e  pdfjs/pdf.worker.min.js
92914a3708cfdf1e62cb553d1856a7fedab21da83d8ee82845de2f897b368cab  mammoth/mammoth.browser.min.js
```

To upgrade, download the new package from the npm registry (`npm pack pdfjs-dist@<version>`), check
it against the registry's `integrity` hash, copy the same files over these, update this table and
the hashes, and bump `CV_MATCH_VERSION` in `index.html`.
