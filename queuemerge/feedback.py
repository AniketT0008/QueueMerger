"""Feedback loop: TA marks a cluster resolved / partially_resolved /
misclustered. That label updates the taxonomy node's running estimates so
later SUPM scores and simulations get more accurate over the course of a
session (and across sessions, since the DB persists).

- resolved (minutes_spent given): EWMA-update mean_explain_minutes for the
  node, and nudge confidence_weight up slightly (the keyword cues that fired
  were validated).
- partially_resolved: smaller nudge; the node's cue set worked but the
  explanation time estimate was probably too optimistic, so weight the
  minutes update but don't move confidence up.
- misclustered: nudge confidence_weight down for the node (its cue matches
  are producing false positives), which lowers its heuristic-extractor score
  going forward and lowers future SUPM confidence discount.
"""
from queuemerge import db as dbm

EWMA_ALPHA = 0.35
CONFIDENCE_STEP = 0.05
CONFIDENCE_MIN, CONFIDENCE_MAX = 0.3, 2.0


def record_feedback(conn, cluster_id: int, ta_label: str, minutes_spent: float = None) -> None:
    with dbm.cursor(conn) as cur:
        cur.execute(
            "INSERT INTO feedback_events (cluster_id, ta_label, minutes_spent, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (cluster_id, ta_label, minutes_spent, dbm.now()),
        )
        cluster = cur.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if cluster is None:
            return
        node = cur.execute(
            "SELECT * FROM taxonomy_nodes WHERE id = ?", (cluster["taxonomy_node_id"],)
        ).fetchone()
        if node is None:
            return

        new_mean = node["mean_explain_minutes"]
        new_n = node["explain_minutes_n"]
        new_weight = node["confidence_weight"]

        if ta_label == "resolved" and minutes_spent:
            new_mean = (node["mean_explain_minutes"] * (1 - EWMA_ALPHA)) + (minutes_spent * EWMA_ALPHA) \
                if node["explain_minutes_n"] > 0 else minutes_spent
            new_n = node["explain_minutes_n"] + 1
            new_weight = min(CONFIDENCE_MAX, node["confidence_weight"] + CONFIDENCE_STEP)
        elif ta_label == "partially_resolved" and minutes_spent:
            observed = minutes_spent * 1.3  # partial resolution implies underestimate
            new_mean = (node["mean_explain_minutes"] * (1 - EWMA_ALPHA / 2)) + (observed * (EWMA_ALPHA / 2))
            new_n = node["explain_minutes_n"] + 1
        elif ta_label == "misclustered":
            new_weight = max(CONFIDENCE_MIN, node["confidence_weight"] - CONFIDENCE_STEP * 2)

        cur.execute(
            "UPDATE taxonomy_nodes SET mean_explain_minutes = ?, explain_minutes_n = ?, "
            "confidence_weight = ? WHERE id = ?",
            (round(new_mean, 2), new_n, round(new_weight, 3), node["id"]),
        )
        new_status = "resolved" if ta_label == "resolved" else (
            "merged" if ta_label == "misclustered" else "active"
        )
        cur.execute("UPDATE clusters SET status = ? WHERE id = ?", (new_status, cluster_id))

        if ta_label == "resolved":
            members = cur.execute(
                "SELECT question_id FROM cluster_members WHERE cluster_id = ? AND left_at IS NULL",
                (cluster_id,),
            ).fetchall()
            ts = dbm.now()
            for m in members:
                cur.execute(
                    "UPDATE questions SET status = 'resolved', resolved_at = ? WHERE id = ?",
                    (ts, m["question_id"]),
                )
                cur.execute(
                    "INSERT INTO outcomes (question_id, label, timestamp) VALUES (?, 'resolved', ?)",
                    (m["question_id"], ts),
                )
