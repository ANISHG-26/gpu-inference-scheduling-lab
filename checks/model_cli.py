"""Parse the deployed vLLM command with its pinned image's own CLI parser."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "k8s" / "base" / "model.yaml"

PARSER_CONTRACT = r"""
import sys

import vllm
from vllm.entrypoints.openai.cli_args import (
    make_arg_parser,
    validate_parsed_serve_args,
)
from vllm.utils.argparse_utils import FlexibleArgumentParser

assert vllm.__version__ == "0.27.1", vllm.__version__
parser = make_arg_parser(FlexibleArgumentParser(prog="vllm serve"))
args = parser.parse_args(sys.argv[1:])
validate_parsed_serve_args(args)

assert args.model_tag == "Qwen/Qwen3-0.6B", args.model_tag
assert args.revision == "c1899de289a04d12100db370d81485cdf75e47ca"
assert args.tokenizer_revision == "c1899de289a04d12100db370d81485cdf75e47ca"
assert args.dtype == "float32", args.dtype
assert args.max_model_len == 1024, args.max_model_len
assert args.max_num_seqs == 8, args.max_num_seqs
assert args.kv_cache_memory_bytes == 1073741824, args.kv_cache_memory_bytes
assert args.enable_log_requests is False, args.enable_log_requests
print("Pinned vLLM serve command parsed and validated without loading a model.")
"""


def deployed_model_container() -> tuple[str, list[str]]:
    documents = yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8"))
    for document in documents:
        if (
            document
            and document.get("kind") == "StatefulSet"
            and document.get("metadata", {}).get("name") == "vllm"
        ):
            containers = document["spec"]["template"]["spec"]["containers"]
            model = next(
                container for container in containers if container["name"] == "model"
            )
            image = model["image"]
            args = model["args"]
            if "@sha256:" not in image:
                raise ValueError(f"Model image must be pinned by digest: {image}")
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError("Model container args must be a list of strings")
            return image, args
    raise ValueError("Could not find StatefulSet/vllm model container")


def main() -> int:
    image, args = deployed_model_container()
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--pull=missing",
        "--entrypoint",
        "python",
        "-e",
        "HF_HUB_OFFLINE=1",
        "-e",
        "TRANSFORMERS_OFFLINE=1",
        image,
        "-c",
        PARSER_CONTRACT,
        *args,
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
