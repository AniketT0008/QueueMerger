"""Explanation Memory: reusable teaching notes keyed to misconception root causes.

This deliberately attaches notes to taxonomy nodes, not transient cluster IDs.
Clusters are rebuilt whenever the queue changes, but the underlying misconception
is stable. That means a useful explanation written for one cluster can resurface
for a completely different cluster later in the session or in a later semester
when the SQLite database is persisted to disk.
"""
from queuemerge import db as dbm


def _cluster_node_id(conn, cluster_id: int):
    with dbm.cursor(conn) as cur:
        row = cur.execute(
            "SELECT taxonomy_node_id, course_id FROM clusters WHERE id = ?", (cluster_id,)
        ).fetchone()
    if row is None:
        return None
    return int(row["taxonomy_node_id"]), int(row["course_id"])


def add_note(conn, cluster_id: int, note_text: str) -> int:
    """Store a reusable explanation note for the cluster's root-cause node."""
    text = (note_text or "").strip()
    if not text:
        raise ValueError("Explanation note cannot be empty")

    resolved = _cluster_node_id(conn, cluster_id)
    if resolved is None:
        raise ValueError(f"Unknown cluster_id: {cluster_id}")
    node_id, course_id = resolved
    ts = dbm.now()

    with dbm.cursor(conn) as cur:
        cur.execute(
            "INSERT INTO explanation_notes "
            "(course_id, taxonomy_node_id, source_cluster_id, note_text, upvotes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (course_id, node_id, cluster_id, text, ts, ts),
        )
        return int(cur.lastrowid)


def notes_for_cluster(conn, cluster_id: int, limit: int = 5) -> list:
    """Return the best prior notes for this cluster's root cause.

    Ranking is intentionally transparent: most upvoted first, then most recent.
    The source cluster may be old/superseded; that is the point of the feature.
    """
    resolved = _cluster_node_id(conn, cluster_id)
    if resolved is None:
        return []
    node_id, course_id = resolved
    return notes_for_node(conn, course_id, node_id, limit=limit)


def notes_for_node(conn, course_id: int, taxonomy_node_id: int, limit: int = 5) -> list:
    with dbm.cursor(conn) as cur:
        rows = cur.execute(
            "SELECT en.*, tn.name AS node_name "
            "FROM explanation_notes en "
            "JOIN taxonomy_nodes tn ON tn.id = en.taxonomy_node_id "
            "WHERE en.course_id = ? AND en.taxonomy_node_id = ? "
            "ORDER BY en.upvotes DESC, en.updated_at DESC, en.id DESC LIMIT ?",
            (course_id, taxonomy_node_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def upvote_note(conn, note_id: int) -> int:
    """Add one usefulness vote and return the new vote count."""
    with dbm.cursor(conn) as cur:
        row = cur.execute(
            "SELECT upvotes FROM explanation_notes WHERE id = ?", (note_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown note_id: {note_id}")
        new_count = int(row["upvotes"]) + 1
        cur.execute(
            "UPDATE explanation_notes SET upvotes = ?, updated_at = ? WHERE id = ?",
            (new_count, dbm.now(), note_id),
        )
    return new_count
