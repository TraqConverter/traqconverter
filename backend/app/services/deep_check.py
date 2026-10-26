"""On-demand AI meaning check: Claude compares the source and the translation for flipped negations, swapped parties, wrong dates or amounts, omissions and additions."""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from typing import Optional

import anthropic

from app.services import ai_usage, claude_params
from app.services.glossary_service import lang_key, language_name, project_source_language
from app.services.qa_checks import norm

logger = logging.getLogger(__name__)

MODEL = os.getenv("DEEP_CHECK_MODEL", "claude-sonnet-5")
EFFORT = os.getenv("DEEP_CHECK_EFFORT", "medium")
# One deep check uses one AI edit from the document's allowance per started block of this many pages.
PAGES_PER_EDIT = max(1, int(os.getenv("DEEP_CHECK_PAGES_PER_EDIT", "4")))
MAX_TOKENS = 12_000
MAX_SOURCE_CHARS = 200_000
MAX_TRANSLATION_CHARS = 200_000
MAX_FINDINGS = 40

CATEGORIES = ("negation", "parties", "date", "amount", "omission", "addition", "meaning")
LABELS = {
    "negation": "Negation flipped",
    "parties": "Parties or roles swapped",
    "date": "Date differs",
    "amount": "Amount differs",
    "omission": "Omitted",
    "addition": "Added",
    "meaning": "Meaning changed",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                    "block_id": {"type": "string"},
                    "source_quote": {"type": "string"},
                    "translation_quote": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["category", "severity", "block_id", "source_quote", "translation_quote", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM = """You are the second reviewer of a certified translation of an official or legal document. A certified \
translator will sign it, so every meaning error you miss can reach a court, a registry or an immigration office; every \
false alarm wastes their time. Compare the SOURCE with the TRANSLATION for meaning only, and report what a careful \
legal reviewer would insist on correcting.

Report these categories:
- negation: a statement whose polarity flipped ("is not liable" became "is liable", "without" became "with", \
"may" became "must not").
- parties: people, parties or roles swapped or confused (buyer and seller, landlord and tenant, plaintiff and \
defendant, father and mother, issuer and holder, employer and employee, the declarant and the subject).
- date: a date, deadline, period or age that differs in context (a different day, month or year, "within 30 days" \
became "after 30 days").
- amount: an amount, quantity, percentage, currency, unit or reference number that differs.
- omission: source content with no counterpart in the translation (a clause, a sentence, a row, a stamp's text).
- addition: content in the translation with no basis in the source.
- meaning: any other change that would mislead the reader about a fact or an obligation.

Do NOT report:
- style, word choice, terminology preferences, register or punctuation;
- numbers or dates written in another format (1.000,00 and 1,000.00; 12/07/2011 and 12 July 2011);
- names transliterated into another script, or institutions and places given their usual name in the target language;
- the translator's notes in square brackets, such as [Stamp: ...], [Signature], [illegible] or [Handwritten: ...]: \
they describe the original and are expected;
- the source's layout, line breaks or OCR noise.

For each finding:
- severity: "error" when it changes a fact or the legal meaning (negation, parties, amounts, dates, a dropped clause); \
"warning" when it is probably wrong or ambiguous; "info" when minor but worth a look.
- block_id: the id of the translation paragraph concerned, exactly as listed; for an omission, the paragraph where \
the missing content belongs.
- source_quote: the shortest exact excerpt of the SOURCE that shows the problem, copied character for character.
- translation_quote: the shortest exact excerpt of the TRANSLATION, copied character for character; empty for an omission.
- explanation: one short sentence in English for the translator naming what differs, e.g. "The source says the \
seller pays the costs; the translation says the buyer."

Report each problem once. If the translation is faithful, return an empty list."""


class DeepCheckError(RuntimeError):
    pass


def edits_for(project) -> int:
    return max(1, math.ceil(max(1, project.page_count or 1) / PAGES_PER_EDIT))


def _listing(paras: list[dict]) -> tuple[str, bool]:
    lines, total = [], 0
    for p in paras:
        line = f"{p['id']}: {' '.join(p['text'].split())}"
        if total + len(line) > MAX_TRANSLATION_CHARS:
            return "\n".join(lines), True
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines), False


def _request(project, source: str, listing: str) -> dict:
    src = language_name(lang_key(project_source_language(project))) or "the source language"
    tgt = language_name(lang_key(project.target_language)) or project.target_language or "the target language"
    source_block = f"SOURCE ({src})\n{source}"
    # The source rarely changes between runs, so a re-check after edits reads it from the cache.
    first = (
        claude_params.cached_text_block(source_block)
        if claude_params.worth_caching(MODEL, SYSTEM + source_block)
        else {"type": "text", "text": source_block}
    )
    params = claude_params.request_params(MODEL, max_tokens=MAX_TOKENS, effort=EFFORT)
    output_config = {**params.pop("output_config", {}), "format": {"type": "json_schema", "schema": SCHEMA}}
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": [
                first,
                {"type": "text", "text": f"TRANSLATION ({tgt}), one paragraph per line as id: text\n{listing}"},
            ],
        }],
        "output_config": output_config,
        **params,
    }


def _locate(quote: str, paras: list[dict]) -> Optional[str]:
    q = norm(quote)
    if not q:
        return None
    for p in paras:
        if q in norm(p["text"]):
            return p["id"]
    return None


def findings_to_items(findings: list[dict], ctx, item) -> list[dict]:
    """Model findings as check items; drops any whose quotes appear in neither text."""
    ids = {p["id"] for p in ctx.paras}
    translation = norm(ctx.translation)
    source = norm(ctx.source_text)
    out = []
    for f in findings[:MAX_FINDINGS]:
        category = f.get("category") if f.get("category") in CATEGORIES else "meaning"
        severity = f.get("severity") if f.get("severity") in ("error", "warning", "info") else "warning"
        sq = (f.get("source_quote") or "").strip()
        tq = (f.get("translation_quote") or "").strip()
        explanation = " ".join((f.get("explanation") or "").split())[:300]
        tq_ok = bool(tq) and norm(tq) in translation
        sq_ok = bool(sq) and norm(sq) in source
        if not (tq_ok or sq_ok) or not explanation:
            continue
        bid = f.get("block_id") if f.get("block_id") in ids else None
        if tq_ok:
            bid = _locate(tq, ctx.paras) or bid
        out.append(item(
            "meaning", f"{category}|{norm(sq)[:80]}|{norm(tq)[:80]}", severity,
            f"{LABELS[category]}: {explanation}", bid, ctx.source_for_block(bid) if bid else None,
            category=category, quote_source=sq[:300], quote_translation=tq[:300],
        ))
    return out


def run(project, ctx, item) -> dict:
    api_key = claude_params.api_key()
    if not api_key:
        raise DeepCheckError("The AI check isn't available right now")
    source = ctx.source_text.strip()
    if not source or not ctx.paras:
        raise DeepCheckError("There's no source text to compare with")
    truncated = len(source) > MAX_SOURCE_CHARS
    listing, cut = _listing(ctx.paras)
    truncated = truncated or cut
    request = _request(project, source[:MAX_SOURCE_CHARS], listing)
    try:
        resp = claude_params.create_message(anthropic.Anthropic(api_key=api_key), **request)
    except anthropic.APIError as e:
        logger.warning("Deep check call failed (project=%s): %s", project.id, e)
        raise DeepCheckError("The AI check failed; try again in a minute")
    claude_params.log_usage("deep_check", resp)
    if resp.stop_reason == "refusal":
        raise DeepCheckError("The AI check declined this document")
    if resp.stop_reason == "max_tokens":
        raise DeepCheckError("The document is too long for one AI check")
    try:
        body = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
    except json.JSONDecodeError:
        raise DeepCheckError("The AI check returned an unreadable answer; try again")
    counts = ai_usage.anthropic_counts(getattr(resp, "usage", None))
    return {
        "items": findings_to_items(body.get("findings") or [], ctx, item),
        "model": getattr(resp, "model", MODEL) or MODEL,
        "truncated": truncated,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "usd": str(ai_usage.cost_usd(getattr(resp, "model", MODEL) or MODEL, counts)),
    }
