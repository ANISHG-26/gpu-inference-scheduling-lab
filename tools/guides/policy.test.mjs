import test from 'node:test';
import assert from 'node:assert/strict';
import { validateTarget, readyPodUid, verifyMeasured } from './policy.mjs';

const revision = '0123456789abcdef0123456789abcdef01234567';
const uid = 'pod-uid-private';

function baseState() {
  return {
    active_lesson: '04-triton-cpu-serving',
    session: { status: 'active', remaining_seconds: 240 },
    observation: {
      status: 'ok', placement: { valid: true },
      pods: [{ name: 'triton-0', role: 'Triton model', ready: true, phase: 'Running', terminating: false, uid, node: 'node-private' }],
    },
    experiment: {
      id: 'experiment-private', lesson_id: '04-triton-cpu-serving', state: 'measured', concurrency: 2, batch_size: 4,
      summary: { completed: 8, errors: 0, requests_completed: 2, request_errors: 0, wall_time_seconds: 2, inferences_per_second: 4, p50_latency_seconds: 0.2, p95_latency_seconds: 0.3 },
      triton: {
        model: { name: 'lab_double', version: '1' },
        negative_probes: { invalid_shape_status: 400, missing_version_status: 404 },
        counter_deltas: { success: 2, inference_count: 8, execution_count: 2 },
        before: { loaded: true, ready: true, model: { name: 'lab_double', version: '1' }, stats: { success: 10, inference_count: 40, execution_count: 10 } },
        after_inference: { loaded: true, ready: true, model: { name: 'lab_double', version: '1' }, stats: { success: 12, inference_count: 48, execution_count: 12 } },
        after_probes: { loaded: true, ready: true, model: { name: 'lab_double', version: '1' }, stats: { success: 12, inference_count: 48, execution_count: 12 } },
      },
    },
  };
}

test('validates only a loopback HTTP target and exact commit revision', () => {
  assert.deepEqual(validateTarget(`http://127.0.0.1:8080/`, revision), { baseUrl: 'http://127.0.0.1:8080', revision });
  for (const url of [
    'http://localhost:8080/', 'https://127.0.0.1:8080/', 'http://127.0.0.1/',
    'http://127.0.0.1:80/', 'http://127.0.0.1:65536/', 'http://user@127.0.0.1:8080/',
    'http://127.0.0.1:8080/api', 'http://127.0.0.1:8080/?x=1', 'http://127.0.0.1:8080/#x',
  ]) assert.throws(() => validateTarget(url, revision), Error);
  assert.throws(() => validateTarget('http://127.0.0.1:8080/', 'not-a-revision'), Error);
});

test('requires the active lesson, session budget, valid placement, and one ready model pod', () => {
  const state = baseState();
  assert.equal(readyPodUid(state), uid);
  assert.equal(readyPodUid(state, uid), uid);
  for (const mutate of [
    s => { s.active_lesson = 'other'; },
    s => { s.session.status = 'expired'; },
    s => { s.session.remaining_seconds = 179; },
    s => { s.observation.status = 'error'; },
    s => { s.observation.placement.valid = false; },
    s => { s.observation.pods.push({ ...s.observation.pods[0] }); },
    s => { s.observation.pods[0].ready = false; },
    s => { s.observation.pods[0].phase = 'Pending'; },
    s => { s.observation.pods[0].terminating = true; },
    s => { s.observation.pods[0].uid = ''; },
    s => { s.observation.pods[0].node = ''; },
  ]) {
    const bad = baseState(); mutate(bad);
    assert.throws(() => readyPodUid(bad), Error);
  }
  assert.throws(() => readyPodUid(state, 'another-uid'), Error);
  assert.throws(() => readyPodUid({ ...state, session: { ...state.session, remaining_seconds: true } }), Error);
});

test('returns only verified public experiment metrics and statuses', () => {
  const state = baseState();
  const result = verifyMeasured(state, { id: 'experiment-private', concurrency: 2, batchSize: 4, uid });
  assert.deepEqual(result, {
    concurrency: 2, batch_size: 4, completed_inputs: 8, requests_completed: 2,
    execution_count: 2, invalid_shape_status: 400, missing_version_status: 404,
  });
  assert.doesNotMatch(JSON.stringify(result), /uid|node|host|experiment-private|pod-uid-private/i);
});

test('uses eight divided by batch size for request count at batch sizes one and four', () => {
  for (const batchSize of [1, 4]) {
    const state = baseState();
    const requests = 8 / batchSize;
    state.experiment.batch_size = batchSize;
    state.experiment.summary.requests_completed = requests;
    state.experiment.triton.counter_deltas.success = requests;
    state.experiment.triton.counter_deltas.execution_count = requests;
    for (const key of ['after_inference', 'after_probes']) {
      state.experiment.triton[key].stats.success = 10 + requests;
      state.experiment.triton[key].stats.inference_count = 48;
      state.experiment.triton[key].stats.execution_count = 10 + requests;
    }
    const output = verifyMeasured(state, { id: 'experiment-private', concurrency: 2, batchSize, uid });
    assert.equal(output.requests_completed, requests);
  }
  const unsupported = baseState();
  unsupported.experiment.batch_size = 3;
  assert.throws(() => verifyMeasured(unsupported, { id: 'experiment-private', concurrency: 2, batchSize: 3, uid }), Error);
});

test('rejects tampered experiment identity, counters, model identity, and non-finite metrics', () => {
  for (const mutate of [
    s => { s.experiment.id = 'other'; },
    s => { s.experiment.lesson_id = 'other'; },
    s => { s.experiment.state = 'failed'; },
    s => { s.experiment.concurrency = true; },
    s => { s.experiment.batch_size = 8; },
    s => { s.experiment.summary.completed = 7; },
    s => { s.experiment.summary.requests_completed = 7; },
    s => { s.experiment.triton.counter_deltas.success = 1; },
    s => { s.experiment.triton.counter_deltas.inference_count = 7; },
    s => { s.experiment.triton.counter_deltas.execution_count = 0; },
    s => { s.experiment.triton.after_inference.stats.inference_count++; },
    s => { s.experiment.triton.after_probes.stats.execution_count--; },
    s => { s.experiment.triton.after_probes.ready = false; },
    s => { s.experiment.triton.after_inference.model.name = 'other'; },
    s => { s.experiment.triton.negative_probes.invalid_shape_status = 200; },
    s => { s.experiment.summary.p95_latency_seconds = Infinity; },
    s => { s.experiment.summary.wall_time_seconds = NaN; },
  ]) {
    const bad = baseState(); mutate(bad);
    assert.throws(() => verifyMeasured(bad, { id: 'experiment-private', concurrency: 2, batchSize: 4, uid }), Error);
  }
  const state = baseState();
  assert.throws(() => verifyMeasured(state, { id: 'experiment-private', concurrency: 2, batchSize: 4, uid: 'changed' }), Error);
});
