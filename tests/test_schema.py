from sqlalchemy import inspect, text

SPEC_TABLES = {
    "patient",
    "consent",
    "document",
    "doc_chunk",
    "doctor",
    "specialty",
    "clinic",
    "slot",
    "appointment",
    "encounter",
    "clinical_note",
    "prescription",
    "medicine_stock",
    "audit_event",
    "desk_ticket",
    "sms_outbox",
    "idempotency_record",
    "ingest_job",
    "quarantined_chunk",
    "embedding_cache",
}


def test_all_spec_tables_exist(database):
    # LangGraph's checkpointer owns its own tables
    tables = {t for t in inspect(database).get_table_names() if not t.startswith("checkpoint")} - {
        "alembic_version"
    }
    assert tables == SPEC_TABLES


def test_vector_column_and_indexes(database):
    with database.connect() as conn:
        assert conn.scalar(text("SELECT extname FROM pg_extension WHERE extname='vector'"))
        indexes = {
            row.indexname: row.indexdef
            for row in conn.execute(text("SELECT indexname, indexdef FROM pg_indexes"))
        }
    assert "hnsw" in indexes["ix_doc_chunk_embedding_hnsw"]
    assert "gin" in indexes["ix_doc_chunk_tsv"]


def test_safety_triggers_installed(database):
    with database.connect() as conn:
        triggers = set(conn.scalars(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")))
    assert {
        "audit_event_append_only",
        "audit_event_no_truncate",
        "clinical_note_signed_immutable",
        "appointment_token_within_capacity",
    } <= triggers
