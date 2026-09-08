"""Compatibility imports for the relocated check-validation domain module."""

from merani_core.domain.validation import (
    ValidationError,
    evaluate_checks,
    normalize_required_checks,
    parse_check_result,
)
