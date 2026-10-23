# Local operator UI

This buildless page is served by the lab operator at `/`. It reads `GET /api/state` and refreshes every five seconds. The UI expects the state contract described by the operator API: session lifetime, active lesson, the four lesson records, current pod observation, and the optional latest experiment. Browser notes in the prediction field stay local to the page. Experiment creation sends exactly `{ "lesson_id": "…", "concurrency": 1|2|4|8 }` as JSON to `POST /api/experiments`; the operator owns the fixed request count and output-token limit. A successful submission returns HTTP 202 and the page follows state until the experiment finishes.

The page uses only same-origin static assets and APIs, with no third-party scripts, fonts, or runtime packages. Serve it with a restrictive policy such as `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'self'; frame-ancestors 'none'`. Dynamic API values are inserted as text. Keep the service private as a ClusterIP and access it through a loopback-only port-forward:

```powershell
kubectl -n inference-lab port-forward --address=127.0.0.1 service/lab-operator 18080:8080
```

Then open `http://127.0.0.1:18080/`. Session expiry in the UI is a countdown based on the last API snapshot; it does not confirm that cluster resources were deleted. Pod placement is the operator's current API observation. Ray node identity does not establish model-serving identity, and the balanced request model pod is unknown. Slurm and Triton have no live adapter and cannot be enabled through environment settings. Experiment state is in memory and is lost if the operator restarts. Historical measurements are not represented as live results.
