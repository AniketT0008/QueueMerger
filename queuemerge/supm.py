"""Pipeline stage 4: SUPM (students-unblocked-per-TA-minute) scoring.

SUPM = expected_students_unblocked / expected_ta_minutes

- expected_students_unblocked: cluster size discounted by average clustering
  confidence (a low-confidence cluster of 6 is treated as "worth less" than
  a high-confidence one, since some members may turn out misclustered and
  not actually get unblocked by a single explanation).
- expected_ta_minutes: the taxonomy node's running estimate of how long one
  explanation takes (mean_explain_minutes, an EWMA updated by the feedback
  loop) plus a small per-extra-student overhead for a group vs 1-on-1
  (fielding follow-up questions, walking through 2-3 individual code diffs).

Every score is returned with its inputs attached so the TA UI can show the
arithmetic instead of a bare number, per the spec's "not hidden" requirement.
"""
from queuemerge import db as dbm

PER_EXTRA_STUDENT_OVERHEAD_MIN = 0.6  # minutes added per member beyond the first
SINGLE_STUDENT_BASE_MIN = 4.0  # default explain time for an ungrouped single student


def score_cluster(conn, cluster: dict) -> dict:
    node = _get_node(conn, cluster["taxonomy_node_id"])
    size = cluster["size"]
    avg_conf = cluster.get("avg_confidence", 0.5)

    expected_unblocked = size * max(0.15, avg_conf)  # floor so a cluster is never "worthless"
    base_minutes = node["mean_explain_minutes"]
    expected_minutes = base_minutes + PER_EXTRA_STUDENT_OVERHEAD_MIN * max(0, size - 1)
    expected_minutes = max(1.0, expected_minutes)

    supm = expected_unblocked / expected_minutes
    return {
        "cluster_id": cluster["cluster_id"] if "cluster_id" in cluster else cluster.get("id"),
        "supm": round(supm, 4),
        "inputs": {
            "cluster_size": size,
            "avg_clustering_confidence": round(avg_conf, 3),
            "expected_students_unblocked": round(expected_unblocked, 2),
            "node_mean_explain_minutes": round(base_minutes, 2),
            "group_overhead_minutes": round(PER_EXTRA_STUDENT_OVERHEAD_MIN * max(0, size - 1), 2),
            "expected_ta_minutes": round(expected_minutes, 2),
        },
    }


def score_single_student(conn, question: dict) -> dict:
    """SUPM for the 'just help the single longest-waiting student' option,
    for comparison against clusters (the tie/edge-case the spec calls out)."""
    expected_unblocked = 1.0 * max(0.15, question.get("extraction_confidence") or 0.5)
    minutes = SINGLE_STUDENT_BASE_MIN
    supm = expected_unblocked / minutes
    return {
        "question_id": question["id"],
        "supm": round(supm, 4),
        "inputs": {
            "cluster_size": 1,
            "avg_clustering_confidence": round(question.get("extraction_confidence") or 0.5, 3),
            "expected_students_unblocked": round(expected_unblocked, 2),
            "node_mean_explain_minutes": minutes,
            "group_overhead_minutes": 0.0,
            "expected_ta_minutes": minutes,
        },
    }


def rank_recommendations(conn, course_id: int, clusters: list) -> list:
    """Ranks all active clusters by SUPM descending. Ties are broken by
    (a) higher avg confidence, then (b) larger size, then (c) longer max
    wait -- all three tie-break keys are returned alongside the score so
    the UI can show *why* the ranking landed the way it did, not just the
    final order."""
    scored = []
    for c in clusters:
        s = score_cluster(conn, c)
        s["cluster"] = c
        scored.append(s)

    scored.sort(
        key=lambda s: (
            -s["supm"],
            -s["inputs"]["avg_clustering_confidence"],
            -s["inputs"]["cluster_size"],
            -s["cluster"].get("oldest_wait_seconds", 0),
        )
    )
    return scored


def _get_node(conn, node_id: int) -> dict:
    with dbm.cursor(conn) as cur:
        row = cur.execute("SELECT * FROM taxonomy_nodes WHERE id = ?", (node_id,)).fetchone()
    return dict(row)
