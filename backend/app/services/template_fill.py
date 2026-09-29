"""Translate a new document by adapting the team's finished translation of the same kind of document."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Optional

import anthropic

from app.services import claude_params, docx_blocks
from app.services.claude_multiturn_rebuild import coverage_failed, extract_number_tokens, missing_source_numbers

logger = logging.getLogger(__name__)

MAX_TEMPLATE_XML_CHARS = 150_000
MAX_TOKENS = 32_000
EFFORT = os.getenv("TEMPLATE_FILL_EFFORT", "low")

_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": ["set_text", "replace_paragraph", "replace", "insert_before", "insert_after", "delete"],
                    },
                    "target": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["op", "target", "content"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["operations", "notes"],
    "additionalProperties": False,
}

_SYSTEM = """You produce certified translations from {source_lang} into {target_lang} for a professional \
translator. The attached file is a NEW source document. The translator already translated a document of the \
same kind: you get that document's source text and its approved translation (the TEMPLATE), as an outline \
and as WordprocessingML blocks with ids.

Return the operations that turn the TEMPLATE into the translation of the NEW source document:
- Where the new source says the same thing as the template's source, keep the template's wording, \
terminology, capitalisation, layout and bracketed notations exactly as they are. Do not rephrase.
- Change only what differs: names, dates, numbers, codes, addresses, places, and any sentence, row or \
notation whose content differs. Every name, number, date and code in the result must come from the NEW \
source; nothing that belongs to the old document may remain.
- Numbers, dates and codes are copied exactly as the new source writes them.

Operations (use the smallest that does the job):
- set_text: new text for ONE paragraph (target = paragraph id, including paragraphs inside tables, headers \
and footers). "content" is the paragraph's complete new plain text (\\t tab, \\n line break). Formatting is kept.
- replace_paragraph: restructure ONE paragraph; "content" is one or more <w:p> elements.
- insert_before / insert_after: add <w:p>/<w:tbl> XML next to a top-level block (outline id).
- delete: remove a top-level block ("content": "").
- replace: swap a top-level block for new <w:p>/<w:tbl> XML, e.g. a table whose rows differ.
XML uses the w: prefix (already declared); top level only <w:p> or <w:tbl>; no images, drawings, \
hyperlinks, relationship ids or <w:sectPr>. Keep the <w:bookmarkStart w:name="_b..."/> pair of each \
paragraph you keep.

Non-text elements and unreadable content:
{notation_rules}

Put in "notes" one short sentence on what differed (for the log)."""


class TemplateFillError(RuntimeError):
    pass


def docx_text(data: bytes) -> str:
    doc = docx_blocks._Doc.load(data)
    return "\n".join(docx_blocks.paragraph_text(p) for p in doc.paragraphs())


_WORD_RE = re.compile(r"[^\W\d_][^\W_]{2,}", re.UNICODE)


def _proper_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text or "") if w[0].isupper()}


def leftover_values(template_text: str, template_source: str, new_source: str, output_text: str) -> list[str]:
    """Values the template carried over verbatim from its own source that the new source doesn't contain."""
    stale_numbers = extract_number_tokens(template_text) - extract_number_tokens(new_source)
    stale_numbers &= extract_number_tokens(output_text)
    new_words = {w.casefold() for w in _WORD_RE.findall(new_source or "")}
    old_words = {w.casefold() for w in _WORD_RE.findall(template_source or "")}
    carried = {w for w in _proper_words(template_text) if w.casefold() in old_words and w.casefold() not in new_words}
    stale_words = carried & _proper_words(output_text)
    return sorted(stale_numbers) + sorted(stale_words)


def source_block(data: bytes, file_name: str) -> dict:
    name = (file_name or "").lower()
    cache = {"type": "ephemeral"}
    b64 = base64.b64encode(data).decode()
    if name.endswith(".pdf"):
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}, "cache_control": cache}
    for ext, media in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
        if name.endswith(ext):
            return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}, "cache_control": cache}
    raise TemplateFillError(f"Unsupported source for template fill: {file_name}")


def _template_text(template_docx: bytes, template_source: str, terminology: str) -> str:
    ids = docx_blocks.block_ids(template_docx)
    _, xml = docx_blocks.units_for_blocks(template_docx, ids, neighbours=0)
    if sum(len(x) for x in xml.values()) > MAX_TEMPLATE_XML_CHARS:
        raise TemplateFillError("Template too large to adapt in one pass")
    blocks = "\n".join(f"--- [{uid}]\n{x}" for uid, x in xml.items())
    parts = [
        f"SOURCE TEXT OF THE TEMPLATE'S ORIGINAL DOCUMENT\n{template_source or '(not available)'}",
        f"TEMPLATE OUTLINE\n{docx_blocks.outline(template_docx)}",
        f"TEMPLATE BLOCKS\n{blocks}",
    ]
    if terminology:
        parts.append(terminology)
    return "\n\n".join(parts)


def fill_from_template(
    *,
    source_data: bytes,
    file_name: str,
    source_text: str,
    template_docx: bytes,
    template_source: str,
    source_lang: str,
    target_lang: str,
    terminology: str = "",
    model: Optional[str] = None,
) -> tuple[bytes, dict]:
    """Return the tagged translated DOCX and timing/usage stats; raise TemplateFillError when the result can't be trusted."""
    from app.services.claude_authored_rebuild import NOTATION_RULES

    key = claude_params.api_key()
    if not key:
        raise TemplateFillError("ANTHROPIC_API_KEY not set")
    started = time.monotonic()
    client = anthropic.Anthropic(api_key=key)
    model = claude_params.rebuild_model(model)
    template_docx = docx_blocks.tag_blocks(template_docx)
    template_text = docx_text(template_docx)
    system = _SYSTEM.format(
        source_lang=source_lang or "the source language",
        target_lang=target_lang,
        notation_rules=NOTATION_RULES,
    )
    messages = [{
        "role": "user",
        "content": [
            source_block(source_data, file_name),
            {"type": "text", "text": _template_text(template_docx, template_source, terminology)},
            {"type": "text", "text": "Return the operations for the NEW source document."},
        ],
    }]
    params = claude_params.request_params(model, max_tokens=MAX_TOKENS, thinking=True, effort=EFFORT)
    output_config = {**params.pop("output_config", {}), "format": {"type": "json_schema", "schema": _SCHEMA}}
    stats = {"model": model, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0}

    problem = ""
    for attempt in range(2):
        try:
            resp = claude_params.create_message(
                client,
                model=model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messages,
                output_config=output_config,
                **params,
            )
        except anthropic.APIError as e:
            raise TemplateFillError(f"Template fill call failed: {e}") from e
        claude_params.log_usage("template_fill", resp)
        usage = getattr(resp, "usage", None)
        stats["calls"] += 1
        for field, attr in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                            ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
            stats[field] += int(getattr(usage, attr, 0) or 0)
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise TemplateFillError(f"Template fill stopped: {resp.stop_reason}")
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            result = json.loads(raw)
            out, _ = docx_blocks.apply_operations(template_docx, result.get("operations") or [])
        except (json.JSONDecodeError, docx_blocks.DocxEditError) as e:
            problem = f"Those operations could not be applied: {e}. Return corrected JSON."
        else:
            out_text = docx_text(out)
            missing, total = missing_source_numbers(source_text, out_text)
            leftovers = leftover_values(template_text, template_source, source_text, out_text)
            stats.update(
                ops=len(result.get("operations") or []),
                missing_numbers=len(missing),
                source_numbers=total,
                leftovers=leftovers[:20],
                notes=(result.get("notes") or "")[:300],
            )
            if not coverage_failed(missing, total) and not leftovers:
                stats["seconds"] = round(time.monotonic() - started, 1)
                logger.info("Template fill OK: %s", stats)
                return docx_blocks.tag_blocks(out), stats
            problem = "The result is not a faithful translation of the NEW source yet."
            if leftovers:
                problem += f" These values from the old document are still present: {', '.join(leftovers[:30])}."
            if coverage_failed(missing, total):
                problem += f" These numbers of the new source are missing: {', '.join(missing[:30])}."
            problem += " Return the complete corrected list of operations, applied to the original template."
        logger.warning("Template fill attempt %d rejected: %s", attempt + 1, problem[:300])
        messages = messages + [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": problem},
        ]
    stats["seconds"] = round(time.monotonic() - started, 1)
    raise TemplateFillError(f"Template fill rejected after retry ({problem[:200]}); stats={stats}")
