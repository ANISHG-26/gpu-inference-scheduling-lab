const INVALID = 'Invalid recorder evidence';
const fail = () => { throw new Error(INVALID); };
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isPositiveFinite = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
const isCounter = value => Number.isSafeInteger(value) && value >= 0;
const supportedSize = value => Number.isSafeInteger(value) && [1, 2, 4, 8].includes(value);
const sameModel = value => isRecord(value) && value.name === 'lab_double' && value.version === '1';

export function validateTarget(url, revision) {
  if (typeof url !== 'string' || typeof revision !== 'string' || !/^[0-9a-fA-F]{40}$/.test(revision)) fail();
  const match = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})\/$/.exec(url);
  if (!match) fail();
  const port = Number(match[1]);
  if (port < 1024 || port > 65535) fail();
  return { baseUrl: `http://127.0.0.1:${port}`, revision };
}

export function readyPodUid(state, expectedUid) {
  if (!isRecord(state) || state.active_lesson !== '04-triton-cpu-serving') fail();
  const session = state.session;
  if (!isRecord(session) || session.status !== 'active' || !Number.isFinite(session.remaining_seconds) || session.remaining_seconds < 180) fail();
  const observation = state.observation;
  if (!isRecord(observation) || observation.status !== 'ok' || !isRecord(observation.placement) || observation.placement.valid !== true || !Array.isArray(observation.pods)) fail();
  const pods = observation.pods.filter(pod => isRecord(pod) && pod.name === 'triton-0');
  if (pods.length !== 1) fail();
  const pod = pods[0];
  if (pod.role !== 'Triton model' || pod.ready !== true || pod.phase !== 'Running' || pod.terminating !== false
      || typeof pod.uid !== 'string' || pod.uid.length === 0 || typeof pod.node !== 'string' || pod.node.length === 0) fail();
  if (expectedUid !== undefined && (typeof expectedUid !== 'string' || expectedUid.length === 0 || pod.uid !== expectedUid)) fail();
  return pod.uid;
}

export function verifyMeasured(state, expected) {
  if (!isRecord(state) || !isRecord(expected)) fail();
  const { id, concurrency, batchSize, uid } = expected;
  if (typeof id !== 'string' || id.length === 0 || !supportedSize(concurrency)
      || !supportedSize(batchSize) || typeof uid !== 'string' || uid.length === 0) fail();
  readyPodUid(state, uid);
  const experiment = state.experiment;
  if (!isRecord(experiment) || experiment.id !== id || experiment.lesson_id !== '04-triton-cpu-serving'
      || experiment.state !== 'measured' || experiment.concurrency !== concurrency || experiment.batch_size !== batchSize) fail();
  const summary = experiment.summary;
  const triton = experiment.triton;
  const expectedRequests = 8 / batchSize;
  if (!isRecord(summary) || !isRecord(triton) || summary.completed !== 8 || summary.errors !== 0
      || summary.requests_completed !== expectedRequests || summary.request_errors !== 0 || !isPositiveFinite(summary.wall_time_seconds)
      || !isPositiveFinite(summary.inferences_per_second) || !isPositiveFinite(summary.p50_latency_seconds)
      || !isPositiveFinite(summary.p95_latency_seconds) || !sameModel(triton.model)) fail();

  const probes = triton.negative_probes;
  if (!isRecord(probes) || probes.invalid_shape_status !== 400 || probes.missing_version_status !== 404) fail();
  const deltas = triton.counter_deltas;
  if (!isRecord(deltas) || deltas.success !== expectedRequests || deltas.inference_count !== 8
      || !Number.isSafeInteger(deltas.execution_count) || deltas.execution_count < 1 || deltas.execution_count > expectedRequests) fail();

  const snapshots = [triton.before, triton.after_inference, triton.after_probes];
  const stats = [];
  for (const snapshot of snapshots) {
    if (!isRecord(snapshot) || snapshot.loaded !== true || snapshot.ready !== true || !sameModel(snapshot.model)
        || !isRecord(snapshot.stats)) fail();
    const row = snapshot.stats;
    if (!isCounter(row.success) || !isCounter(row.inference_count) || !isCounter(row.execution_count)) fail();
    stats.push(row);
  }
  const [before, after, probesAfter] = stats;
  if (after.success - before.success !== deltas.success || after.inference_count - before.inference_count !== deltas.inference_count
      || after.execution_count - before.execution_count !== deltas.execution_count) fail();
  for (const key of ['success', 'inference_count', 'execution_count']) {
    if (after[key] < before[key] || probesAfter[key] < after[key]) fail();
  }

  return {
    concurrency,
    batch_size: batchSize,
    completed_inputs: 8,
    requests_completed: expectedRequests,
    execution_count: deltas.execution_count,
    invalid_shape_status: 400,
    missing_version_status: 404,
  };
}
