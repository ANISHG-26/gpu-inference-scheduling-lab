# Quick guide: Triton CPU experiment

This is a short screen tour for lesson 04 in the local operator console. For deployment and shutdown, use the [runbook](docs/runbook.md). The console only observes the session and runs a bounded experiment; it cannot create, extend or stop a session.

## Walk through the page

1. **Connection and session, at the top.** Wait for “Connected · state current.” The session clock is a countdown from the latest operator snapshot, not proof that cluster resources were deleted. If state is stale or disconnected, actions pause.
2. **Lesson list, on the left.** Select **04 · Triton CPU serving**. Read the objective and steps. The server controls which lesson is active; selecting lesson 04 does not deploy it. If another lesson is active, the notice explains which one can run.
3. **Live pod observation.** Confirm the Triton model pod is Ready and note its UID and node. This table is a read-only Kubernetes observation. A run also checks that the Triton pod UID remains the same before and after its requests.
4. **Your prediction.** Write what you expect to happen when client batch size changes. This note stays in browser memory and is lost on reload; it is not saved with the experiment.
5. **Controlled experiment.** Choose concurrency (1, 2, 4 or 8 in-flight requests) and batch size (1, 2, 4 or 8 items per HTTP request). Click **Run 8 input items** when enabled. The adapter fixes the endpoint, model name `lab_double`, model version 1 and the eight inputs; it accepts no custom model or command. The page follows the run and refreshes state every five seconds.
6. **Result and reflection.** Read the state and counters before drawing a conclusion. Compare against your prediction, then consult the [lesson notes](lessons/04-triton-cpu-serving/README.md) for model details and request examples.

## Read the lesson state

| State | What it means |
| --- | --- |
| **Prepared** | The lesson instructions exist, but current live placement is not verified. |
| **Deployed** | This is the active lesson and the current placement check is ready. It does not mean an experiment has passed. |
| **Measured** | The bounded run completed with valid responses and metrics, and the current pod identity still matches the run. |
| **Failed** | A required pod or experiment check failed, the session expired, or the current pod identity no longer matches the measurement. Read the result message and refresh the observation before interpreting it. |

The experiment itself may show **running**, **measured** or **failed**. A failure is evidence to inspect, not a measurement to compare as if it succeeded.

## Understand the counts

Every run contains eight input items, each with four FP32 values. Client batch size groups those items into HTTP requests:

| Client batch size | HTTP requests for 8 items |
| ---: | ---: |
| 1 | 8 |
| 2 | 4 |
| 4 | 2 |
| 8 | 1 |

**Completed inputs** count items that received valid output. **Requests completed** count client HTTP requests. Triton's **inference count** counts input items accepted by the model; **execution count** counts backend executions. Triton may combine items from requests through dynamic batching, so execution count can be lower than request count. A difference in counts does not by itself show that client batch size caused server batching or improved performance.

Compare one setting at a time: keep concurrency fixed while changing batch size, then keep batch size fixed while changing concurrency. These short CPU samples are noisy; latency and throughput can vary between runs. They are useful for seeing behavior, not for choosing a production setting.

The adapter also makes fixed negative checks. **HTTP 400** for an invalid tensor shape and **HTTP 404** for unavailable model version 2 are expected. They test the protocol; they do not mean the valid experiment failed. Version 1 is the configured model version.

## Keep the scheduling layers straight

The pod table shows where Kubernetes placed the Triton pod. The Triton execution counter shows backend work. Neither is a Ray or GPU measurement: lesson 04 uses Triton directly on CPU, while lessons 01–02 use Ray Serve and vLLM. The 2026-11-06 runtime, API and browser results are dated evidence. That session was shut down after recording, and the cluster, VM and boot disk were verified absent. The video is usable without a running lab.

For a short browser walkthrough, open [WATCH.html](WATCH.html) or [the video](videos/triton-batching.webm). For the wider project refresher and architecture, see the [README](README.md).
