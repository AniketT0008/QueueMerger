"""Synthetic queue generator for the evaluation harness.

Generates a timestamped stream of (student, question_text, code, error,
true_root_cause) tuples for a chosen taxonomy preset, with:
  - realistic phrasing variety per root cause (so lexical clustering would
    fail to unify differently-worded questions on the same cause)
  - a couple of confusable near-duplicate phrasings across DIFFERENT root
    causes (so lexical clustering would wrongly merge them)
  - a scripted outbreak: one node's arrival rate spikes sharply partway
    through the session, so outbreak.py has something real to detect and
    evaluate.py can measure detection lead time against the true spike start.

Ground truth (true taxonomy node name) is attached to every record so
evaluate.py can score extraction/clustering precision & recall without
touching the pipeline's own labels.
"""
import random

from queuemerge.taxonomy import TAXONOMY_PRESETS, normalize_preset

# question templates per node name (matches taxonomy.TAXONOMY_PRESETS["cs101"])
CS101_TEMPLATES = {
    "loop-boundary-inclusive": [
        ("why is my loop off by one, it prints an extra blank line at the end",
         "for i in range(len(arr) + 1):\n    print(arr[i])", None),
        ("my array printer runs one time too many and errors at the end",
         "i = 0\nwhile i <= len(data):\n    print(data[i]); i += 1", "IndexError: list index out of range"),
        ("i think my loop condition is wrong, it goes one step further than it should",
         "for i in range(0, n+1):\n    total += nums[i]", "IndexError: list index out of range"),
    ],
    "loop-boundary-exclusive-missing-last": [
        ("my function never processes the last element of the list, why",
         "for i in range(len(arr)-1):\n    process(arr[i])", None),
        ("the sum is always missing the final number in the array",
         "for i in range(len(nums)-1):\n    total += nums[i]", None),
        ("my search skips the last item every time, is that a loop bug",
         "for i in range(len(items)-1):\n    if items[i] == target: return i", None),
    ],
    "index-out-of-range": [
        ("i keep getting index out of range and i don't know where its from",
         "x = data[len(data)]", "IndexError: list index out of range"),
        ("getting an indexerror on a totally different line than i expect",
         "y = arr[n]", "IndexError: list index out of range"),
    ],
    "mutable-default-arg": [
        ("my accumulator list keeps growing across calls even with new arguments",
         "def add(x, acc=[]):\n    acc.append(x)\n    return acc", None),
        ("why does this function remember values from the last time i called it",
         "def collect(y, bucket=[]):\n    bucket.append(y)\n    return bucket", None),
    ],
    "reference-vs-copy": [
        ("i made a copy of my list but changing one changes both, why",
         "a = [1,2,3]\nb = a\nb.append(4)\nprint(a)", None),
        ("i assigned b = a expecting a separate list but they're linked somehow",
         "original = [1,2]\ncopy = original\ncopy.append(3)", None),
    ],
    "recursion-missing-base-case": [
        ("my recursive function crashes with a recursion error, no idea why",
         "def fact(n):\n    return n * fact(n-1)", "RecursionError: maximum recursion depth exceeded"),
        ("getting a stack overflow looking thing on my recursive function",
         "def countdown(n):\n    print(n)\n    countdown(n-1)", "RecursionError: maximum recursion depth exceeded"),
    ],
    "integer-division-truncation": [
        ("my average calculation is always giving me 0, why is that",
         "avg = total_score // num_students", None),
        ("division isn't giving decimals like i expect, just rounds down",
         "ratio = wins // games", None),
    ],
    "scope-variable-shadowing": [
        ("a variable i set outside my loop keeps getting overwritten unexpectedly",
         "total = 0\nfor total in values:\n    pass\nprint(total)", None),
        ("i'm getting unboundlocalerror and i defined the variable already",
         "def f():\n    x += 1\n    return x", "UnboundLocalError: local variable 'x' referenced before assignment"),
    ],
}

# Confusable pairs echo taxonomy: duplicate-charge vs unexplained-fee share
# "charge"/"statement"/"amount"; stuck-transfer vs stale-account-sync share
# "pending"/"balance"/"not showing".
FINTECH_TEMPLATES = {
    "duplicate-charge": [
        ("I was charged twice for the same checkout — two identical charges on my statement",
         None, None),
        ("merchant billed me twice, same transaction twice for one order",
         None, None),
        ("I see a duplicate charge posted twice for the coffee shop purchase",
         None, None),
    ],
    "unexplained-fee": [
        ("there's a mystery fee on my statement I never authorized — what is this fee?",
         None, None),
        ("strange service charge appeared, not a duplicate of any prior purchase",
         None, None),
        ("unexplained fee / inactivity fee I don't recognize on this statement",
         None, None),
    ],
    "stuck-transfer": [
        ("I sent an ACH but the transfer is still pending and the destination never credited",
         None, None),
        ("wire not received — funds left my account but money still pending at destination",
         None, None),
        ("stuck transfer taking forever, sent money but not there yet",
         None, None),
    ],
    "stale-account-sync": [
        ("my app shows a stale balance and transactions are not showing after refresh",
         None, None),
        ("account not syncing — balance not updating even though nothing is pending",
         None, None),
        ("feed not updating, old transactions still showing, cached balance looks wrong",
         None, None),
    ],
    "false-fraud-decline": [
        ("my card declined for fraud on a purchase I definitely authorized",
         None, None),
        ("false fraud decline blocked a legitimate purchase as suspicious",
         None, None),
        ("fraud system declined my card even though I authorized the charge",
         None, None),
    ],
    "mfa-lockout": [
        ("I'm locked out of MFA after too many codes — authenticator locked",
         None, None),
        ("can't get past verification, OTP failed too many times, 2FA locked",
         None, None),
        ("mfa lockout — need to reset my authenticator after step-up locked",
         None, None),
    ],
    "unauthorized-ach-pull": [
        ("unauthorized ACH pulled money — debit I don't recognize",
         None, None),
        ("mystery withdrawal / ACH pull I didn't authorize from my checking",
         None, None),
    ],
    "card-network-timeout": [
        ("payment hung then failed — authorization timeout, pending hold reversed",
         None, None),
        ("gateway timeout on card, auth expired after acquirer timeout",
         None, None),
    ],
}

TEMPLATES_BY_PRESET = {
    "cs101": CS101_TEMPLATES,
    "fintech": FINTECH_TEMPLATES,
}

# Backward-compatible alias used by evaluate.py / older callers.
TEMPLATES = CS101_TEMPLATES

STUDENT_FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Mia", "Ethan", "Zoe", "Leo", "Ivy", "Kai",
    "Nora", "Owen", "Ruby", "Sam", "Tara", "Uma", "Victor", "Wren", "Xin", "Yara",
]

DEFAULT_OUTBREAK_NODE = {
    "cs101": "reference-vs-copy",
    "fintech": "false-fraud-decline",
}


def templates_for(preset: str = "cs101") -> dict:
    preset = normalize_preset(preset)
    templates = TEMPLATES_BY_PRESET[preset]
    # Sanity: every seeded taxonomy node should have at least one template.
    seeded = {n["name"] for n in TAXONOMY_PRESETS[preset]}
    missing = seeded - set(templates)
    if missing:
        raise RuntimeError(f"synthetic templates missing nodes for {preset}: {sorted(missing)}")
    return templates


def generate_session(seed: int = 7, n_students: int = 40, session_minutes: float = 60.0,
                      outbreak_node: str = None,
                      outbreak_start_min: float = 25.0,
                      arrival_rate_per_min: float = 0.9,
                      preset: str = "cs101") -> list:
    """Returns a list of dicts, sorted by created_offset_min ascending:
    {student, text, code, error, true_node, created_offset_min}
    Baseline arrival process is roughly Poisson with ~0.5/min; from
    outbreak_start_min onward, arrivals for outbreak_node get a strong
    rate boost to simulate a real misconception spike (e.g. a slide typo)."""
    preset = normalize_preset(preset)
    templates = templates_for(preset)
    if outbreak_node is None:
        outbreak_node = DEFAULT_OUTBREAK_NODE[preset]

    rng = random.Random(seed)
    node_names = list(templates.keys())
    records = []
    t = 0.0
    used_names = set()

    def draw_name():
        for _ in range(50):
            n = rng.choice(STUDENT_FIRST_NAMES) + str(rng.randint(1, 999))
            if n not in used_names:
                used_names.add(n)
                return n
        return f"student{len(used_names)}"

    idx = 0
    while t < session_minutes and idx < n_students:
        gap = rng.expovariate(arrival_rate_per_min)
        t += gap
        if t >= session_minutes:
            break

        if outbreak_node != "__none__" and t >= outbreak_start_min and rng.random() < 0.55:
            node = outbreak_node
        else:
            node = rng.choice(node_names)

        text, code, err = rng.choice(templates[node])
        records.append({
            "student": draw_name(),
            "text": text,
            "code": code,
            "error": err,
            "true_node": node,
            "created_offset_min": round(t, 3),
            "preset": preset,
        })
        idx += 1

    return records
