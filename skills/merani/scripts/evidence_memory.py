"""Compatibility imports for the relocated SQLite evidence-memory adapter."""

from merani_core.adapters.evidence_memory import (
    SCHEMA_VERSION,
    _connect,
    _connect_read_only,
    _field_relevance,
    _open_database,
    _open_database_read_only,
    _rank_rows,
    _read_object,
    _triage_items,
    compact,
    evidence_relevance,
    normalized_text,
    rebuild,
    search,
    search_many,
    sqlite3,
    status,
    upsert_run,
)
