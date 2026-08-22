"""Pipeline stage 2: misconception extraction.

Takes a raw question and assigns it to a taxonomy node (or proposes a new
bootstrapped one), trying Gemini first and falling back to the heuristic
extractor on any failure. This is the fallback boundary the user asked for:
Gemini is the "main" path, heuristic is what keeps the system working with
no key, no network, or a failed/malformed call.
"""
import json
from queuemerge import db as dbm
from queuemerge import taxonomy as tax
from queuemerge.llm_client import HeuristicExtractor, GeminiExtractor

_heuristic = HeuristicExtractor()


def _get_extractor(prefer_gemini: bool):
    if prefer_gemini:
        try:
            return GeminiExtractor()
        except Exception:
            return None
    return None


def extract_for_question(conn, question_id: int, prefer_gemini: bool = True) -> dict:
    with dbm.cursor(conn) as cur:
        q = cur.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    q = dict(q)
    nodes = tax.list_nodes(conn, q["course_id"])

    result = None
    gem = _get_extractor(prefer_gemini)
    if gem is not None:
        try:
            result = gem.extract(q["raw_text"], q["code_snippet"], q["error_message"], nodes)
        except Exception:
            result = None  # fall through to heuristic
    if result is None:
        result = _heuristic.extract(q["raw_text"], q["code_snippet"], q["error_message"], nodes)

    node_id = result.get("node_id")
    if node_id is None:
        # No confident match against the existing taxonomy -> bootstrap live.
        proposal = result.get("proposed_new_node") or {
            "name": result.get("node_name") or f"candidate-q{question_id}",
            "description": "Auto-bootstrapped node pending TA review.",
            "keywords": [],
        }
        node_id = tax.create_bootstrapped_node(
            conn, q["course_id"], proposal["name"], proposal["description"],
            proposal.get("keywords", []),
        )

    with dbm.cursor(conn) as cur:
        cur.execute(
            "UPDATE questions SET taxonomy_node_id = ?, extraction_confidence = ?, "
            "evidence_json = ? WHERE id = ?",
            (node_id, result["confidence"], json.dumps(result["evidence"]), question_id),
        )
    result["node_id"] = node_id
    return result


def intake_question(conn, course_id: int, student_name: str, raw_text: str,
                     code_snippet: str = None, error_message: str = None,
                     prefer_gemini: bool = True, created_at: float = None) -> int:
    """Full intake: register student if new, insert question, run extraction.
    Returns the new question id. `created_at` lets the eval harness replay a
    synthetic timeline with reproducible timestamps instead of wall-clock
    time; live callers (the UI) should leave it as None."""
    if not (student_name or "").strip():
        raise ValueError("student_name is required")
    if not (raw_text or "").strip():
        raise ValueError("question text is required")
    student_name = student_name.strip()
    raw_text = raw_text.strip()

    with dbm.cursor(conn) as cur:
        row = cur.execute(
            "SELECT id FROM students WHERE course_id = ? AND name = ?", (course_id, student_name)
        ).fetchone()
        if row:
            student_id = row["id"]
        else:
            cur.execute("INSERT INTO students (course_id, name) VALUES (?, ?)",
                        (course_id, student_name))
            student_id = cur.lastrowid

        cur.execute(
            "INSERT INTO questions (course_id, student_id, raw_text, code_snippet, "
            "error_message, created_at, status) VALUES (?, ?, ?, ?, ?, ?, 'waiting')",
            (course_id, student_id, raw_text, code_snippet, error_message,
             created_at if created_at is not None else dbm.now()),
        )
        question_id = cur.lastrowid

    extract_for_question(conn, question_id, prefer_gemini=prefer_gemini)
    return question_id
