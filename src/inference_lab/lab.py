"""Console entry point for the inference lab lifecycle controller."""

from .lifecycle import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
