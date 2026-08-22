"""Pluggable misconception-extraction backends.

QueueMerge needs, per question: a candidate taxonomy node, a confidence
score, and a short evidence trail (why that node). Two implementations:

- HeuristicExtractor: deterministic keyword/pattern matcher. No API key,
  no network, no rate limits. This is the default fallback and what the
  eval harness uses for reproducible numbers.
- GeminiExtractor: calls Gemini (google-generativeai) with a structured
  JSON-schema prompt grounded in the course's taxonomy. This is the
  "main" path per user preference. If GEMINI_API_KEY isn't set, or the
  call fails/times out/returns malformed JSON, callers should fall back
  to HeuristicExtractor -- see extraction.extract_misconception, which
  implements that fallback chain. Nothing else in the pipeline should
  call these classes directly.

Both return the same shape:
    {
        "node_id": int | None,        # None => no taxonomy match, candidate for bootstrap
        "node_name": str | None,      # used when node_id is None but a name is proposed
        "confidence": float,          # 0..1
        "evidence": {
            "matched_cues": [str, ...],
            "sub_step": str,          # short free-text guess at the specific sub-cause
            "source": "heuristic" | "gemini",
        },
        "proposed_new_node": {"name": str, "description": str, "keywords": [str,...]} | None,
    }
"""
import json
import os
import re
from typing import Optional

# Load GEMINI_API_KEY (and anything else) from a .env file in the project
# root if python-dotenv is installed and a .env exists. This is optional --
# the pipeline works with zero config either way (falls back to the
# heuristic extractor) -- it just saves having to `export` the key by hand
# every terminal session. Never put a real key in source control; use
# .env (gitignored) or a real environment variable instead.
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Heuristic extractor (fallback / offline / eval-harness default)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "is", "it", "to", "of", "in", "on", "for", "my", "and",
    "why", "does", "do", "i", "im", "i'm", "this", "that", "with", "but",
    "when", "so", "get", "gets", "getting", "not", "be", "am", "are", "was",
}


def _tokenize(text: str):
    return re.findall(r"[a-zA-Z0-9_<>=/\.\+\-\[\]]+", text.lower())


class HeuristicExtractor:
    """Weighted keyword/phrase overlap against each taxonomy node's cue
    list. Error messages and code snippets are weighted higher than
    conversational phrasing, since exact tokens like 'IndexError' or
    'range(len(arr)-1' are much stronger evidence than word choice.
    """

    MATCH_THRESHOLD = 0.18  # below this, treat as unmatched -> bootstrap candidate
    BOOTSTRAP_PENDING_WEIGHT_DISCOUNT = 0.35  # see bugfix note in extract() below

    def extract(self, question_text: str, code_snippet: Optional[str],
                error_message: Optional[str], taxonomy_nodes: list) -> dict:
        text_blob = (question_text or "").lower()
        code_blob = (code_snippet or "").lower()
        err_blob = (error_message or "").lower()

        scores = {}
        matches = {}
        for node in taxonomy_nodes:
            keywords = json.loads(node["keywords"]) if isinstance(node["keywords"], str) else node["keywords"]
            weight = float(node.get("confidence_weight", 1.0)) if isinstance(node, dict) else 1.0
            # BUGFIX: bootstrapped nodes not yet TA-approved get their auto-
            # generated keyword list straight from one question's own words
            # (see _propose_node below) -- short, generic lists like
            # ["list", "always", "seems"] have a much smaller normalization
            # denominator than a curated node's longer, specific list, so a
            # couple of coincidental common-word hits could previously beat
            # a real match against a properly curated node (e.g. a genuine
            # "recursion missing base case" question, which legitimately
            # matches on "base case", losing out to an unrelated pending
            # bootstrap node that happened to also contain "always" and
            # "seems"). Discount pending nodes so they can't outrank
            # approved/curated ones; once a TA approves a bootstrap node it
            # competes at full strength like any other node.
            if isinstance(node, dict) and node.get("is_bootstrapped") and not node.get("approved"):
                weight *= self.BOOTSTRAP_PENDING_WEIGHT_DISCOUNT
            score = 0.0
            hit_cues = []
            for kw in keywords:
                kwl = kw.lower()
                w = 1.0
                if kwl in err_blob:
                    w = 3.0
                elif kwl in code_blob:
                    w = 2.2
                elif kwl in text_blob:
                    w = 1.0
                else:
                    continue
                score += w
                hit_cues.append(kw)
            # Normalize by cue-list length so long lists don't dominate —
            # BUT cap the denominator. Without a cap, a curated fintech node
            # with ~10 carefully-written multi-word cues needs multiple hits
            # just to clear MATCH_THRESHOLD on a single strong phrase match
            # (e.g. "declined for fraud"), so the question falls through to
            # bootstrap and a short pending node's generic words can win later
            # rounds. Cap keeps CS101's short/medium lists behaving as before
            # while letting one solid multi-word hit clear the bar on denser
            # taxonomies. Extra cues beyond the cap still help *matching*
            # more phrasings; they just stop inflating the penalty.
            effective_len = min(len(keywords), 6)
            norm = score / max(3.0, effective_len * 0.6)
            scores[node["id"]] = norm * weight
            matches[node["id"]] = hit_cues

        if not scores or max(scores.values()) < self.MATCH_THRESHOLD:
            # no confident taxonomy match -> propose bootstrapping a node
            candidate_name, candidate_kw = self._propose_node(question_text, code_snippet, error_message)
            return {
                "node_id": None,
                "node_name": candidate_name,
                "confidence": 0.15,
                "evidence": {
                    "matched_cues": [],
                    "sub_step": "unclassified - no taxonomy node cleared match threshold",
                    "source": "heuristic",
                },
                "proposed_new_node": {
                    "name": candidate_name,
                    "description": f"Auto-bootstrapped from: \"{(question_text or '')[:120]}\"",
                    "keywords": candidate_kw,
                },
            }

        best_id = max(scores, key=scores.get)
        raw = scores[best_id]
        confidence = max(0.05, min(0.97, raw / (raw + 1.0) * 2.0))  # squashed 0..~0.97
        sub_step = matches[best_id][0] if matches[best_id] else "general pattern match"
        return {
            "node_id": best_id,
            "node_name": None,
            "confidence": round(confidence, 3),
            "evidence": {
                "matched_cues": matches[best_id],
                "sub_step": sub_step,
                "source": "heuristic",
            },
            "proposed_new_node": None,
        }

    @staticmethod
    def _propose_node(question_text, code_snippet, error_message) -> tuple:
        tokens = [t for t in _tokenize(question_text or "") if t not in _STOPWORDS and len(t) > 2]
        top = tokens[:3] if tokens else ["unclassified"]
        name = "candidate-" + "-".join(top)
        keywords = list(dict.fromkeys(tokens[:6]))
        if error_message:
            keywords.append(error_message.split(":")[0].strip().lower())
        return name, keywords


# ---------------------------------------------------------------------------
# Gemini extractor (primary path, requires GEMINI_API_KEY)
# ---------------------------------------------------------------------------

GEMINI_SYSTEM_PROMPT = """You are a structured extraction engine for an office-hour queue system.
Given a student's question (plus optional code and error message) and a course's misconception
taxonomy, identify which taxonomy node is the ROOT CAUSE (not the surface symptom) of the
student's confusion. If nothing fits well, say so instead of forcing a match.

Respond with ONLY a JSON object, no markdown fences, no prose, matching this schema:
{
  "node_id": <int or null>,
  "confidence": <float 0..1>,
  "matched_cues": [<short strings from the input that justify the match>],
  "sub_step": "<one short phrase: the specific sub-cause, e.g. 'uses <= instead of <'>",
  "proposed_new_node": null OR {"name": "<kebab-case>", "description": "<one sentence>", "keywords": [<3-6 strings>]}
}
Only set proposed_new_node when node_id is null (no existing node fits)."""


def _load_gemini_keys() -> list:
    """Collects configured Gemini keys, supporting either form:

    - GEMINI_API_KEYS="key1,key2,key3"   (comma-separated, preferred for 2+)
    - GEMINI_API_KEY="key1"              (single-key, still fully supported)

    Both can be set at once -- GEMINI_API_KEYS entries come first, then
    GEMINI_API_KEY is appended if it isn't already in the list, so existing
    single-key setups (local .env, already-configured Cloud secrets) keep
    working unchanged. Blank/whitespace-only entries are dropped. Order is
    preserved and duplicates are removed (first occurrence wins) so
    round-robin rotation doesn't get stuck re-trying the same key twice in
    a row when a key was listed in both places.
    """
    keys = []
    multi = os.environ.get("GEMINI_API_KEYS", "")
    for k in multi.split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    single = os.environ.get("GEMINI_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)
    return keys


# Exceptions from the Gemini SDK/API that indicate "this specific key is
# rate-limited/exhausted/invalid right now" -- worth rotating to the next
# key and retrying. Anything else (malformed response, network blip on a
# request that would fail the same way on any key) is not worth burning
# every key on, so it's raised immediately instead.
_ROTATE_ON_MESSAGE_SUBSTRINGS = (
    "429",            # rate limit / resource exhausted
    "quota",
    "resource_exhausted",
    "rate limit",
    "permission_denied",  # e.g. a key that's been revoked/disabled
    "api_key_invalid",
    "403",
)


def _should_rotate(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in _ROTATE_ON_MESSAGE_SUBSTRINGS)


class GeminiExtractor:
    """Calls Gemini for structured misconception extraction. Requires at
    least one key via GEMINI_API_KEY or GEMINI_API_KEYS in the environment,
    plus network access to generativelanguage.googleapis.com.

    Supports multiple keys for basic load distribution and failover:
    - Each call rotates to the next key round-robin, spreading requests
      (and therefore free-tier quota usage) across all configured keys
      instead of hammering just the first one.
    - If a call fails with a rate-limit/quota/invalid-key-shaped error,
      it retries the SAME request against each remaining key in turn
      before giving up.
    - Only raises (triggering the heuristic fallback in extraction.py)
      once every configured key has been tried and failed, or if the
      failure clearly isn't key-related (e.g. malformed JSON response) --
      no point burning through every key for an error every key would
      hit identically.
    """

    # gemini-2.0-flash was retired; Cloud returns 404 unless this is updated.
    MODEL = "gemini-3.6-flash"
    # Fallbacks if a key's project doesn't have the primary model yet.
    MODEL_FALLBACKS = ("gemini-3.6-flash", "gemini-2.5-flash", "gemini-flash-latest")

    def __init__(self, api_key: Optional[str] = None):
        if api_key:
            self.keys = [api_key]
        else:
            self.keys = _load_gemini_keys()
        if not self.keys:
            raise RuntimeError("GEMINI_API_KEY / GEMINI_API_KEYS not set")
        self._next_index = 0

    def extract(self, question_text: str, code_snippet: Optional[str],
                error_message: Optional[str], taxonomy_nodes: list) -> dict:
        import google.generativeai as genai

        taxonomy_desc = "\n".join(
            f"- id={n['id']} name={n['name']}: {n['description']}" for n in taxonomy_nodes
        )
        user_prompt = (
            f"TAXONOMY:\n{taxonomy_desc}\n\n"
            f"QUESTION: {question_text}\n"
            f"CODE:\n{code_snippet or '(none provided)'}\n"
            f"ERROR:\n{error_message or '(none provided)'}\n"
        )

        n = len(self.keys)
        # Round-robin the starting key across calls (not just on failure) so
        # normal, successful traffic is spread across all configured keys.
        start = self._next_index
        self._next_index = (self._next_index + 1) % n

        last_exc = None
        for attempt in range(n):
            key = self.keys[(start + attempt) % n]
            try:
                genai.configure(api_key=key)
                models_to_try = []
                for m in (self.MODEL,) + tuple(self.MODEL_FALLBACKS):
                    if m not in models_to_try:
                        models_to_try.append(m)
                parsed = None
                model_exc = None
                for model_name in models_to_try:
                    try:
                        model = genai.GenerativeModel(
                            model_name, system_instruction=GEMINI_SYSTEM_PROMPT
                        )
                        resp = model.generate_content(
                            user_prompt,
                            generation_config={
                                "temperature": 0.0,
                                "response_mime_type": "application/json",
                            },
                        )
                        raw = resp.text.strip()
                        raw = re.sub(
                            r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE
                        ).strip()
                        parsed = json.loads(raw)
                        break
                    except Exception as mex:
                        model_exc = mex
                        msg = str(mex).lower()
                        # Retired / missing model → try next model name on same key.
                        if "not found" in msg or "no longer available" in msg or "404" in msg:
                            continue
                        raise
                if parsed is None:
                    raise model_exc
                return {
                    "node_id": parsed.get("node_id"),
                    "node_name": None,
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "evidence": {
                        "matched_cues": parsed.get("matched_cues", []),
                        "sub_step": parsed.get("sub_step", ""),
                        "source": "gemini",
                    },
                    "proposed_new_node": parsed.get("proposed_new_node"),
                }
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < n and _should_rotate(exc):
                    continue  # try the next key
                raise
        # unreachable, but keeps type-checkers happy
        raise last_exc


def get_default_extractor():
    """Returns Gemini if at least one key is configured (GEMINI_API_KEY or
    GEMINI_API_KEYS), else the heuristic extractor. This is a convenience
    for callers that just want 'the best available thing'; extraction.py
    does its own try/except around actual calls so a mid-session Gemini
    failure (rate limit, network, or every configured key exhausted)
    still degrades gracefully per-question rather than only at startup."""
    if _load_gemini_keys():
        try:
            return GeminiExtractor()
        except Exception:
            pass
    return HeuristicExtractor()
