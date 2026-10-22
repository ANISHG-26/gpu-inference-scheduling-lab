"""Source arithmetic with a utility fixture, not Triton runtime acceptance."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class TeachingModelTests(unittest.TestCase):
    def test_each_request_returns_doubled_fp32_tensor_without_changing_input(self):
        class Tensor:
            def __init__(self, name, value):
                self.name, self.value = name, value

            def as_numpy(self):
                return self.value

        fixture = SimpleNamespace(
            get_input_tensor_by_name=lambda request, name: request[name],
            Tensor=Tensor,
            InferenceResponse=lambda output_tensors: output_tensors,
        )
        spec = importlib.util.spec_from_file_location("lab_double", ROOT / "lessons/04-triton-cpu-serving/model-repository/lab_double/1/model.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"triton_python_backend_utils": fixture}):
            spec.loader.exec_module(module)
            inputs = [np.array([[1, -2, 0, 3.5]], dtype=np.float32), np.ones((2, 4), dtype=np.float32)]
            copies = [value.copy() for value in inputs]
            results = module.TritonPythonModel().execute([{"INPUT": Tensor("INPUT", value)} for value in inputs])
        self.assertEqual(len(results), 2)
        for result, original, unchanged in zip(results, copies, inputs):
            self.assertEqual(result[0].name, "OUTPUT")
            self.assertEqual(result[0].as_numpy().dtype, np.float32)
            np.testing.assert_array_equal(result[0].as_numpy(), original * 2)
            np.testing.assert_array_equal(unchanged, original)


if __name__ == "__main__":
    unittest.main()
