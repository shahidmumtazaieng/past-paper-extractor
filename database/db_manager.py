"""
database/db_manager.py
=======================
Handles all SQLite operations.
Supports multiple PDFs uploaded on different days.
Uses WAL mode for better concurrency and performance.

UPDATED: Added marking scheme support
  - documents.doc_type   TEXT  ('question_paper' | 'marking_scheme')
  - documents.topic      TEXT  (topical book topic, e.g. "Topic 5: The Internet")
  - questions.source_ref TEXT  (e.g. "[Q10(d) Paper 11 M/J/18]")
  All new columns added via safe migration — existing databases auto-upgrade.
"""

import sqlite3
import json
import os
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_db_path() -> str:
    """Return path to SQLite DB in user's AppData/app folder."""
    base = Path.home() / ".past_paper_extractor"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "papers.db")


def get_connection() -> sqlite3.Connection:
    """Get a database connection with performance settings applied."""
    conn = sqlite3.connect(get_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    return conn


def _migrate_db(conn: sqlite3.Connection):
    """
    Run any schema migrations needed on an existing database.
    Safe to call every startup — checks before altering.
    """
    # questions table migrations
    q_cols = [row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()]
    if "question_level" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN question_level INTEGER DEFAULT 0")
        logger.info("Migration applied: added question_level column")
    if "parent_number" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN parent_number TEXT DEFAULT ''")
        logger.info("Migration applied: added parent_number column")
    if "bbox_full" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN bbox_full TEXT NOT NULL DEFAULT '{}'")
        logger.info("Migration applied: added bbox_full column")
    if "source_ref" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN source_ref TEXT DEFAULT ''")
        logger.info("Migration applied: added source_ref column")

    # documents table migrations
    d_cols = [row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if "doc_type" not in d_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN doc_type TEXT DEFAULT 'question_paper'")
        logger.info("Migration applied: added doc_type column")
    if "topic" not in d_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN topic TEXT DEFAULT ''")
        logger.info("Migration applied: added topic column")

    conn.commit()


def init_db():
    """Create all tables and indexes if they don't exist."""
    conn = get_connection()
    try:
        # Step 1: Check if any tables exist
        tables_exist = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('documents', 'questions')"
        ).fetchall()
        
        # Step 2: If tables exist, run migrations FIRST to upgrade schema
        if tables_exist:
            logger.info("Existing database found. Running migrations...")
            _migrate_db(conn)
        
        # Step 3: Create tables and indexes (safe if they already exist)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath    TEXT NOT NULL,
                filename    TEXT NOT NULL,
                file_hash   TEXT NOT NULL UNIQUE,
                doc_type    TEXT DEFAULT 'question_paper',
                level       TEXT,
                subject     TEXT,
                year        INTEGER,
                season      TEXT,
                variant     INTEGER,
                paper       INTEGER,
                topic       TEXT DEFAULT '',
                page_count  INTEGER,
                imported_at TEXT NOT NULL,
                status      TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS questions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                question_number TEXT NOT NULL,
                question_level  INTEGER DEFAULT 0,
                parent_number   TEXT DEFAULT '',
                page_number     INTEGER NOT NULL,
                bbox            TEXT NOT NULL,
                bbox_full       TEXT NOT NULL DEFAULT '{}',
                text_content    TEXT,
                marks           INTEGER,
                source_ref      TEXT DEFAULT '',
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath    TEXT NOT NULL,
                status      TEXT NOT NULL,
                message     TEXT,
                imported_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_docs_level    ON documents(level);
            CREATE INDEX IF NOT EXISTS idx_docs_year     ON documents(year);
            CREATE INDEX IF NOT EXISTS idx_docs_season   ON documents(season);
            CREATE INDEX IF NOT EXISTS idx_docs_variant  ON documents(variant);
            CREATE INDEX IF NOT EXISTS idx_docs_paper    ON documents(paper);
            CREATE INDEX IF NOT EXISTS idx_docs_subject  ON documents(subject);
            CREATE INDEX IF NOT EXISTS idx_docs_type     ON documents(doc_type);
            CREATE INDEX IF NOT EXISTS idx_questions_doc ON questions(document_id);
            CREATE INDEX IF NOT EXISTS idx_questions_num ON questions(question_number);
        """)
        conn.commit()
        
        # Step 4: Run migrations again for fresh installs without tables
        if not tables_exist:
            _migrate_db(conn)
        
        logger.info("Database initialized at %s", get_db_path())
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        raise
    finally:
        conn.close()


def file_hash(filepath: str) -> str:
    """Compute SHA-256 of a file to detect duplicates."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def document_exists(filepath: str) -> Optional[dict]:
    """Check if a document with this file hash is already imported."""
    fhash = file_hash(filepath)
    conn  = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE file_hash = ?", (fhash,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_document(
    filepath:   str,
    level:      str,
    subject:    str,
    year:       int,
    season:     str,
    variant:    int,
    paper:      int,
    page_count: int,
    doc_type:   str = "question_paper",   # NEW — 'question_paper' | 'marking_scheme'
    topic:      str = "",                  # NEW — topical book topic
) -> int:
    """Insert a new document record. Returns the new document ID."""
    conn = get_connection()
    try:
        fhash = file_hash(filepath)
        cur   = conn.execute(
            """INSERT INTO documents
               (filepath, filename, file_hash, doc_type, level, subject, year, season,
                variant, paper, topic, page_count, imported_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                filepath,
                os.path.basename(filepath),
                fhash,
                doc_type,
                level,
                subject,
                year,
                season,
                variant,
                paper,
                topic,
                page_count,
                datetime.now().isoformat(),
                "pending",
            ),
        )
        conn.commit()
        doc_id = cur.lastrowid
        logger.info("Document inserted: id=%d, type=%s, file=%s", doc_id, doc_type, filepath)
        return doc_id
    finally:
        conn.close()


def update_document_status(doc_id: int, status: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE documents SET status=? WHERE id=?", (status, doc_id))
        conn.commit()
    finally:
        conn.close()


def insert_questions_batch(questions: list[dict]):
    """Bulk insert questions for speed. Works for both question papers and marking schemes."""
    if not questions:
        return
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.executemany(
            """INSERT INTO questions
               (document_id, question_number, question_level, parent_number,
                page_number, bbox, bbox_full, text_content, marks, source_ref, created_at)
               VALUES (:document_id, :question_number, :question_level, :parent_number,
                       :page_number, :bbox, :bbox_full, :text_content, :marks,
                       :source_ref, :created_at)""",
            [{
                **q,
                "question_level": q.get("question_level", 0),
                "parent_number":  q.get("parent_number", ""),
                "bbox_full":      q.get("bbox_full", q.get("bbox", "{}")),
                "source_ref":     q.get("source_ref", ""),   # NEW
                "created_at":     now,
            } for q in questions],
        )
        conn.commit()
        logger.info("Inserted %d questions", len(questions))
    finally:
        conn.close()


def query_questions(
    level:           str = None,
    subject:         str = None,
    year:            int = None,
    season:          str = None,
    variant:         int = None,
    paper:           int = None,
    question_number: str = None,
    question_level:  int = None,    # 0=main only, 1=sub, 2=subsub, None=all
    doc_type:        str = None,    # NEW: 'question_paper' | 'marking_scheme' | None=both
    topic:           str = None,    # NEW: filter by topic (marking schemes)
) -> list[dict]:
    """
    Flexible filtered query. Any param can be None (ignored).
    Returns list of question dicts with document metadata joined.
    """
    wheres = ["d.status = 'indexed'"]
    params = []

    if level:
        wheres.append("d.level = ?");             params.append(level)
    if subject:
        wheres.append("d.subject = ?");           params.append(subject)
    if year:
        wheres.append("d.year = ?");              params.append(year)
    if season:
        wheres.append("d.season = ?");            params.append(season)
    if variant:
        wheres.append("d.variant = ?");           params.append(variant)
    if paper:
        wheres.append("d.paper = ?");             params.append(paper)
    if question_number:
        wheres.append("q.question_number LIKE ?"); params.append(f"{question_number}%")
    if question_level is not None:
        wheres.append("q.question_level = ?");    params.append(question_level)
    if doc_type:
        wheres.append("d.doc_type = ?");          params.append(doc_type)
    if topic:
        wheres.append("d.topic LIKE ?");          params.append(f"%{topic}%")

    where_clause = " AND ".join(wheres)
    sql = f"""
        SELECT
            q.id, q.question_number, q.question_level, q.parent_number,
            q.page_number, q.bbox, q.bbox_full, q.text_content, q.marks,
            q.source_ref,
            d.id AS doc_id, d.filepath, d.filename,
            d.doc_type, d.level, d.subject, d.year, d.season, d.variant, d.paper,
            d.topic
        FROM questions q
        JOIN documents d ON q.document_id = d.id
        WHERE {where_clause}
        ORDER BY d.year DESC, d.season, d.variant, d.paper,
                 q.page_number, q.id
    """
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_documents() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY imported_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_document(doc_id: int):
    """Remove a document and all its questions (CASCADE)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def get_filter_options() -> dict:
    """Return distinct values for each filter dropdown."""
    conn = get_connection()
    try:
        def distinct(col):
            rows = conn.execute(
                f"SELECT DISTINCT {col} FROM documents WHERE status='indexed' "
                f"AND {col} IS NOT NULL ORDER BY {col}"
            ).fetchall()
            return [r[0] for r in rows if r[0]]

        def distinct_topics():
            rows = conn.execute(
                "SELECT DISTINCT topic FROM documents WHERE status='indexed' "
                "AND topic IS NOT NULL AND topic != '' ORDER BY topic"
            ).fetchall()
            return [r[0] for r in rows if r[0]]

        return {
            "levels":   distinct("level"),
            "subjects": distinct("subject"),
            "years":    [str(y) for y in distinct("year")],
            "seasons":  distinct("season"),
            "variants": [str(v) for v in distinct("variant")],
            "papers":   [str(p) for p in distinct("paper")],
            "topics":   distinct_topics(),          # NEW
            "doc_types": ["question_paper", "marking_scheme"],  # NEW
        }
    finally:
        conn.close()


def log_import(filepath: str, status: str, message: str = ""):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO import_log (filepath, status, message, imported_at) VALUES (?,?,?,?)",
            (filepath, status, message, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()