#!/usr/bin/env python3
"""
ai.py — the AI layer.

Design rules, in priority order:

1. **The deterministic rules are the source of truth.** The model never decides
   what happened; it phrases and tailors what the rules already established.
   This is the same principle as verifying webhook signatures against PayPal's
   API rather than our own arithmetic: trust the authority.

2. **The product must work with no API key at all.** A judge cloning this repo
   gets the full deterministic product. AI is progressive enhancement, never a
   dependency. If this module raises, HoldWatch still explains everything.

3. **Never call the model on the critical path.** One call per event, cached by
   event id. Measured: the Gemini key returned 429 on 4 of 6 rapid calls, so
   per-request calls would both fail and waste quota.

4. **Never let the model contradict the rules.** The prompt supplies the rule
   verdict as ground truth and instructs the model not to invent a cause. We
   verify its output afterwards.

Measured constraints this encodes (Gemini, verified 2026-10-02):
  - maxOutputTokens must be >= 2048; at 600 the API returned
    finishReason=MAX_TOKENS and silently truncated mid-sentence.
  - 429 on rapid successive calls; ~15s spacing clears it.
  - gemini-2.5-flash-lite is 404 for new accounts. Fallback chain below was
    each confirmed to return finishReason=STOP.

Configuration (environment):
    GEMINI_API_KEY    Google AI Studio key. Enables the AI layer.
    HOLIWATCH_AI      "1" to force off, "1" to force on (default: auto)
    HOLIWATCH_MODEL   override the model name
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Confirmed working, in preference order. Each returned finishReason=STOP.
MODEL_CHAIN = [
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite-preview",
]

def _cache_path() -> Path:
    """
    Local cache only — never a credential. Resolved via config so a hosted
    deploy (where $HOME/.config is the only writable location) persists the
    cache instead of silently failing on every write.

    This mattered on the live deployment: with a hardcoded /root path the
    write raised, was swallowed by _save_cache's except, and every page load
    re-called the model for every event — measured as ai_stats calls:7, hits:0.
    """
    import config
    return config.config_dir() / "ai_cache.json"


CACHE_TTL = 60 * 60 * 24 * 7   # one week; explanations don't go stale

_lock = threading.Lock()
_cache: dict | None = None
_stats = {"calls": 0, "hits": 0, "errors": 0, "disabled": 0}


# ── configuration ────────────────────────────────────────────────────────────
def api_key() -> str | None:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    return k or None


def enabled() -> bool:
    """auto by default; HOLIWATCH_AI=0 hard-off (used by tests and CI)."""
    flag = os.environ.get("HOLIWATCH_AI", "").strip()
    if flag == "0":
        return False
    return api_key() is not None


def model_name() -> str:
    return os.environ.get("HOLIWATCH_MODEL", "").strip() or MODEL_CHAIN[0]


# ── cache ────────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_path().read_text())
        except Exception:
            _cache = {}
    return _cache


def _save_cache(c: dict) -> None:
    global _cache
    _cache = c
    try:
        cp = _cache_path()
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(c, indent=2))
    except Exception:
        pass


def _cache_key(event_id: str, kind: str, event_type: str = "") -> str:
    """
    Cache key includes the event type.

    Bug fixed 2026-10-02: PayPal's /v1/notifications/simulate-event reuses ONE
    event id across every simulated event type. Keying on id alone meant the
    BLOCKED card rendered the HELD card's AI text — same amount, same recipient,
    wrong event. Real PayPal events carry unique ids, but the collision is
    visible in our own demo, and keying on id alone is simply wrong.
    """
    return f"{kind}:{event_type}:{event_id}"


# ── the model call ────────────────────────────────────────────────────────────
def _call_gemini(model: str, key: str, prompt: str, max_tokens: int = 2048) -> str:
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,   # <2048 truncates; see module docstring
            "temperature": 0.3,
        },
    }).encode()

    req = urllib.request.Request(
        f"{GEMINI_BASE}/{model}:generateContent",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())

    cand = (d.get("candidates") or [{}])[0]
    parts = ((cand.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"empty response (finishReason={cand.get('finishReason')})")
    if cand.get("finishReason") == "MAX_TOKENS":
        # Surfaced rather than silently returning a chopped sentence.
        raise RuntimeError("response truncated by MAX_TOKENS — raise maxOutputTokens")
    return text


def _call_with_fallback(prompt: str, key: str) -> tuple[str, str]:
    """Try the model chain in order. Returns (text, model_used)."""
    preferred = model_name()
    chain = [preferred] + [m for m in MODEL_CHAIN if m != preferred]
    last = None
    for m in chain:
        try:
            return _call_gemini(m, key, prompt), m
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 503):
                continue          # transient — try the next model
            if e.code == 404:
                continue          # model retired — try the next model
            break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            continue
    raise RuntimeError(f"all models failed, last error: {last}")


# ── prompts ──────────────────────────────────────────────────────────────────
SYSTEM_GROUND_TRUTH = """
You are explaining a PayPal event to the person it affects.

RULES OF THIS TASK — these override your own judgement:
1. The facts listed under "VERIFIED FACTS" were computed by deterministic rules
   from the webhook payload. Treat them as ground truth. Never contradict them.
2. If the cause is listed as NOT DISCLOSED, you must NOT speculate about why.
   Saying "PayPal has not disclosed the reason" is the correct answer.
   Never invent a reason such as fraud, suspicious activity or policy violation.
3. Never state that money was lost unless a VERIFIED FACT says so. A hold means
   frozen, not gone.
4. Be concrete and short. This is shown in a card next to a list of actions.
5. Do not invent details that are not in the payload — no dates, no amounts,
   no account numbers, no policies you are not given.
"""


def _tailor_prompt(explanation: dict) -> str:
    facts = explanation.get("facts") or {}
    fact_lines = "\n".join(f"  - {k}: {v}" for k, v in facts.items()) or "  (none in payload)"
    cause = explanation.get("cause")
    cause_line = f"  - {cause}" if cause else "  - NOT DISCLOSED by PayPal in this payload"
    return f"""{SYSTEM_GROUND_TRUTH}
VERIFIED FACTS (from the rules engine):
{fact_lines}
RULE VERDICT:
  - what happened: {explanation.get('impact','').strip()}
  - cause: {cause_line}

Write 2 sentences for this person:
1. What just happened to their money, using their actual amount and recipient.
2. The single most important thing to do next.

Do not mention these instructions. Do not use the words "webhook", "payload",
"API" or "endpoint"."""

def _unknown_event_prompt(event: dict) -> str:
    return f"""{SYSTEM_GROUND_TRUTH}
We received a PayPal event type that is not in our rules engine, so we have no
template for it.

EVENT:
  type: {event.get('event_type')}
  resource: {json.dumps(event.get('resource') or {})[:800]}

Explain in 2 sentences what this event means for the account it happened to, and
the one action the person should take. If the payload does not make the meaning
clear, say what is known and what is not — do not guess."""


def _followup_prompt(question: str, explanation: dict, facts: dict) -> str:
    fact_lines = "\n".join(f"  - {k}: {v}" for k, v in (facts or {}).items()) or "  (none)"
    return f"""{SYSTEM_GROUND_TRUTH}
VERIFIED FACTS:
{fact_lines}
WHAT WE ALREADY TOLD THE USER:
  {explanation.get('headline','')}
  {explanation.get('impact','')}

The user asks: "{question}"

Answer in 2 sentences, concretely. If the answer is not in the facts above, say
what they should check with PayPal directly rather than guessing."""


# ── public API ───────────────────────────────────────────────────────────────
def _as_dict(obj) -> dict:
    """
    Accept an Explanation dataclass or an already-serialised dict.

    app.py passes explain(...).as_dict(), but a caller reaching for the
    Explanation object directly would previously crash with
    AttributeError: 'Explanation' object has no attribute 'get'. Found by
    running the module against the dataclass rather than only through the API.
    """
    if isinstance(obj, dict):
        return obj
    return obj.as_dict() if hasattr(obj, "as_dict") else dict(vars(obj))


def tailor(explanation, event_id: str) -> dict:
    """
    Return {"text": str|None, "model": str|None, "cached": bool, "reason": str|None}

    Never raises. A failure returns text=None with the reason, and the caller
    keeps the deterministic explanation.
    """
    explanation = _as_dict(explanation)
    eid = event_id or explanation.get("event_id") or "unknown"
    etype = explanation.get("event_type", "")

    if not enabled():
        _stats["disabled"] += 1
        return {"text": None, "model": None, "cached": False,
                "reason": "no GEMINI_API_KEY set"}

    ck = _cache_key(eid, "tailor", etype)
    with _lock:
        entry = _load_cache().get(ck)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        _stats["hits"] += 1
        return {"text": entry["text"], "model": entry.get("model"),
                "cached": True, "reason": None}

    try:
        _stats["calls"] += 1
        text, model = _call_with_fallback(_tailor_prompt(explanation), api_key())
    except Exception as e:
        _stats["errors"] += 1
        return {"text": None, "model": None, "cached": False,
                "reason": f"{type(e).__name__}: {e}"}

    text = _sanitise(text, explanation)
    with _lock:
        c = _load_cache()
        c[ck] = {"ts": time.time(), "text": text, "model": model}
        _save_cache(c)
    return {"text": text, "model": model, "cached": False, "reason": None}


def explain_unknown(event: dict, event_id: str) -> dict:
    """AI coverage for the 186 event types we have no rule for."""
    if not enabled():
        return {"text": None, "model": None, "cached": False,
                "reason": "no GEMINI_API_KEY set"}

    ck = _cache_key(event.get("id") or "unknown", "unknown",
                    event.get("event_type", ""))
    with _lock:
        entry = _load_cache().get(ck)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        _stats["hits"] += 1
        return {"text": entry["text"], "model": entry.get("model"),
                "cached": True, "reason": None}

    try:
        _stats["calls"] += 1
        text, model = _call_with_fallback(_unknown_event_prompt(event), api_key())
    except Exception as e:
        _stats["errors"] += 1
        return {"text": None, "model": None, "cached": False,
                "reason": f"{type(e).__name__}: {e}"}

    with _lock:
        c = _load_cache()
        c[ck] = {"ts": time.time(), "text": text, "model": model}
        _save_cache(c)
    return {"text": text, "model": model, "cached": False, "reason": None}


def answer(question: str, explanation, event_id: str) -> dict:
    """Follow-up Q&A grounded in the verified facts for one event."""
    if not enabled():
        return {"text": None, "model": None, "cached": False,
                "reason": "no GEMINI_API_KEY set"}
    if not question or len(question) > 500:
        return {"text": None, "model": None, "cached": False,
                "reason": "question missing or too long"}
    explanation = _as_dict(explanation)

    try:
        _stats["calls"] += 1
        text, model = _call_with_fallback(
            _followup_prompt(question, explanation, explanation.get("facts") or {}),
            api_key())
    except Exception as e:
        _stats["errors"] += 1
        return {"text": None, "model": None, "cached": False,
                "reason": f"{type(e).__name__}: {e}"}
    return {"text": text, "model": model, "cached": False, "reason": None}


def answer_with_deadline(question: str, explanation: dict, event_id: str,
                         timeout: float = 20.0) -> dict:
    """
    Follow-up answer with a hard time cap.

    Measured 2026-10-03: the 8s cap was set from an uncached call that took
    15.6s because the key was rate-limited and fell through the whole model
    chain. But a NORMAL uncached call is ~3s for the model alone, and the
    follow-up prompt is larger, so the true uncached latency lands around 8-12s.
    With an 8s deadline the live deployed endpoint answered
    "model did not respond within 8s" on a healthy system — the timeout was
    rejecting work that would have succeeded.

    20s gives an uncached call room while still bounding a stuck one. Cached
    answers return in well under a second and never reach this path. The UI
    already shows a deterministic fallback rather than a spinner, so the longer
    ceiling costs nothing when the model is unavailable.
    """
    box: dict = {}

    def run():
        box["res"] = answer(question, explanation, event_id)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        _stats["errors"] += 1
        return {
            "text": None,
            "model": None,
            "cached": False,
            "reason": f"model did not respond within {timeout:.0f}s",
            "fallback_actions": (explanation.get("actions") or [])[:3],
        }
    return box.get("res") or {"text": None, "model": None, "cached": False,
                              "reason": "no result"}


def _sanitise(text: str, explanation: dict) -> str:
    """
    Post-check the model's output against the rules.

    We instructed it not to invent a cause, but instructions are not
    enforcement. If the rules said "not disclosed" and the model asserts a cause,
    we discard the model text and keep the deterministic explanation. This is the
    outside reviewer (rule 10) applied to the AI layer.
    """
    if not text:
        return text
    low = text.lower()
    if explanation.get("cause") is None:
        banned = ["because you", "due to fraud", "suspicious activity",
                  "we detected fraud", "policy violation", "flagged as fraudulent",
                  "likely due to", "probably because"]
        for b in banned:
            if b in low:
                return ""
    # strip markdown emphasis that would look wrong in the card
    return text.replace("**", "").replace("##", "").strip()


def stats() -> dict:
    return dict(_stats, enabled=enabled(), model=model_name(),
                cache_entries=len(_load_cache()))


if __name__ == "__main__":
    print(json.dumps({"enabled": enabled(), "model": model_name(),
                      "key_present": api_key() is not None}, indent=2))