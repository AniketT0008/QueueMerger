"""SQLite data model for QueueMerge.

Tables map directly onto the data model in ARCHITECTURE.md:
courses, taxonomy_nodes, students, questions, clusters, cluster_members,
ta_sessions, ta_actions, outcomes, outbreak_alerts, feedback_events, explanation_notes.
"""
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS taxonomy_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    keywords TEXT NOT NULL,           -- JSON list of keyword/phrase strings
    is_bootstrapped INTEGER NOT NULL DEFAULT 0,  -- 1 if auto-created, pending TA approval
    approved INTEGER NOT NULL DEFAULT 1,
    mean_explain_minutes REAL NOT NULL DEFAULT 5.0,  -- EWMA of TA minutes to resolve
    explain_minutes_n INTEGER NOT NULL DEFAULT 0,
    confidence_weight REAL NOT NULL DEFAULT 1.0,  -- reweighted by feedback loop
    created_at REAL NOT NULL,
    FOREIGN KEY(course_id) REFERENCES courses(id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY(course_id) REFERENCES courses(id)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    code_snippet TEXT,
    error_message TEXT,
    created_at REAL NOT NULL,
    taxonomy_node_id INTEGER,
    extraction_confidence REAL,
    evidence_json TEXT,                -- JSON: matched keywords, sub-step guess, source (heuristic/gemini)
    cluster_id INTEGER,
    status TEXT NOT NULL DEFAULT 'waiting',  -- waiting/resolved/still_stuck/escalated
    resolved_at REAL,
    FOREIGN KEY(course_id) REFERENCES courses(id),
    FOREIGN KEY(student_id) REFERENCES students(id),
    FOREIGN KEY(taxonomy_node_id) REFERENCES taxonomy_nodes(id)
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    taxonomy_node_id INTEGER NOT NULL,
    sub_key TEXT,                      -- evidence sub-key that split this cluster off its node, if any
    explanation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active/resolved/merged
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(course_id) REFERENCES courses(id),
    FOREIGN KEY(taxonomy_node_id) REFERENCES taxonomy_nodes(id)
);

CREATE TABLE IF NOT EXISTS cluster_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    joined_at REAL NOT NULL,
    left_at REAL,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id),
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS ta_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    ta_name TEXT NOT NULL,
    started_at REAL NOT NULL,
    FOREIGN KEY(course_id) REFERENCES courses(id)
);

CREATE TABLE IF NOT EXISTS ta_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    action_type TEXT NOT NULL,   -- helped_cluster/helped_single/simulated/dismissed_outbreak
    cluster_id INTEGER,
    question_id INTEGER,
    minutes_spent REAL,
    timestamp REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    label TEXT NOT NULL,   -- resolved/still_stuck/escalated
    timestamp REAL NOT NULL,
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS outbreak_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    taxonomy_node_id INTEGER NOT NULL,
    fired_at REAL NOT NULL,
    dismissed_at REAL,
    confidence REAL NOT NULL,
    trend TEXT NOT NULL,          -- climbing/plateauing/declining
    observed_rate REAL NOT NULL,
    baseline_rate REAL NOT NULL,
    estimated_minutes_saved REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open/acknowledged/dismissed
    FOREIGN KEY(course_id) REFERENCES courses(id),
    FOREIGN KEY(taxonomy_node_id) REFERENCES taxonomy_nodes(id)
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    ta_label TEXT NOT NULL,   -- resolved/partially_resolved/misclustered
    minutes_spent REAL,
    timestamp REAL NOT NULL,
    FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);

CREATE TABLE IF NOT EXISTS explanation_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    taxonomy_node_id INTEGER NOT NULL,
    source_cluster_id INTEGER,
    note_text TEXT NOT NULL,
    upvotes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(course_id) REFERENCES courses(id),
    FOREIGN KEY(taxonomy_node_id) REFERENCES taxonomy_nodes(id),
    FOREIGN KEY(source_cluster_id) REFERENCES clusters(id)
);

CREATE INDEX IF NOT EXISTS idx_explanation_notes_node
ON explanation_notes(course_id, taxonomy_node_id, upvotes DESC, updated_at DESC);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@contextmanager
def cursor(conn: sqlite3.Connection):
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        cur.close()


def now() -> float:
    return time.time()
