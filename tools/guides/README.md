# Record the Triton walkthrough

This optional developer tool uses Playwright 1.65.0 and **Node.js 20 or newer**. It records the existing real operator page; it never provisions or extends a lab.

From this directory:

```sh
npm ci
npx playwright install chromium
npm test
npm run record -- http://127.0.0.1:18080/ DEPLOYED_OPERATOR_COMMIT
```

Replace the port with an existing loopback-only operator forward and the revision with the full 40-character source commit of its deployed image. Verify that image/source relationship separately before capture. The tool accepts only an explicit unprivileged port on `http://127.0.0.1/`; URLs with credentials, other paths, queries or fragments are rejected. No cloud credentials are needed by the recorder.

It requires active lesson 04, fresh Ready placement, no running experiment and at least three minutes of session lifetime. It sends **two experiments / 16 input items total**, using concurrency 4 and client batch sizes 1 and 4. Fixed shape/version error probes are made by the existing adapter. Actual input/request/execution counters, model version, readiness and stable pod identity are asserted. The whole recording has a three-minute watchdog.

Captures and full API evidence go to ignored `.lab/guide-captures/`. No public files are overwritten. For the public presentation, an appended stylesheet hides the table's raw pod name, UID and node columns before the first render; roles, readiness, inference results and APIs are unchanged. Captions are added to the browser only. This presentation is not a fixture or a change to the deployed operator.

Before publishing, play the entire successful clip, inspect its frames for identifiers, verify captions and outcomes, and copy only the selected video/poster to `videos/`. Write a small `videos/recordings.json` with the public capture date, actual deployed source/image identities, verified outcomes and presentation notes. Never publish the private report, cookies, traces, failed videos or raw logs. Preserve prior recordings before replacing them.

Open `WATCH.html` to play the committed recording. If file playback is restricted, serve the repository locally with `python -m http.server 18081 --bind 127.0.0.1` and visit `http://127.0.0.1:18081/WATCH.html`. This serves files only; it does not connect to a lab or enable experiments.

Recording finalization follows [Playwright's video lifecycle](https://playwright.dev/docs/videos): close the browser context before saving the completed video. Fixtures in `policy.test.mjs` test recorder guards; they do not establish real Triton acceptance.
