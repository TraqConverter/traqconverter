"""The layout rebuild for a document another model translates: Claude rebuilds the PDF in its own language, then the chosen model translates that copy's text in place."""
import logging
import re
from typing import Callable, Optional

from app.services import docx_blocks, job_progress
from app.services.ai_translation_service import uses_openai
from app.services.glossary_service import project_source_language

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
_EDGES = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)


class UntranslatedText(RuntimeError):
    pass


def needs_separate_translation(project) -> bool:
    """True when the project's model isn't the one that rebuilds the layout, so the rebuild must not write the translation."""
    return uses_openai(getattr(project, "model", None))


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def translate_docx(data: bytes, translate: Callable[[list[str]], list[str]]) -> bytes:
    """Replace the text of every paragraph (body, tables, headers, footers, text boxes) with its translation.

    Tabs split a paragraph into pieces translated separately, so tab-aligned layouts keep their columns.
    """
    doc = docx_blocks._Doc.load(data)
    plan = []
    wanted: dict[str, None] = {}
    for p in doc.paragraphs():
        text = docx_blocks.paragraph_text(p)
        if not _has_letters(text):
            continue
        pieces = []
        for part in text.split("\t"):
            lead, core, trail = _EDGES.match(part).groups()
            pieces.append((lead, core, trail))
            if _has_letters(core):
                wanted[core] = None
        plan.append((p, pieces))
    if not plan:
        return data

    sources = list(wanted)
    translated = translate(sources)
    found = {src: (out or "").strip() for src, out in zip(sources, translated)}
    missing = [src for src in sources if not found.get(src)]
    if missing:
        raise UntranslatedText(f"{len(missing)} of {len(sources)} passages of the rebuilt document could not be translated")

    for p, pieces in plan:
        new_text = "\t".join(lead + (found.get(core) or core) + trail for lead, core, trail in pieces)
        docx_blocks.set_paragraph_text(p, new_text)
    return doc.dump()


def _translator(db, project, source_lang: str, target_lang: str, extra_instructions: str):
    from app.services import translation_memory_service as tm_service
    from app.services import tm_keys
    from app.services.translation_processor import translate_resilient

    def run(texts: list[str]) -> list[str]:
        memory = {}
        if getattr(project, "use_tm", True):
            try:
                memory = tm_service.exact_map(db, project, texts)
            except Exception:
                logger.exception("Translation memory lookup for the rebuilt document failed (project=%s)", project.id)
        out = [memory.get(tm_keys.normalise_text(t)) or "" for t in texts]
        todo = [i for i, t in enumerate(out) if not t]
        for start in range(0, len(todo), BATCH_SIZE):
            chunk = todo[start:start + BATCH_SIZE]
            results = translate_resilient(
                [texts[i] for i in chunk], source_lang, target_lang, db, project, extra_instructions=extra_instructions
            )
            for i, result in zip(chunk, results):
                out[i] = result or ""
            job_progress.report(job_progress.REBUILDING, 0.9 + 0.1 * (start + len(chunk)) / len(todo))
        return out

    return run


def rebuild_then_translate(
    pdf_bytes: bytes,
    *,
    db,
    project,
    source_lang: str,
    target_lang: str,
    extra_instructions: Optional[str] = None,
) -> bytes:
    """Claude rebuilds the layout as a same-language copy; the project's model then translates its text."""
    layout_lang = project_source_language(project) or ""
    if extra_instructions:
        from app.services.claude_multiturn_rebuild import author_rebuild_docx_multiturn

        copy = author_rebuild_docx_multiturn(
            pdf_bytes,
            layout_lang,
            layout_lang,
            extra_instructions=extra_instructions,
            reproduce=True,
        )
    else:
        from app.services.claude_authored_rebuild import author_rebuild_docx

        copy = author_rebuild_docx(
            pdf_bytes=pdf_bytes,
            source_lang=layout_lang,
            target_lang=layout_lang,
            reproduce=True,
        )
    job_progress.report(job_progress.REBUILDING, 0.9, "Translating the rebuilt document")
    return translate_docx(copy, _translator(db, project, source_lang, target_lang, extra_instructions or ""))
