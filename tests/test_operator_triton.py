"""Triton topology and admission boundaries; no live runtime acceptance."""
import os
import http.client
import json
import threading
import time
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from inference_lab import operator

LESSON = '04-triton-cpu-serving'


def triton_pod(name='triton-0', uid='t0', owner='triton', ready=True):
    return {'metadata': {'name': name, 'uid': uid, 'labels': {'app': 'triton'},
            'ownerReferences': [{'controller': True, 'kind': 'StatefulSet', 'name': owner}]},
            'spec': {'nodeName': 'node-a'}, 'status': {'phase': 'Running',
            'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]}}


class TritonOperatorTests(unittest.TestCase):
    def test_one_owned_ready_model_and_stable_uid_are_required(self):
        pods = operator._safe_pods([triton_pod()])
        self.assertTrue(operator._placement(LESSON, pods)['valid'])
        self.assertEqual(operator._serving_uids(LESSON, pods), {'t0'})
        for raw in ([triton_pod(ready=False)], [triton_pod(owner='other')],
                    [triton_pod(), triton_pod('triton-1', 't1')], [triton_pod(uid='')]):
            self.assertFalse(operator._placement(LESSON, operator._safe_pods(raw))['valid'])

    def test_payload_is_fixed_per_adapter(self):
        self.assertEqual(operator._experiment_input({'lesson_id': LESSON, 'concurrency': 4, 'batch_size': 2}), (LESSON, 4, 2))
        self.assertEqual(operator._experiment_input({'lesson_id': '01-single-node-inference', 'concurrency': 1}), ('01-single-node-inference', 1, None))
        for extra in ({'url': 'http://invalid.example'}, {'model': 'other'}, {'command': 'anything'}):
            self.assertIsNone(operator._experiment_input({'lesson_id': LESSON, 'concurrency': 1, 'batch_size': 1, **extra}))
        for value in (True, 0, 3, '4', None):
            self.assertIsNone(operator._experiment_input({'lesson_id': LESSON, 'concurrency': 1, 'batch_size': value}))

    def test_preparation_gate_cannot_be_enabled_by_environment(self):
        with patch.dict(os.environ, {'ACTIVE_LESSON': LESSON, 'LAB_ACTIONS_ENABLED': 'true'}), patch.object(operator, '_catalog', return_value=({'id': LESSON, 'gate': 'unmeasured disk'},)):
            self.assertFalse(operator._lesson_gate_open(LESSON))


class TritonAdmissionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = operator._BoundedServer(('127.0.0.1', 0), operator.OperatorHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.env = patch.dict(os.environ, {'ACTIVE_LESSON': LESSON, 'LAB_ACTIONS_ENABLED': 'true', 'LAB_EXPIRES_AT': str(int(time.time()) + 1000)})
        self.env.start()
        self.pods = patch.object(operator, '_list_pods', return_value=[triton_pod()])
        self.pods.start()
        operator.EXPERIMENT = None
        operator.EXPERIMENT_RUNNING = False

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.pods.stop(); self.env.stop()
        operator.EXPERIMENT = None
        operator.EXPERIMENT_RUNNING = False

    def post(self, payload):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        connection.request('POST', '/api/experiments', json.dumps(payload), {'Origin': f'http://127.0.0.1:{self.port}', 'Content-Type': 'application/json'})
        response = connection.getresponse()
        value = json.loads(response.read())
        status = response.status
        connection.close()
        return status, value

    def test_prepared_runtime_gate_blocks_http_dispatch_even_with_ready_pod(self):
        with patch.object(operator.triton, 'run_experiment') as execute:
            status, value = self.post({'lesson_id': LESSON, 'concurrency': 4, 'batch_size': 4})
        self.assertEqual(status, 503)
        self.assertEqual(value['error'], 'lesson_unavailable')
        execute.assert_not_called()

    def test_fixture_open_gate_uses_fixed_adapter_and_input_units(self):
        catalog = tuple({**item, 'gate': None} if item['id'] == LESSON else item for item in operator._catalog())
        result = {'summary': {'completed': 8, 'errors': 0, 'requests_completed': 2, 'request_errors': 0,
                  'p50_ms': 2.0, 'p95_ms': 3.0, 'wall_seconds': .02, 'inferences_per_second': 400},
                  'triton': {'counter_deltas': {'success': 2, 'inference_count': 8, 'execution_count': 2}}, 'error': None}
        with patch.object(operator, '_catalog', return_value=catalog), patch.object(operator.triton, 'run_experiment', return_value=result) as execute:
            status, _ = self.post({'lesson_id': LESSON, 'concurrency': 4, 'batch_size': 4})
            self.assertEqual(status, 202)
            deadline = time.monotonic() + 2
            while operator.EXPERIMENT_RUNNING and time.monotonic() < deadline:
                time.sleep(.01)
            state = operator.state()['experiment']
        self.assertEqual(execute.call_args.args[:2], (4, 4))
        self.assertEqual(state['state'], 'measured')
        self.assertEqual(state['summary']['completed'], 8)
        self.assertEqual(state['summary']['requests_completed'], 2)
        self.assertEqual(state['summary']['p50_latency_seconds'], .002)
        self.assertNotIn('completion_tokens_per_second', state['summary'])
        self.assertEqual(state['triton']['mean_batch_size'], 4)


if __name__ == '__main__':
    unittest.main()
