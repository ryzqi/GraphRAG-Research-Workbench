from __future__ import annotations


class ModelConfigIncompleteError(RuntimeError):
    """Raised when model runtime configuration is missing required fields."""

