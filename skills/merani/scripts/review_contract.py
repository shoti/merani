"""Compatibility imports for the relocated review-report domain module."""

from merani_core.domain.review_contract import (
    CLAUDE_REVIEW_SCHEMA,
    REPORT_SECTIONS,
    SEVERITIES,
    duplicate_report_sections,
    markdown_section,
    parse_bullet_test_gaps,
    parse_coverage,
    parse_criteria_coverage,
    parse_json_list_field,
    parse_notes,
    parse_review_report,
    parse_severity_items,
    parsed_report_is_invalid,
    render_field,
    render_structured_review,
    structured_render_is_faithful,
    unparsed_item_sections,
    validate_structured_review,
)
