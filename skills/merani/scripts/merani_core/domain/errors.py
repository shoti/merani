"""Shared failures raised by the Merani domain and application layers."""


class ReviewError(RuntimeError):
    """A user-actionable review workflow failure."""
