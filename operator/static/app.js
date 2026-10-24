(() => {
  "use strict";

  const LESSONS = [
    { id: "01-single-node-inference", title: "Single node inference" },
    { id: "02-two-node-inference", title: "Two node inference" },
    { id: "03-slurm-cpu-scheduling", title: "Slurm CPU scheduling" },
    { id: "04-triton-cpu-serving", title: "Triton CPU serving" },
  ];
  const $ = (id) => document.getElementById(id);
  const els = {
    connection: $("connection"), connectionText: $("connection-text"), list: $("lesson-list"),
    sessionTime: $("session-time"), sessionLabel: $("session-label"), sequence: $("sequence-notice"),
    number: $("lesson-number"), state: $("lesson-state"), title: $("lesson-title"), objective: $("lesson-objective"),
    gate: $("gate-note"), steps: $("lesson-steps"), stepCount: $("step-count"), prediction: $("prediction"), predictionPrompt: $("prediction-prompt"),
    concurrency: $("concurrency"), batchSize: $("batch-size"), tritonControls: $("triton-controls"),
    runBudget: $("run-budget"), runDescription: $("run-description"), run: $("run-button"), actionStatus: $("action-status"), result: $("experiment-result"),
    observationTime: $("observation-time"), placement: $("placement-summary"), pods: $("pod-rows"),
    reflection: $("reflection-text"), lastRefresh: $("last-refresh"),
  };
  const predictions = new Map();
  let selectedId = LESSONS[0].id;
  let latest = null;
  let lastSuccessAt = 0;
  let stateFetchFailed = false;
  let refreshing = false;
  let actionBusy = false;
  let actionFeedback = "";
  let experimentPoll = 0;

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function formatTime(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const date = new Date(seconds * 1000);
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(date);
  }
  function elapsedServerSeconds() {
    return latest ? Math.max(0, Math.floor((Date.now() - lastSuccessAt) / 1000)) : 0;
  }
  function isFresh() { return !!latest && !stateFetchFailed && Date.now() - lastSuccessAt < 15000; }
  function sessionActive() {
    const remaining = latest?.session?.remaining_seconds;
    return !!latest && latest.session?.status === "active" && Number.isFinite(remaining) &&
      remaining - elapsedServerSeconds() > 0;
  }
  function hasReadyPod() {
    return latest?.observation?.status === "ok" && Array.isArray(latest.observation.pods) &&
      latest.observation.pods.some((pod) => pod.ready === true);
  }
  function lessonById(id) { return latest?.lessons?.find((item) => item.id === id) || null; }
  function selectedLesson() { return lessonById(selectedId); }

  function renderLessonNav() {
    els.list.replaceChildren();
    for (let i = 0; i < LESSONS.length; i += 1) {
      const meta = LESSONS[i];
      const lesson = lessonById(meta.id);
      const button = node("button", "lesson-link");
      button.type = "button";
      button.setAttribute("aria-current", selectedId === meta.id ? "step" : "false");
      const index = node("span", "lesson-index", String(i + 1).padStart(2, "0"));
      const copy = node("span", "lesson-link-copy");
      copy.append(node("span", "lesson-link-title", lesson?.title || meta.title));
      const badge = node("span", `mini-state state-${lesson?.state || "unavailable"}`, lesson?.state || "unavailable");
      copy.append(badge);
      button.append(index, copy);
      button.addEventListener("click", () => {
        predictions.set(selectedId, els.prediction.value);
        selectedId = meta.id;
        render();
      });
      els.list.append(button);
    }
  }
  function renderLesson() {
    const lesson = selectedLesson();
    const num = LESSONS.findIndex((item) => item.id === selectedId) + 1;
    els.number.textContent = `LESSON ${String(num).padStart(2, "0")}`;
    els.state.textContent = lesson?.state || "unavailable";
    els.state.className = `state-pill state-${lesson?.state || "unavailable"}`;
    els.title.textContent = lesson?.title || LESSONS[num - 1]?.title || "Lesson unavailable";
    els.objective.textContent = lesson?.objective || "This lesson is not present in the latest operator state.";
    els.predictionPrompt.textContent = lesson?.prediction || "Write down your expectation before the experiment.";
    els.steps.replaceChildren();
    const steps = Array.isArray(lesson?.steps) ? lesson.steps : [];
    els.stepCount.textContent = `${steps.length} steps`;
    for (const step of steps) els.steps.append(node("li", "step-item", step));
    if (steps.length === 0) els.steps.append(node("li", "muted", "No instructions are available in the current state."));
    const serverGate = lesson?.gate || (["03-slurm-cpu-scheduling", "04-triton-cpu-serving"].includes(selectedId) && lesson?.actions_enabled !== true
      ? "The server has not enabled this lesson." : "");
    els.gate.hidden = !serverGate;
    els.gate.textContent = serverGate ? `This lesson is gated: ${serverGate}` : "";
    els.prediction.value = predictions.get(selectedId) || "";
    const activeId = latest?.active_lesson;
    const isActive = activeId === selectedId;
    els.sequence.hidden = isActive;
    els.sequence.textContent = !activeId ? "No lesson is currently active. Run controls stay disabled until the operator activates a lesson." :
      `Sequential session: ${lessonById(activeId)?.title || activeId} is active. Select it to run the experiment.`;
    els.reflection.textContent = lesson?.reflection || "Complete the measurement, then note what matched your prediction and what surprised you.";
  }
  function renderSession() {
    if (!latest) return;
    const session = latest.session || {};
    const remaining = session.remaining_seconds === null ? null : Math.max(0, session.remaining_seconds - elapsedServerSeconds());
    if (session.status === "active" && remaining !== null) {
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      els.sessionTime.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
      els.sessionLabel.textContent = remaining > 0 ? "session remaining" : "session expired";
    } else if (session.status === "active") {
      els.sessionTime.textContent = "—";
      els.sessionLabel.textContent = "expiry unavailable";
    } else {
      els.sessionTime.textContent = "—";
      els.sessionLabel.textContent = session.status === "expired" ? "session expired" : "session unconfigured";
    }
  }
  function renderObservation() {
    const observation = latest?.observation;
    els.pods.replaceChildren();
    if (!observation || observation.status !== "ok") {
      els.observationTime.textContent = observation?.observed_at ? `Last attempt ${formatTime(observation.observed_at)}` : "Not yet observed";
      els.placement.textContent = "Kubernetes observation unavailable. No current placement is shown.";
      const row = node("tr"); row.append(node("td", "empty-cell", "No current pod observation.")); row.firstChild.colSpan = 6; els.pods.append(row);
      return;
    }
    els.observationTime.textContent = `Observed ${formatTime(observation.observed_at)}`;
    const placement = observation.placement || {};
    els.placement.textContent = placement.valid ? "Placement check passed for this observation." : `Placement check: ${placement.reason || "not valid"}`;
    for (const pod of (observation.pods || [])) {
      const row = node("tr");
      for (const value of [pod.name, pod.uid || "—", pod.node || "—", pod.role || "—", pod.terminating ? "Terminating" : pod.phase || "unknown", pod.ready ? "Ready" : "Not ready"]) row.append(node("td", "", value));
      els.pods.append(row);
    }
    if (!observation.pods?.length) {
      const row = node("tr"); const cell = node("td", "empty-cell", "No pods found in this observation."); cell.colSpan = 6; row.append(cell); els.pods.append(row);
    }
  }
  function metric(label, value) {
    const item = node("div", "metric"); item.append(node("span", "metric-label", label), node("strong", "metric-value", value)); return item;
  }
  function renderExperiment() {
    els.result.replaceChildren();
    const exp = latest?.experiment;
    if (!exp) return;
    const heading = node("div", "result-heading");
    heading.append(node("strong", "", `Experiment ${exp.state}`));
    if (exp.lesson_id) heading.append(node("span", "muted small", ` · ${lessonById(exp.lesson_id)?.title || exp.lesson_id}`));
    const triton = exp.adapter === "triton" || exp.lesson_id === "04-triton-cpu-serving";
    heading.append(node("span", "muted small", ` · concurrency ${exp.concurrency}${triton && Number.isInteger(exp.batch_size) ? ` · batch size ${exp.batch_size}` : ""} · started ${formatTime(exp.started_at)}`));
    els.result.append(heading);
    if (exp.state === "running") { els.result.append(node("p", "muted small", "Measurement is running; this view will update automatically.")); return; }
    if (exp.state === "failed") els.result.append(node("p", "error-copy", readableExperimentError(exp.error)));
    if (exp.summary) {
      const summary = exp.summary;
      const grid = node("div", "metrics-grid");
      if (triton) {
        const counters = exp.triton?.counter_deltas || {};
        grid.append(metric("Completed inputs", String(summary.completed ?? "—")), metric("Failed inputs", String(summary.errors ?? "—")),
          metric("Inferences/sec", formatMetric(summary.inferences_per_second, "")), metric("Requests completed", String(summary.requests_completed ?? "—")),
          metric("Request errors", String(summary.request_errors ?? "—")), metric("p50 latency", formatMetric(summary.p50_latency_seconds, " s")),
          metric("p95 latency", formatMetric(summary.p95_latency_seconds, " s")), metric("Wall time", formatMetric(summary.wall_time_seconds, " s")));
        if (Number.isFinite(counters.success)) grid.append(metric("Success counter delta", String(counters.success)));
        if (Number.isFinite(counters.inference_count)) grid.append(metric("Inference count delta", String(counters.inference_count)));
        if (Number.isFinite(counters.execution_count)) grid.append(metric("Execution count delta", String(counters.execution_count)));
        if (Number.isFinite(exp.triton?.mean_batch_size)) grid.append(metric("Observed items / execution", formatMetric(exp.triton.mean_batch_size, "")));
      } else {
        grid.append(metric("Completed", String(summary.completed ?? "—")), metric("Errors", String(summary.errors ?? "—")),
          metric("p50 latency", formatMetric(summary.p50_latency_seconds, " s")), metric("p95 latency", formatMetric(summary.p95_latency_seconds, " s")),
          metric("Completion rate", formatMetric(summary.completion_tokens_per_second, " tok/s")), metric("Wall time", formatMetric(summary.wall_time_seconds, " s")));
      }
      els.result.append(grid);
    }
    if (exp.identity_note) els.result.append(node("p", "identity-note", exp.identity_note));
  }
  function readableExperimentError(code) {
    const messages = {
      requests_failed: "One or more requests failed. Compare the completed and error counts below.",
      placement_unready: "The serving pods are no longer Ready. Observe placement before running again.",
      pod_identity_changed: "A serving pod was replaced. This result no longer describes the current pod identities.",
      observation_unavailable: "Current Kubernetes status is unavailable; the result cannot be verified as current.",
      inference_evidence_missing: "Responses did not include the required positive completion-token evidence.",
      triton_protocol_failed: "Triton did not return a valid inference response. Check the serving lesson status before retrying.",
      metrics_unverified: "Triton metrics could not be verified for this run, so the measurement is not available.",
      experiment_unavailable: "The bounded experiment could not complete. Refresh the lesson status before retrying.",
      adapter_unavailable: "This lesson has no live serving adapter available yet.",
      experiment_failed: "The experiment did not complete successfully.",
      readiness_missing: "No ready model pod was available for the experiment.",
      session_expired: "The session expired before the experiment could complete.",
      lesson_inactive: "This lesson is not active in the current sequence.",
      already_running: "An experiment is already running.",
      cancelled: "The experiment was cancelled.",
      timeout: "The experiment exceeded its time limit.",
    };
    return messages[code] || "The experiment did not complete successfully.";
  }
  function formatMetric(value, suffix) { return Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : "—"; }
  function renderConnection() {
    const fresh = isFresh();
    const status = stateFetchFailed || !latest ? "disconnected" : fresh ? "connected" : "stale";
    els.connection.dataset.state = status;
    els.connectionText.textContent = status === "connected" ? "Connected · state current" : status === "stale" ? "State stale · actions paused" : "Disconnected · waiting for operator";
    els.lastRefresh.textContent = fresh ? `Updated ${formatTime(latest.server_time)}` : latest ? `Last successful refresh ${formatTime(latest.server_time)}` : "No successful refresh yet";
    const lesson = selectedLesson();
    const experimentRunning = latest?.experiment?.state === "running";
    const enabled = fresh && sessionActive() && hasReadyPod() && latest?.active_lesson === selectedId && lesson?.actions_enabled === true && !experimentRunning && !actionBusy;
    els.run.disabled = !enabled;
    const isTriton = selectedId === "04-triton-cpu-serving";
    els.tritonControls.hidden = !isTriton;
    els.batchSize.disabled = !isTriton || !enabled;
    els.runBudget.textContent = isTriton ? "8 input items · model version 1 fixed" : "8 requests · up to 32 tokens each";
    els.runDescription.textContent = isTriton ? "A bounded measurement against the active Triton lesson. Inputs, endpoint, and model version are fixed." : "A bounded measurement against the active lesson. The request shape and endpoint are fixed.";
    els.run.textContent = isTriton ? "Run 8 input items" : "Run 8 requests";
    if (actionFeedback) els.actionStatus.textContent = actionFeedback;
    else if (!fresh) els.actionStatus.textContent = "Actions pause until a fresh state is received.";
    else if (!sessionActive()) els.actionStatus.textContent = "The session is not active. Run controls are disabled.";
    else if (!hasReadyPod()) els.actionStatus.textContent = "No ready pod is present in the current observation. Run controls are disabled.";
    else if (latest?.active_lesson !== selectedId) els.actionStatus.textContent = "Only the server-designated active lesson can run.";
    else if (experimentRunning) els.actionStatus.textContent = "An experiment is already running.";
    else if (!lesson?.actions_enabled) els.actionStatus.textContent = lesson?.reason || lesson?.gate || "The operator has disabled this action.";
    else if (!actionBusy && !actionFeedback) els.actionStatus.textContent = isTriton ? `Ready. This run uses 8 input items in ${8 / Number(els.batchSize.value)} requests, with up to ${els.concurrency.value} in-flight requests.` : "Ready. This run uses 8 requests with up to 32 output tokens each.";
  }
  function render() { renderLessonNav(); renderLesson(); renderSession(); renderObservation(); renderExperiment(); renderConnection(); }
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const response = await fetch("/api/state", { headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error(`Operator returned ${response.status}`);
      const state = await response.json();
      latest = state;
      stateFetchFailed = false;
      actionFeedback = "";
      lastSuccessAt = Date.now();
      if (!state.lessons?.some((lesson) => lesson.id === selectedId)) selectedId = state.active_lesson || LESSONS[0].id;
      render();
    } catch (_error) {
      stateFetchFailed = true;
      renderConnection();
      els.connectionText.textContent = "Disconnected · state request failed";
    } finally { refreshing = false; }
  }
  async function runExperiment() {
    if (actionBusy || !isFresh() || !sessionActive()) return;
    const lesson = selectedLesson();
    if (!lesson || !hasReadyPod() || latest.active_lesson !== selectedId || lesson.actions_enabled !== true || latest.experiment?.state === "running") return;
    actionBusy = true;
    actionFeedback = "";
    els.actionStatus.textContent = "Submitting the bounded experiment…";
    renderConnection();
    try {
      const response = await fetch("/api/experiments", {
        method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(selectedId === "04-triton-cpu-serving"
          ? { lesson_id: selectedId, concurrency: Number(els.concurrency.value), batch_size: Number(els.batchSize.value) }
          : { lesson_id: selectedId, concurrency: Number(els.concurrency.value) }),
      });
      if (!response.ok) {
        const message = response.status === 409 ? "An experiment is already running." :
          response.status === 429 ? "The operator is temporarily rate limiting experiment requests." :
          response.status >= 400 && response.status < 500 ? "The operator rejected this request." :
          "The operator could not accept the experiment.";
        actionFeedback = message;
        els.actionStatus.textContent = message;
        return;
      }
      els.actionStatus.textContent = "Accepted. Waiting for the operator result…";
      const experiment = await response.json();
      if (experiment && typeof experiment === "object") latest = { ...latest, experiment };
      await refresh();
      startExperimentPolling();
    } catch (_error) {
      actionFeedback = "Could not reach the operator. Actions will resume after a fresh state.";
      els.actionStatus.textContent = actionFeedback;
    } finally {
      actionBusy = false;
      renderConnection();
    }
  }
  function startExperimentPolling() {
    window.clearInterval(experimentPoll);
    experimentPoll = window.setInterval(async () => {
      if (refreshing) return;
      await refresh();
      if (latest?.experiment?.state !== "running") window.clearInterval(experimentPoll);
    }, 2000);
  }
  els.prediction.addEventListener("input", () => predictions.set(selectedId, els.prediction.value));
  els.run.addEventListener("click", runExperiment);
  refresh();
  window.setInterval(() => { renderSession(); renderConnection(); }, 1000);
  window.setInterval(refresh, 5000);
})();
