"""Course-scoped misconception taxonomy.

A taxonomy node is a named root cause with a description and a set of
keyword/phrase cues used by the heuristic extractor. Real deployments would
seed this from past semesters; QueueMerge can also bootstrap nodes live from
unmatched questions in an empty/new course (see extraction.bootstrap_node).

Two named presets share the same pipeline (clustering / SUPM / simulation /
outbreak / Explanation Memory). Switching presets means a fresh course so
nodes never mix in one session.
"""
import json
from typing import Optional
from queuemerge import db as dbm

# ---------------------------------------------------------------------------
# CS101 office-hours seed (kept byte-for-byte as the original DEFAULT_TAXONOMY)
# Deliberately includes confusable pairs (nodes 1 vs 2, both "loop boundary"
# but opposite direction) so clustering has to split similarly-worded
# questions apart, and 1/3 co-occur in the wild so it has to avoid conflating
# a symptom (IndexError) with its distinct root causes.
# ---------------------------------------------------------------------------
_CS101_TAXONOMY = [
    {
        "name": "loop-boundary-inclusive",
        "description": "Loop condition uses <= (or range(len(arr)+1)/range(len(arr), -1)) so it "
                        "runs one iteration too many, walking off the end of the collection.",
        "keywords": ["<=", "off by one", "off-by-one", "one extra", "one too many",
                     "range(len(arr)+1", "range(len(a)+1", "inclusive", "extra blank line",
                     "extra iteration", "prints an extra"],
    },
    {
        "name": "loop-boundary-exclusive-missing-last",
        "description": "Loop condition stops one iteration short (e.g. range(len(arr)-1)) so the "
                        "last element is never processed.",
        "keywords": ["misses the last", "skips the last", "missing last", "range(len(arr)-1",
                     "range(len(a)-1", "stops one early", "never processes the last",
                     "doesn't include the last"],
    },
    {
        "name": "index-out-of-range",
        "description": "Code indexes one position past the end of a list/array, raising IndexError.",
        "keywords": ["index out of range", "indexerror", "list index", "out of bounds",
                     "index error"],
    },
    {
        "name": "mutable-default-arg",
        "description": "A mutable default argument (e.g. def f(x, acc=[])) is created once and "
                        "reused across every call, so state silently leaks between calls.",
        "keywords": ["default argument", "acc=[]", "mutable default", "keeps growing",
                     "shared between calls", "def f(x, acc=[]", "list keeps accumulating"],
    },
    {
        "name": "reference-vs-copy",
        "description": "Student assumes `b = a` copies a list, but it aliases the same object, so "
                        "mutating one mutates both.",
        "keywords": ["reference", "alias", "shared list", "b = a", "changes both", "same object",
                     "copy of the list", "not an actual copy"],
    },
    {
        "name": "recursion-missing-base-case",
        "description": "Recursive function has no base case (or an unreachable one), so it "
                        "recurses until the stack overflows.",
        "keywords": ["recursionerror", "maximum recursion", "base case", "infinite recursion",
                     "stack overflow", "never stops recursing"],
    },
    {
        "name": "integer-division-truncation",
        "description": "Student expects float division but `//` (or Py2-style `/`) truncates, "
                        "silently producing 0 or a rounded-down value.",
        "keywords": ["integer division", "truncat", "floor division", "//", "rounds down",
                     "always getting 0", "unexpected 0"],
    },
    {
        "name": "scope-variable-shadowing",
        "description": "A variable declared inside a loop/function shadows an outer variable of "
                        "the same name, so the outer value is unexpectedly overwritten or reused.",
        "keywords": ["shadowing", "same variable name", "overwritten", "unboundlocalerror",
                     "global vs local", "wrong value after the loop"],
    },
]

# ---------------------------------------------------------------------------
# Fintech support triage seed.
# Confusable pairs (deliberate):
#   - duplicate-charge vs unexplained-fee: both talk about "charge" /
#     "transaction" / "amount" / "statement", but one is a second posting of
#     a known purchase and the other is a novel fee line with no prior twin.
#   - stuck-transfer vs stale-account-sync: both talk about "pending" /
#     "balance" / "not showing" / "still waiting", but one is money in flight
#     between accounts and the other is a feed that stopped refreshing.
# ---------------------------------------------------------------------------
_FINTECH_TAXONOMY = [
    {
        "name": "duplicate-charge",
        "description": "A known merchant purchase posted twice (or was captured and then "
                        "re-settled), so the statement shows two identical charge lines for "
                        "one checkout.",
        "keywords": ["charged twice", "duplicate charge", "double charged", "same transaction twice",
                     "posted twice", "two identical charges", "duplicate transaction",
                     "billed twice", "same amount twice", "merchant charged me twice"],
    },
    {
        "name": "unexplained-fee",
        "description": "A novel fee or service charge appears on the statement with no matching "
                        "prior purchase twin — maintenance, inactivity, foreign-transaction, or "
                        "overdraft fee the customer does not recognize as a duplicate of anything.",
        "keywords": ["mystery fee", "unexplained fee", "unknown fee", "service charge",
                     "maintenance fee", "inactivity fee", "foreign transaction fee",
                     "overdraft fee", "fee i never authorized", "strange fee on my statement",
                     "what is this fee"],
    },
    {
        "name": "stuck-transfer",
        "description": "A customer-initiated transfer (ACH, wire, or internal move) left the "
                        "source account but never credited the destination — money is in flight "
                        "or held pending bank processing.",
        "keywords": ["transfer pending", "stuck transfer", "transfer not arrived",
                     "money still pending", "wire not received", "ach not posted",
                     "sent money but not there", "transfer taking forever",
                     "funds left my account", "destination never credited"],
    },
    {
        "name": "stale-account-sync",
        "description": "Balances or recent transactions are stale because the account aggregation "
                        "feed / device cache stopped refreshing — nothing is actually in flight; "
                        "the UI is showing an old snapshot.",
        "keywords": ["balance not updating", "stale balance", "transactions not showing",
                     "account not syncing", "refresh not working", "old transactions still showing",
                     "feed not updating", "app shows wrong balance", "cached balance",
                     "sync stuck", "haven't seen new transactions"],
    },
    {
        "name": "false-fraud-decline",
        "description": "A legitimate card purchase was declined by the fraud engine (velocity, "
                        "geo, or MCC rules) even though the cardholder authorized it.",
        "keywords": ["declined for fraud", "false fraud decline", "fraud alert declined",
                     "card declined but i authorized", "blocked as suspicious",
                     "fraud system declined", "velocity decline", "geo mismatch decline",
                     "mcc block", "legitimate purchase declined"],
    },
    {
        "name": "mfa-lockout",
        "description": "Too many failed one-time codes / authenticator attempts locked the "
                        "login or step-up challenge; the customer cannot complete MFA.",
        "keywords": ["locked out of mfa", "mfa lockout", "too many codes", "authenticator locked",
                     "2fa locked", "otp failed too many", "can't get past verification",
                     "verification code locked", "step-up locked", "reset my authenticator"],
    },
    {
        "name": "unauthorized-ach-pull",
        "description": "An ACH debit the customer does not recognize pulled funds from their "
                        "account (possible compromised routing/account numbers or revoked "
                        "authorization that still cleared).",
        "keywords": ["unauthorized ach", "unknown debit", "ach pull i didn't authorize",
                     "mystery withdrawal", "debit i don't recognize", "ach fraud",
                     "someone pulled money", "unauthorized withdrawal", "revoke ach"],
    },
    {
        "name": "card-network-timeout",
        "description": "Authorization timed out at the card network / acquirer — customer saw "
                        "a hang or pending hold that later reversed, not a fraud rule decision.",
        "keywords": ["authorization timeout", "network timeout", "pending hold reversed",
                     "acquirer timeout", "iso 8583 timeout", "payment hung then failed",
                     "gateway timeout on card", "auth expired", "hold then dropped"],
    },
]

TAXONOMY_PRESETS = {
    "cs101": _CS101_TAXONOMY,
    "fintech": _FINTECH_TAXONOMY,
}

PRESET_LABELS = {
    "cs101": "CS101 Office Hours",
    "fintech": "Fintech Support Triage",
}

PRESET_COURSE_NAMES = {
    "cs101": "CS101 Demo",
    "fintech": "Fintech Support",
}

# Backward-compatible alias: existing imports of DEFAULT_TAXONOMY keep CS101.
DEFAULT_TAXONOMY = TAXONOMY_PRESETS["cs101"]


def normalize_preset(preset: Optional[str]) -> str:
    name = (preset or "cs101").strip().lower()
    if name not in TAXONOMY_PRESETS:
        known = ", ".join(sorted(TAXONOMY_PRESETS))
        raise ValueError(f"Unknown taxonomy preset {preset!r}; expected one of: {known}")
    return name


def seed_taxonomy(conn, course_id: int, preset: str = "cs101") -> None:
    """Seed approved taxonomy nodes for a course from a named preset."""
    preset = normalize_preset(preset)
    nodes = TAXONOMY_PRESETS[preset]
    ts = dbm.now()
    with dbm.cursor(conn) as cur:
        for node in nodes:
            cur.execute(
                "INSERT INTO taxonomy_nodes (course_id, name, description, keywords, "
                "is_bootstrapped, approved, created_at) VALUES (?, ?, ?, ?, 0, 1, ?)",
                (course_id, node["name"], node["description"], json.dumps(node["keywords"]), ts),
            )


def seed_default_taxonomy(conn, course_id: int) -> None:
    """Backward-compatible wrapper: seeds the CS101 preset."""
    seed_taxonomy(conn, course_id, preset="cs101")


def get_or_create_course(conn, name: str) -> int:
    with dbm.cursor(conn) as cur:
        row = cur.execute("SELECT id FROM courses WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur.execute("INSERT INTO courses (name, created_at) VALUES (?, ?)", (name, dbm.now()))
        course_id = cur.lastrowid
    return course_id


def list_nodes(conn, course_id: int):
    with dbm.cursor(conn) as cur:
        rows = cur.execute(
            "SELECT * FROM taxonomy_nodes WHERE course_id = ?", (course_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def has_taxonomy(conn, course_id: int) -> bool:
    with dbm.cursor(conn) as cur:
        row = cur.execute(
            "SELECT COUNT(*) AS n FROM taxonomy_nodes WHERE course_id = ?", (course_id,)
        ).fetchone()
    return row["n"] > 0


def create_bootstrapped_node(conn, course_id: int, name: str, description: str,
                              keywords: list) -> int:
    """Create a new taxonomy node live from an unmatched question. Marked
    is_bootstrapped=1, approved=0 so the TA-facing UI can surface it for
    a rename/approve/reject pass ("degrade gracefully" requirement)."""
    with dbm.cursor(conn) as cur:
        cur.execute(
            "INSERT INTO taxonomy_nodes (course_id, name, description, keywords, "
            "is_bootstrapped, approved, created_at) VALUES (?, ?, ?, ?, 1, 0, ?)",
            (course_id, name, description, json.dumps(keywords), dbm.now()),
        )
        return cur.lastrowid


def approve_node(conn, node_id: int, new_name: Optional[str] = None) -> None:
    with dbm.cursor(conn) as cur:
        if new_name:
            cur.execute("UPDATE taxonomy_nodes SET approved = 1, name = ? WHERE id = ?",
                        (new_name, node_id))
        else:
            cur.execute("UPDATE taxonomy_nodes SET approved = 1 WHERE id = ?", (node_id,))


def get_node(conn, node_id: int) -> Optional[dict]:
    with dbm.cursor(conn) as cur:
        row = cur.execute("SELECT * FROM taxonomy_nodes WHERE id = ?", (node_id,)).fetchone()
    return dict(row) if row else None
