"""Deterministic QA checks a certified translator runs before delivery: number formats, identifiers, dropped or untranslated text, consistency and formatting."""
from __future__ import annotations

import difflib
import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services import source_map

# Languages that write 1.234,56; everything else writes 1,234.56.
DECIMAL_COMMA = {
    "it", "de", "es", "fr", "pt", "nl", "pl", "ru", "uk", "tr", "cs", "sk", "sl", "hr", "sr", "bs", "ro", "bg", "el",
    "hu", "da", "sv", "no", "nb", "nn", "fi", "et", "lv", "lt", "id", "vi", "sq", "mk", "az", "ka", "be",
}
# Characters per character of English for the same content: a translation far below its expected share likely lost text.
LENGTH_FACTOR = {
    "en": 1.0, "it": 1.12, "es": 1.15, "fr": 1.18, "pt": 1.12, "de": 1.2, "nl": 1.15, "pl": 1.1, "ro": 1.1, "ru": 1.05,
    "uk": 1.05, "bg": 1.05, "el": 1.15, "tr": 1.0, "sv": 1.0, "da": 1.0, "no": 1.0, "fi": 1.05, "cs": 1.0, "sk": 1.0,
    "hu": 1.1, "hr": 1.0, "sr": 1.0, "sq": 1.1, "ar": 0.95, "he": 0.8, "fa": 0.95, "hi": 1.0, "ur": 0.95, "th": 0.95,
    "vi": 1.1, "id": 1.15, "ms": 1.15, "zh": 0.33, "ja": 0.45, "ko": 0.5,
}
# Names are routinely transliterated into these scripts, so a Latin name missing from the text says nothing.
NON_LATIN = {"ru", "uk", "bg", "sr", "mk", "be", "el", "ar", "he", "fa", "ur", "hi", "th", "zh", "ja", "ko", "ka", "hy"}
SHORT_RATIO = 0.5
DOC_SHORT_RATIO = 0.6
MIN_SHORT_SOURCE = 60
MIN_DOC_SOURCE = 600
MIN_DROPPED_SOURCE = 40

_PAGE_INLINE_RE = re.compile(
    r"(?i)\b(?:pag(?:ina|e)?|p|seite|página|strona|blatt|foglio|sheet|folio)\.?\s*\d{1,3}"
    r"(?:\s*(?:/|di|of|von|de|sur|z|из)\s*\d{1,3})?\b"
)
_PAGE_ALONE_RE = re.compile(r"^\W*(?:\d{1,3}\s*(?:/|di|of|von|de|sur|z)\s*\d{1,3}|-\s*\d{1,3}\s*-)\W*$", re.I)
_LIST_MARKER_RE = re.compile(r"^\s*\(?(\d{1,2})[.)]\s+(?=([^\W\d_]+))")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'()\[\]]+")
_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]{1,60}\}\}|\{\d{1,2}\}|(?<![\w%])%(?:\d\$)?[sdif](?!\w)|</?[a-z][a-z0-9]{0,9}\s*/?>")
_LEADING_ENUM_RE = re.compile(r"^\s*(?:[a-zA-Z]|\d{1,3}|[ivxIVX]{1,5})\)\s*")
_DOUBLE_SPACE_RE = re.compile(r"[^\W\d_][,.;:]?  (?=[^\W\d_])")
_WORD_RE = re.compile(r"[^\W\d_][^\W\d_'’\-]*")


def lang_base(value: str) -> str:
    return (value or "").split("-")[0].lower()


def decimal_comma(lang: str) -> bool:
    return lang_base(lang) in DECIMAL_COMMA


def parse_number(tok: str, comma_decimal: bool) -> Optional[Decimal]:
    """The value of 1.234,56 / 1,234.56 / 12,5 as written in a language with the given decimal separator."""
    if "/" in tok or "-" in tok or not tok[:1].isdigit():
        return None
    dots, commas = tok.count("."), tok.count(",")
    if dots and commas:
        dec = "." if tok.rfind(".") > tok.rfind(",") else ","
        whole, _, frac = tok.rpartition(dec)
        raw = re.sub(r"[.,]", "", whole) + "." + frac
    elif dots or commas:
        sep = "." if dots else ","
        if (dots or commas) > 1:
            raw = tok.replace(sep, "")
        else:
            whole, frac = tok.split(sep)
            is_decimal = (sep == ",") == comma_decimal
            # The other language's decimal mark followed by three digits is a thousands separator: 1.234 in German.
            raw = f"{whole}.{frac}" if is_decimal or len(frac) != 3 else whole + frac
    else:
        raw = tok
    try:
        return Decimal(raw).normalize()
    except InvalidOperation:
        return None


def misread_in_target(tok: str, src_lang: str, tgt_lang: str) -> bool:
    """A number copied as-is whose value changes when read with the target's separators: German 1.500 in English."""
    if decimal_comma(src_lang) == decimal_comma(tgt_lang):
        return False
    a, b = parse_number(tok, decimal_comma(src_lang)), parse_number(tok, decimal_comma(tgt_lang))
    return a is not None and b is not None and a != b


def kept_source_format(tok: str, src_lang: str, tgt_lang: str) -> bool:
    """A number copied with the source's decimal mark (1.000,50 or 12,5 in an English text), or one that would be misread."""
    if decimal_comma(src_lang) == decimal_comma(tgt_lang) or parse_number(tok, decimal_comma(src_lang)) is None:
        return False
    if misread_in_target(tok, src_lang, tgt_lang):
        return True
    seps = [c for c in tok if c in ".,"]
    if not seps:
        return False
    src_dec = "," if decimal_comma(src_lang) else "."
    last = seps[-1]
    frac = tok.rsplit(last, 1)[1]
    return last == src_dec and (len(set(seps)) == 2 or len(frac) != 3)


def numbers_text(src: str) -> str:
    """Segment text without page numbers and list markers, which a layout may drop or renumber."""
    if _PAGE_ALONE_RE.match(src):
        return ""
    text = _PAGE_INLINE_RE.sub(" ", src)
    # The identifier check compares these whole; their digit groups would be reported twice.
    for found in ibans(text) + emails(text) + urls(text):
        text = text.replace(found, " ")
    m = _LIST_MARKER_RE.match(text)
    if m and source_map.fold(m.group(2)) not in _month_words():
        text = text[m.end():]
    return text


def _month_words() -> set:
    from app.services.review_checks import _MONTH_OF

    return set(_MONTH_OF)


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def ibans(text: str) -> list[str]:
    return [m.group(0) for m in _IBAN_RE.finditer(text or "") if iban_valid(m.group(0))]


def emails(text: str) -> list[str]:
    return [e.rstrip(".") for e in _EMAIL_RE.findall(text or "")]


def urls(text: str) -> list[str]:
    return [u.rstrip(".,;:") for u in _URL_RE.findall(text or "")]


def _url_key(url: str) -> str:
    u = re.sub(r"(?i)^https?://", "", url).rstrip("/").lower()
    return u[4:] if u.startswith("www.") else u


def placeholders(text: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(text or "")


def unbalanced(text: str) -> bool:
    body = _LEADING_ENUM_RE.sub("", text or "")
    return body.count("(") != body.count(")") or body.count("[") != body.count("]")


def norm(text: str) -> str:
    return " ".join(source_map.fold(text).split()).strip(" .;:,")


def snippet(text: str, n: int = 60) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"


def align(paras: list[dict], segments: list[dict]) -> dict[str, list[int]]:
    """Paragraph id -> the source segments it translates, by shared words, names and numbers."""
    boxed = [{**s, "bbox": s.get("bbox") or [0.0, 0.0, 1.0, 1.0]} for s in segments if s.get("toks")]
    return {pid: e["segments"] for pid, e in source_map.match_segments(paras, boxed).items()}


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class QA:
    """The new checks over a review_checks context, sharing its paragraphs, segments and item helpers."""

    def __init__(self, ctx, item):
        from app.services.glossary_service import lang_key, project_source_language

        self.ctx = ctx
        self.item = item
        self.src = lang_base(lang_key(project_source_language(ctx.project)))
        self.tgt = lang_base(lang_key(ctx.project.target_language))
        self.segments = [s for s in ctx.segments if (s.get("src") or "").strip() and not s.get("placeholder")]
        self.by_index = {s["index"]: s for s in ctx.segments}
        self.alignment = align(ctx.paras, ctx.segments)
        self.claims: dict[int, list[str]] = {}
        for pid, idxs in self.alignment.items():
            for i in idxs:
                self.claims.setdefault(i, []).append(pid)
        self.order = [p["id"] for p in ctx.paras]

    def _sole_segments(self, pid: str) -> list[dict]:
        """The paragraph's segments when no other paragraph shares them."""
        idxs = self.alignment.get(pid) or []
        if not idxs or any(len(self.claims.get(i, [])) > 1 for i in idxs):
            return []
        return [self.by_index[i] for i in idxs if i in self.by_index]

    def _block_near(self, seg: dict) -> Optional[str]:
        """The paragraph translating the closest earlier source segment: where a dropped passage should be."""
        before = [i for i in self.claims if i < seg["index"]]
        if not before:
            return self.order[0] if self.order else None
        return self.claims[max(before)][0]

    # --- numbers -----------------------------------------------------------------

    def number_formats(self, kept: list[str], block_of: dict) -> list[dict]:
        """Numbers copied with the source's separators; a reader of the target language may read 1.500 as one and a half."""
        if not kept or decimal_comma(self.src) == decimal_comma(self.tgt):
            return []
        misread = [t for t in kept if misread_in_target(t, self.src, self.tgt)]
        if misread:
            examples = ", ".join(misread[:4])
            return [self.item(
                "number_format", "misread", "warning",
                f"{len(misread)} number{'s' if len(misread) > 1 else ''} kept the source separators and read differently in the "
                f"target language ({examples}); write them in the target format or keep them deliberately",
                block_of.get(misread[0]),
            )]
        examples = ", ".join(kept[:4])
        return [self.item(
            "number_format", "kept", "info",
            f"{len(kept)} number{'s' if len(kept) > 1 else ''} keep the source format ({examples})",
            block_of.get(kept[0]),
        )]

    # --- identifiers ---------------------------------------------------------------

    def identifiers(self) -> tuple[list[dict], set[str]]:
        """IBANs, emails and URLs must be copied character for character."""
        ctx = self.ctx
        items, seen = [], set()
        t_ibans = {i.replace(" ", "").upper() for i in ibans(ctx.translation)}
        t_stream = re.sub(r"[^A-Z0-9]", "", ctx.translation.upper())
        t_emails = {e.lower() for e in emails(ctx.translation)}
        t_urls = {_url_key(u) for u in urls(ctx.translation)}
        for seg in ctx.segments:
            for iban in ibans(seg["src"]):
                key = iban.replace(" ", "").upper()
                if key in seen:
                    continue
                seen.add(key)
                if key in t_ibans or key in t_stream:
                    continue
                close = [t for t in t_ibans if t[:2] == key[:2] and difflib.SequenceMatcher(None, t, key).ratio() > 0.8]
                msg = (f"IBAN {iban} reads {close[0]} in the translation" if close
                       else f"IBAN {iban} from the source isn't in the translation")
                items.append(self._located("identifier", key, "error", msg, seg))
            for email in emails(seg["src"]):
                key = email.lower()
                if key in seen:
                    continue
                seen.add(key)
                if key not in t_emails:
                    items.append(self._located("identifier", key, "error", f"Email {email} isn't copied exactly", seg))
            for url in urls(seg["src"]):
                key = _url_key(url)
                if key in seen or "@" in url:
                    continue
                seen.add(key)
                if key not in t_urls and key not in ctx.translation.lower():
                    items.append(self._located("identifier", key, "warning", f"Web address {url} isn't copied exactly", seg))
        return items, {re.sub(r"[^A-Z0-9]", "", s.upper()) for s in seen}

    def _located(self, kind, key, severity, message, seg, **extra) -> dict:
        bid = self.ctx.block_for(seg) or (self.claims.get(seg["index"]) or [None])[0]
        return self.item(kind, key, severity, message, bid, self.ctx.ref_for(seg, bid), **extra)

    # --- names (only when the model's name list is unavailable) -------------------

    def capitalised_names(self) -> list[dict]:
        from app.services.review_checks import _LANG_SETS

        if self.src == "de" or self.tgt in NON_LATIN or self.src == self.tgt:
            return []
        common = set().union(*_LANG_SETS.values()) | source_map._STOP
        t_words = {source_map.fold(w) for w in _WORD_RE.findall(self.ctx.translation)}
        items, seen = [], set()
        for seg in self.segments:
            run: list[str] = []
            words = _WORD_RE.findall(seg["src"]) + [""]
            for w in words:
                if w and w[0].isupper() and len(w) >= 2 and source_map.fold(w) not in common:
                    run.append(w)
                    continue
                if len(run) >= 2:
                    name = " ".join(run)
                    folded = [source_map.fold(x) for x in run]
                    if name not in seen and not all(
                        f in t_words or difflib.get_close_matches(f, t_words, n=1, cutoff=0.85) for f in folded
                    ):
                        seen.add(name)
                        items.append(self._located(
                            "name", name, "info", f"Name {name} may be missing (fine if transliterated or translated)", seg,
                        ))
                run = []
            if len(items) >= 15:
                break
        return items

    # --- missing, dropped and untranslated text -----------------------------------

    def _expected_ratio(self) -> float:
        return LENGTH_FACTOR.get(self.tgt, 1.0) / LENGTH_FACTOR.get(self.src, 1.0)

    def missing_text(self, authored: bool) -> list[dict]:
        ctx = self.ctx
        items = []
        t_toks = source_map.tokens(ctx.translation)
        expected = self._expected_ratio()
        for seg in self.segments:
            src = seg["src"].strip()
            if len(src) < MIN_DROPPED_SOURCE or sum(c.isalpha() for c in src) < 20 or seg["index"] in self.claims:
                continue
            tgt = (seg.get("tgt") or "").strip()
            if not tgt:
                if not authored:
                    items.append(self._dropped(seg, "error", f"No translation for “{snippet(src)}”"))
                continue
            want = source_map.tokens(tgt)
            weight = source_map._w(want)
            if weight >= 6 and source_map._w(want & t_toks) / weight < 0.5:
                items.append(self._dropped(seg, "warning", f"This source passage may be missing from the translation: “{snippet(src)}”"))
        for p in ctx.paras:
            segs = self._sole_segments(p["id"])
            src_len = sum(len(s["src"].strip()) for s in segs)
            if src_len < MIN_SHORT_SOURCE:
                continue
            ratio = len(p["text"].strip()) / src_len
            if ratio < expected * SHORT_RATIO:
                items.append(self.item(
                    "short", _key(p["id"], p["text"]), "warning",
                    f"Much shorter than the source ({round(ratio * 100)}% of its length): a sentence may be missing",
                    p["id"], ctx.ref_for(segs[0], p["id"]),
                ))
        src_total = sum(len(s["src"].strip()) for s in self.segments)
        tgt_total = sum(len(p["text"].strip()) for p in ctx.paras)
        if src_total >= MIN_DOC_SOURCE and tgt_total / src_total < expected * DOC_SHORT_RATIO:
            items.append(self.item(
                "short", "document", "warning",
                f"The translation is {round(tgt_total / src_total * 100)}% the length of the source, where about "
                f"{round(expected * 100)}% is usual: check for dropped passages",
            ))
        return items

    def _dropped(self, seg, severity, message) -> dict:
        bid = self._block_near(seg)
        return self.item("missing", _key(seg["index"], seg["src"]), severity, message, bid, self.ctx.ref_for(seg, None))

    def identical_to_source(self, verdicts: dict) -> list[dict]:
        """A long sentence copied unchanged from the source was left untranslated."""
        if not self.src or self.src == self.tgt:
            return []
        long_sources = set()
        for s in self.segments:
            words = _WORD_RE.findall(s["src"])
            if len(s["src"].strip()) >= 40 and len(words) >= 6 and sum(w.islower() and len(w) >= 3 for w in words) >= 3:
                long_sources.add(norm(s["src"]))
        items = []
        for p in self.ctx.paras:
            if norm(p["text"]) not in long_sources:
                continue
            key = hashlib.sha1(p["text"].encode()).hexdigest()[:16]
            if verdicts.get(key) is False:
                continue
            items.append(self.item(
                "untranslated", key, "error", f"Left untranslated, identical to the source: “{snippet(p['text'])}”",
                p["id"], self.ctx.source_for_block(p["id"]),
            ))
        return items

    # --- consistency -----------------------------------------------------------------

    def consistency(self) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for p in self.ctx.paras:
            segs = self._sole_segments(p["id"])
            if len(segs) != 1:
                continue
            src = segs[0]["src"]
            if len(src.strip()) < 25 or sum(c.isalpha() for c in src) < 15:
                continue
            groups.setdefault(norm(src), []).append(p)
        items = []
        for src, paras in groups.items():
            variants: dict[str, dict] = {}
            for p in paras:
                variants.setdefault(norm(p["text"]), p)
            if len(variants) < 2:
                continue
            first, second = list(variants.values())[:2]
            items.append(self.item(
                "consistency", _key(src), "warning",
                f"The same source sentence is translated {len(variants)} ways: “{snippet(first['text'], 40)}” and "
                f"“{snippet(second['text'], 40)}”",
                second["id"], self.ctx.source_for_block(second["id"]),
            ))
        return items

    # --- formatting --------------------------------------------------------------------

    def formatting(self) -> list[dict]:
        ctx = self.ctx
        items = []
        t_marks = placeholders(ctx.translation)
        for seg in ctx.segments:
            for mark in placeholders(seg["src"]):
                if mark in t_marks:
                    t_marks.remove(mark)
                    continue
                items.append(self._located("placeholder", mark, "warning", f"Placeholder {mark} from the source isn't in the translation", seg))
        for p in ctx.paras:
            if not unbalanced(p["text"]):
                continue
            segs = [self.by_index[i] for i in self.alignment.get(p["id"], []) if i in self.by_index]
            if segs and unbalanced(" ".join(s["src"] for s in segs)):
                continue
            items.append(self.item(
                "brackets", _key(p["id"], p["text"]), "info", f"Unmatched bracket: “{snippet(p['text'])}”", p["id"],
                ctx.source_for_block(p["id"]),
            ))
        doubled = [p for p in ctx.paras if _DOUBLE_SPACE_RE.search(p["text"])]
        if doubled:
            n = len(doubled)
            items.append(self.item(
                "spacing", "double", "info", f"Double space between words in {n} paragraph{'s' if n > 1 else ''}", doubled[0]["id"],
            ))
        return items
