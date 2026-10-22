"""Deterministic tensor teaching model; requires the selected Triton Python ABI."""
import triton_python_backend_utils as pb_utils


class TritonPythonModel:
    def execute(self, requests):
        responses = []
        for request in requests:
            tensor = pb_utils.get_input_tensor_by_name(request, "INPUT")
            output = tensor.as_numpy() * 2.0
            responses.append(pb_utils.InferenceResponse(
                output_tensors=[pb_utils.Tensor("OUTPUT", output)]
            ))
        return responses
