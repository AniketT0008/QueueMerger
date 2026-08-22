"""Pipeline stage 3: clustering / re-clustering.

Groups *waiting* questions primarily by taxonomy_node_id (the causal tag),
never by raw text similarity. Within a node, if there's enough support for
more than one distinct evidence sub_step, the group is split into
sub-clusters so "same node, different specific cause" doesn't get lumped
into one giant unexplained bucket. Each resulting cluster gets a
human-readable explanation string.

This is re-run any time the queue changes materially (new intake,
resolution, or manual TA refresh) -- it's cheap since it only touches
'waiting' questions and rebuilds active clusters from scratch each call,
which keeps it simple and avoids stale-membership bugs.
"""
import json
from collections import defaultdict
from queuemerge import db as dbm
from queuemerge import taxonomy as tax

SUB_SPLIT_MIN_SUPPORT = 2  # need >=2 questions sharing a sub_step to justify a split
SUB_SPLIT_MIN_FRACTION = 0.34  # and that sub_step must be >=34% of the node's waiting queue


def _dominant_sub_steps(questions: list) -> dict:
    """Returns {sub_step: [question,...]} for sub_steps that clear the
    support threshold; everything else stays in a shared 'general' bucket."""
    by_sub = defaultdict(list)
    for q in questions:
        ev = json.loads(q["evidence_json"]) if q["evidence_json"] else {}
        sub = ev.get("sub_step") or "general pattern match"
        by_sub[sub].append(q)

    n = len(questions)
    kept = {}
    overflow = []
    for sub, qs in by_sub.items():
        if len(qs) >= SUB_SPLIT_MIN_SUPPORT and (len(qs) / n) >= SUB_SPLIT_MIN_FRACTION:
            kept[sub] = qs
        else:
            overflow.extend(qs)
    if overflow:
        kept.setdefault("general", []).extend(overflow)
    return kept if len(kept) > 1 else {"general": questions}


def rebuild_clusters(conn, course_id: int) -> list:
    """Rebuilds active clusters for all *waiting* questions in a course.
    Returns the list of resulting cluster dicts (with members + explanation)."""
    ts = dbm.now()
    with dbm.cursor(conn) as cur:
        waiting = cur.execute(
            "SELECT * FROM questions WHERE course_id = ? AND status = 'waiting' "
            "AND taxonomy_node_id IS NOT NULL",
            (course_id,),
        ).fetchall()
        # retire previous active clusters; membership rows stay as history
        cur.execute(
            "UPDATE clusters SET status = 'superseded', updated_at = ? "
            "WHERE course_id = ? AND status = 'active'",
            (ts, course_id),
        )

    waiting = [dict(q) for q in waiting]
    by_node = defaultdict(list)
    for q in waiting:
        by_node[q["taxonomy_node_id"]].append(q)

    node_cache = {n["id"]: n for n in tax.list_nodes(conn, course_id)}
    results = []

    for node_id, qs in by_node.items():
        node = node_cache.get(node_id)
        if node is None:
            continue
        sub_groups = _dominant_sub_steps(qs)
        for sub_key, members in sub_groups.items():
            explanation = _explain(node, members, sub_key, len(sub_groups) > 1)
            with dbm.cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO clusters (course_id, taxonomy_node_id, sub_key, explanation, "
                    "status, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                    (course_id, node_id, sub_key, explanation, ts, ts),
                )
                cluster_id = cur.lastrowid
                for m in members:
                    cur.execute(
                        "INSERT INTO cluster_members (cluster_id, question_id, joined_at) "
                        "VALUES (?, ?, ?)",
                        (cluster_id, m["id"], ts),
                    )
                    cur.execute("UPDATE questions SET cluster_id = ? WHERE id = ?",
                                (cluster_id, m["id"]))
            avg_conf = sum(m["extraction_confidence"] or 0 for m in members) / len(members)
            results.append({
                "cluster_id": cluster_id,
                "taxonomy_node_id": node_id,
                "node_name": node["name"],
                "sub_key": sub_key,
                "explanation": explanation,
                "member_question_ids": [m["id"] for m in members],
                "size": len(members),
                "avg_confidence": round(avg_conf, 3),
                "oldest_wait_seconds": ts - min(m["created_at"] for m in members),
            })

    return results


def _explain(node: dict, members: list, sub_key: str, is_split: bool) -> str:
    n = len(members)
    if n == 1:
        base = f"1 student shows evidence of: {node['description']}"
    else:
        base = f"{n} students all show evidence of: {node['description']}"
    if is_split and sub_key not in ("general", "general pattern match"):
        base += f" Specifically, the shared cue in this subgroup is \u201c{sub_key}\u201d."
    all_cues = set()
    for m in members:
        ev = json.loads(m["evidence_json"]) if m["evidence_json"] else {}
        all_cues.update(ev.get("matched_cues", []))
    if all_cues:
        shown = ", ".join(sorted(all_cues)[:5])
        base += f" Common evidence: {shown}."
    return base


def get_active_clusters(conn, course_id: int) -> list:
    """Returns clusters in the SAME shape rebuild_clusters() returns
    (cluster_id, taxonomy_node_id, size, avg_confidence, oldest_wait_seconds,
    member_question_ids, explanation), so downstream code (supm.py,
    simulation.py, the UI) can treat either source interchangeably."""
    ts = dbm.now()
    with dbm.cursor(conn) as cur:
        clusters = cur.execute(
            "SELECT * FROM clusters WHERE course_id = ? AND status = 'active'", (course_id,)
        ).fetchall()
    out = []
    for c in clusters:
        c = dict(c)
        with dbm.cursor(conn) as cur:
            members = cur.execute(
                "SELECT q.* FROM cluster_members cm JOIN questions q ON q.id = cm.question_id "
                "WHERE cm.cluster_id = ? AND cm.left_at IS NULL", (c["id"],)
            ).fetchall()
        members = [dict(m) for m in members]
        if not members:
            continue
        avg_conf = sum(m["extraction_confidence"] or 0.5 for m in members) / len(members)
        out.append({
            "cluster_id": c["id"],
            "id": c["id"],
            "course_id": c["course_id"],
            "taxonomy_node_id": c["taxonomy_node_id"],
            "sub_key": c["sub_key"],
            "explanation": c["explanation"],
            "status": c["status"],
            "members": members,
            "member_question_ids": [m["id"] for m in members],
            "size": len(members),
            "avg_confidence": round(avg_conf, 3),
            "oldest_wait_seconds": ts - min(m["created_at"] for m in members),
        })
    return out
