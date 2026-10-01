"""Pre-delivery checks that compare the source with the translation before the translator certifies it."""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.project import TranslationProject, is_dtp
from app.services import claude_params, source_map, source_pages
from app.services.claude_multiturn_rebuild import extract_number_tokens, missing_source_numbers
from app.services.glossary_service import fold_text, lang_key, language_name, project_source_language, term_in_text

logger = logging.getLogger(__name__)

CHECKS_VERSION = 2
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
MAX_SOURCE_CHARS = 14_000

_NUM_RE = re.compile(r"(?<![^\W\d_])\d(?:\d|[.,/\-](?=\d))*")
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(?=[A-Z0-9/.\-]*\d)(?=[A-Z0-9/.\-]*[A-Z])[A-Z0-9](?:[A-Z0-9]|[/.\-](?=[A-Z0-9]))+")
_DMY_RE = re.compile(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$")
_YMD_RE = re.compile(r"^(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})$")
_BRACKET_RE = re.compile(r"\[([^\[\]]{1,300})\]")
_ILLEGIBLE_RE = re.compile(
    r"illegib|illeggib|ilegib|illisib|unleserlich|ilegível|ilegivel|onleesbaar|nieczyteln|неразборчив", re.I
)
_MONTHS = {
    1: "january jan gennaio gen enero ene janvier janv januar jänner janeiro januari styczeń stycznia",
    2: "february feb febbraio febrero février févr februar fevereiro fev februari luty lutego",
    3: "march mar marzo mars märz março maart marzec marca",
    4: "april apr aprile abril avril avr kwiecień kwietnia",
    5: "may maggio mag mayo mai maio mei maj maja",
    6: "june jun giugno giu junio juin juni junho czerwiec czerwca",
    7: "july jul luglio lug julio juillet juil juli julho lipiec lipca",
    8: "august aug agosto ago août aout augustus sierpień sierpnia",
    9: "september sep sept settembre set septiembre septembre setembro wrzesień września",
    10: "october oct ottobre ott octubre octobre oktober outubro out październik października",
    11: "november nov novembre noviembre novembro listopad listopada",
    12: "december dec dicembre dic diciembre décembre déc dezember dezembro dez grudzień grudnia",
}
_MONTH_OF = {name: m for m, names in _MONTHS.items() for name in names.split()}
_TEXT_DATE_RES = (
    re.compile(r"(\d{1,2})(?:st|nd|rd|th|º|°|\.)?\s+(?:de\s+|of\s+)?([^\W\d_]{3,})\.?,?\s+(?:de\s+)?(\d{4})", re.I),
    re.compile(r"([^\W\d_]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I),
)
_NOTATION_KINDS = (
    ("revenue_stamp", ("revenue stamp", "duty stamp", "tax stamp", "fiscal stamp", "marca da bollo", "bollo", "timbre fiscal",
                       "timbre fiscal", "stempelmarke", "gebührenmarke", "selo fiscal", "znaczek skarbowy")),
    ("signature", ("signature", "signed", "firma", "firmato", "unterschrift", "signatur", "assinatura", "handtekening", "podpis")),
    ("stamp", ("stamp", "seal", "timbro", "sigillo", "sello", "timbre", "cachet", "sceau", "stempel", "siegel", "carimbo",
               "selo", "zegel", "pieczęć", "pieczec")),
    ("handwriting", ("handwrit", "manoscritt", "a mano", "manuscrit", "handschrift", "manuscrito", "odręczn")),
)


def _digits(text: str) -> str:
    return "".join(str(unicodedata.digit(c)) for c in text if c.isdigit())


def _item_id(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:12]


def _item(kind: str, key: str, severity: str, message: str, block_id=None, source=None, **extra) -> dict:
    out = {"id": _item_id(kind, key), "kind": kind, "severity": severity, "message": message}
    if block_id:
        out["block_id"] = block_id
    if source:
        out["source"] = source
    out.update(extra)
    return out


def _parse_date(token: str) -> Optional[tuple[int, int, int]]:
    m = _DMY_RE.match(token)
    if m:
        d, mo, y = (int(v) for v in m.groups())
    else:
        m = _YMD_RE.match(token)
        if not m:
            return None
        y, mo, d = (int(v) for v in m.groups())
    if y < 100:
        y += 2000 if y < 50 else 1900
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        if 1 <= mo <= 31 and 1 <= d <= 12:
            d, mo = mo, d
        else:
            return None
    return d, mo, y


def _translation_dates(text: str) -> tuple[dict, set]:
    """Full (d, m, y) dates in any format the translation uses, and (day, year) pairs of dates whose month isn't recognised."""
    full: dict[tuple, str] = {}
    partial: set[tuple] = set()
    for tok in _NUM_RE.findall(text):
        m = _DMY_RE.match(tok) or _YMD_RE.match(tok)
        if not m:
            continue
        if _YMD_RE.match(tok):
            y, a, b = (int(v) for v in m.groups())
        else:
            a, b, y = (int(v) for v in m.groups())
            if y < 100:
                y += 2000 if y < 50 else 1900
        full.setdefault((a, b, y), tok)
        full.setdefault((b, a, y), tok)
    folded = source_map.fold(text)
    for rx in _TEXT_DATE_RES:
        for m in rx.finditer(folded):
            g = m.groups()
            if g[0].isdigit():
                day, month, year = int(g[0]), g[1], int(g[2])
            else:
                month, day, year = g[0], int(g[1]), int(g[2])
            mo = _MONTH_OF.get(source_map.fold(month).rstrip("."))
            if mo:
                full.setdefault((day, mo, year), m.group(0))
            elif 1 <= day <= 31:
                partial.add((day, year))
    return full, partial


def _segment_for(segments: list[dict], needle: str, fold_match: bool = False) -> Optional[dict]:
    for s in segments:
        hay = s["src"]
        if (fold_match and term_in_text(needle, fold_text(hay))) or (not fold_match and needle in hay):
            return s
    return None


def _source_ref(seg: Optional[dict]) -> Optional[dict]:
    if seg and seg.get("bbox"):
        return {"page": seg["page"], "bbox": seg["bbox"]}
    return None


class _Ctx:
    def __init__(self, db, project, user, paras, smap, segments):
        self.db = db
        self.project = project
        self.user = user
        self.paras = [p for p in paras if not p["cert"]]
        self.cert_paras = [p for p in paras if p["cert"]]
        self.smap = smap
        self.blocks = smap.get("blocks") or {}
        self.segments = segments
        self.translation = "\n".join(p["text"] for p in self.paras)
        self.source_text = "\n".join(s["src"] for s in segments) or source_pages.text_layer(project)
        self.seg_to_block: dict[int, str] = {}
        for bid, e in self.blocks.items():
            for idx in e.get("segments") or []:
                self.seg_to_block.setdefault(idx, bid)
        self.text_of = {p["id"]: p["text"] for p in self.paras}

    def block_for(self, seg: Optional[dict]) -> Optional[str]:
        if not seg or "toks" not in seg:
            return None
        bid = self.seg_to_block.get(seg["index"])
        if bid in self.text_of:
            return bid
        # No mapped paragraph (e.g. a scan mapped by vision): take the paragraph sharing most of the segment's words.
        base = seg["base"]
        wb = source_map._w(base)
        best, best_score = None, 0.5
        for p in self.paras:
            score = source_map._w(source_map.tokens(p["text"]) & seg["toks"]) / wb if wb else 0
            if score > best_score:
                best, best_score = p["id"], score
        return best

    def ref_for(self, seg: Optional[dict], bid: Optional[str]) -> Optional[dict]:
        return _source_ref(seg) or (self.source_for_block(bid) if bid else None)

    def source_for_block(self, bid: str) -> Optional[dict]:
        e = self.blocks.get(bid)
        if e and e.get("page") is not None and e.get("bbox"):
            return {"page": e["page"], "bbox": e["bbox"]}
        return None


def check_numbers(ctx: _Ctx) -> list[dict]:
    items = []
    translation = ctx.translation
    exact = set(_NUM_RE.findall(translation))
    by_digits: dict[str, str] = {}
    for tok in exact:
        by_digits.setdefault(_digits(tok).lstrip("0") or "0", tok)
    stream = " ".join(_digits(t) for t in _NUM_RE.findall(translation))
    dates, partial = _translation_dates(translation)
    missing_runs, _ = missing_source_numbers(ctx.source_text, translation)
    missing_runs = set(missing_runs)
    seen = set()
    for seg in ctx.segments or [{"src": ctx.source_text, "index": -1, "bbox": None, "page": 0}]:
        for tok in _NUM_RE.findall(seg["src"]):
            if tok in seen:
                continue
            seen.add(tok)
            digits = _digits(tok)
            if len(digits) < 2 or tok in exact:
                continue
            core = digits.lstrip("0") or "0"
            bid = ctx.block_for(seg)
            ref = ctx.ref_for(seg, bid)
            date = _parse_date(tok)
            if date:
                if date in dates:
                    items.append(_item("date", tok, "info", f"Date {tok} is written as {dates[date]}", bid, ref))
                elif (date[0], date[2]) in partial:
                    items.append(_item("date", tok, "info", f"Date {tok} is written out; check the month", bid, ref))
                else:
                    items.append(_number_missing(ctx, "date", tok, f"Date {tok} from the source isn't in the translation", seg))
                continue
            if core in by_digits:
                items.append(_item("number", tok, "info", f"{tok} is formatted as {by_digits[core]}", bid, ref))
            elif len(core) >= 4 and core in stream.replace(" ", ""):
                items.append(_item("number", tok, "info", f"{tok} appears split or reformatted in the translation", bid, ref))
            elif not (extract_number_tokens(tok) & missing_runs):
                items.append(_item("number", tok, "info", f"{tok} appears only in parts in the translation", bid, ref))
            else:
                items.append(_number_missing(ctx, "number", tok, f"Number {tok} from the source isn't in the translation", seg))
    return items


def _number_missing(ctx: _Ctx, kind: str, tok: str, message: str, seg: dict) -> dict:
    bid = ctx.block_for(seg)
    ref = ctx.ref_for(seg, bid)
    if not bid:
        seg_toks = source_map.tokens(seg.get("src", "")) | source_map.tokens(seg.get("tgt", ""))
        near = [(len(seg_toks & source_map.tokens(p["text"])), p["id"]) for p in ctx.paras if _ILLEGIBLE_RE.search(p["text"])]
        near = [n for n in near if n[0] >= 2]
        if near:
            bid = max(near)[1]
    if bid and not ref:
        ref = ctx.source_for_block(bid)
    # The translator already flagged that spot as unreadable: point at it without blocking.
    if bid and _ILLEGIBLE_RE.search(ctx.text_of.get(bid, "")):
        return _item(kind, tok, "warning", f"The source may read {tok} where the translation says illegible", bid, ref)
    return _item(kind, tok, "error", message, bid, ref)


def check_codes(ctx: _Ctx) -> list[dict]:
    items = []
    stream = re.sub(r"[^A-Z0-9]", "", source_map.fold(ctx.translation).upper())
    seen = set()
    for seg in ctx.segments:
        for tok in _CODE_RE.findall(seg["src"]):
            norm = re.sub(r"[^A-Z0-9]", "", tok)
            if len(norm) < 5 or norm in seen or norm.isdigit():
                continue
            seen.add(norm)
            if norm not in stream:
                items.append(_number_missing(ctx, "code", tok, f"Code {tok} from the source isn't in the translation", seg))
    return items


NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "kind": {"type": "string", "enum": ["person", "place", "institution", "other"]},
                    "renderings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["source", "kind", "renderings"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["names"],
    "additionalProperties": False,
}

_NAMES_PROMPT = """List the proper nouns in this {src} document that a {tgt} translation must carry over: \
people's names, places (cities, provinces, countries, streets) and institutions or organisations. For each give \
"source" exactly as printed, its kind, and "renderings": every acceptable way it may appear in a {tgt} \
translation: the original spelling, a transliteration into the {tgt} script when the scripts differ, and the \
conventional {tgt} name of places and institutions when one exists (e.g. "Comune di Bari" -> "Municipality of \
Bari"). Skip generic words, document titles, job titles and anything inside codes.

DOCUMENT TEXT
{text}"""


def source_names(db: Session, project: TranslationProject, state, source_text: str) -> Optional[list[dict]]:
    """Proper nouns of the source with their acceptable renderings: one cheap call per source, cached."""
    key = hashlib.sha1(f"{project.file_path}|{lang_key(project.target_language)}|{source_text}".encode()).hexdigest()
    if state.names and state.names.get("key") == key:
        return state.names.get("names")
    api_key = claude_params.api_key()
    if not api_key or not source_text.strip():
        return None
    model = claude_params.CLASSIFIER_MODEL
    src = language_name(lang_key(project_source_language(project))) or "source-language"
    tgt = language_name(lang_key(project.target_language)) or project.target_language or "target-language"
    try:
        resp = claude_params.create_message(
            anthropic.Anthropic(api_key=api_key),
            model=model,
            max_tokens=3000,
            messages=[{"role": "user", "content": _NAMES_PROMPT.format(src=src, tgt=tgt, text=source_text[:MAX_SOURCE_CHARS])}],
            output_config={"format": {"type": "json_schema", "schema": NAMES_SCHEMA}},
            **claude_params.request_params(model, max_tokens=3000),
        )
        claude_params.log_usage("review_names", resp)
        if resp.stop_reason == "refusal":
            return None
        names = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}")).get("names") or []
    except Exception:
        logger.exception("Name listing failed (project=%s)", project.id)
        return None
    state.names = {"key": key, "names": names[:120]}
    return state.names["names"]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_]+", source_map.fold(text)) if len(w) >= 3]


def check_names(ctx: _Ctx, names: Optional[list[dict]]) -> list[dict]:
    items = []
    if not names:
        return items
    folded = source_map.fold(ctx.translation)
    t_words = set(_words(ctx.translation))
    for n in names:
        src = (n.get("source") or "").strip()
        if not src or len(src) > 120:
            continue
        kind = n.get("kind") or "other"
        accepted = [src] + [r for r in n.get("renderings") or [] if r and r.strip()]
        if any(term_in_text(source_map.fold(r), folded) for r in accepted):
            continue
        name_words = _words(src)
        if name_words and all(w in t_words for w in name_words):
            continue
        seg = _segment_for(ctx.segments, src, fold_match=True)
        bid = ctx.block_for(seg)
        ref = ctx.ref_for(seg, bid)
        close = []
        for w in name_words:
            if w in t_words:
                continue
            match = difflib.get_close_matches(w, t_words, n=1, cutoff=0.8)
            if match:
                close.append(match[0])
        if kind == "person":
            if close:
                items.append(_item("name", src, "warning", f"Name {src} is spelled differently ({', '.join(close)})", bid, ref))
            else:
                items.append(_item("name", src, "error", f"Name {src} isn't in the translation", bid, ref))
        elif kind == "place":
            items.append(_item("name", src, "warning", f"Place {src} isn't in the translation", bid, ref))
        elif kind == "institution":
            items.append(_item("name", src, "info", f"Check how {src} is rendered", bid, ref))
    return items


UNTRANSLATED_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "untranslated": {"type": "boolean"}},
                "required": ["id", "untranslated"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _untranslated_candidates(ctx: _Ctx) -> list[dict]:
    if lang_key(project_source_language(ctx.project)) == lang_key(ctx.project.target_language):
        return []
    vocab = set(_words(ctx.source_text))
    if not vocab:
        return []
    out = []
    for p in ctx.paras:
        words = _words(_BRACKET_RE.sub(" ", p["text"]))
        if len(words) < 4:
            continue
        if sum(w in vocab for w in words) / len(words) >= 0.7:
            out.append(p)
    return out


def check_untranslated(ctx: _Ctx, state) -> list[dict]:
    candidates = _untranslated_candidates(ctx)
    if not candidates:
        return []
    cache = dict(state.untranslated or {})
    key_of = {p["id"]: hashlib.sha1(p["text"].encode()).hexdigest()[:16] for p in candidates}
    unknown = [p for p in candidates if key_of[p["id"]] not in cache]
    confirmed_by_model = bool(unknown) and _confirm_untranslated(ctx, unknown, key_of, cache)
    if confirmed_by_model or not unknown:
        state.untranslated = dict(list(cache.items())[-400:])
    items = []
    for p in candidates:
        verdict = cache.get(key_of[p["id"]])
        if verdict is False:
            continue
        severity = "error" if verdict else "warning"
        snippet = " ".join(p["text"].split())[:60]
        items.append(_item("untranslated", key_of[p["id"]], severity, f"Still in the source language: “{snippet}”", p["id"], ctx.source_for_block(p["id"])))
    return items


def _confirm_untranslated(ctx: _Ctx, paras: list[dict], key_of: dict, cache: dict) -> bool:
    api_key = claude_params.api_key()
    if not api_key:
        return False
    src = language_name(lang_key(project_source_language(ctx.project))) or "the source language"
    tgt = language_name(lang_key(ctx.project.target_language)) or "the target language"
    listing = "\n".join(f"{p['id']}: {p['text'][:600]}" for p in paras[:40])
    prompt = (
        f"These paragraphs come from a translation from {src} into {tgt}. Mark each one untranslated when it is "
        f"still, fully or mostly, written in {src}. Names, addresses, codes and quoted titles kept in the original "
        f"are fine and do not count.\n\n{listing}"
    )
    model = claude_params.CLASSIFIER_MODEL
    try:
        resp = claude_params.create_message(
            anthropic.Anthropic(api_key=api_key),
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": UNTRANSLATED_SCHEMA}},
            **claude_params.request_params(model, max_tokens=1500),
        )
        claude_params.log_usage("review_untranslated", resp)
        if resp.stop_reason == "refusal":
            return False
        results = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}")).get("results") or []
    except Exception:
        logger.exception("Untranslated check failed (project=%s)", ctx.project.id)
        return False
    for r in results:
        if r.get("id") in key_of:
            cache[key_of[r["id"]]] = bool(r.get("untranslated"))
    return True


# Short function words and common document terms per language, for lines too short to detect a language from.
_LANG_WORDS = {
    "en": "the of and to in for with on by at from is are was this that an or not "
          "municipality certificate office registry birth born date name surname residence",
    "it": "il lo la le gli di del della dello dei delle degli che e è per con nel nella nei sul sulla dal dalla alla "
          "alle ai al un una uno ed sono questo questa "
          "comune provincia regione repubblica italiana certificato certificazione residenza nascita matrimonio morte "
          "ufficio anagrafe civile nato nata cittadinanza tribunale ministero prefettura questura sindaco cognome "
          "rilasciato rilasciata scadenza luogo atto estratto stato famiglia",
    "es": "el los las del que en para con por una uno es son este esta al "
          "ayuntamiento municipio certificado nacimiento matrimonio defunción registro oficina nacido nacida apellido "
          "fecha lugar domicilio",
    "fr": "le les du des que et est pour avec dans une sur au aux ce cette sont "
          "mairie commune certificat acte naissance mariage décès registre bureau né née nom prénom date lieu domicile",
    "de": "der die das den dem des und ist für mit von im auf ein eine einer zu nicht "
          "gemeinde stadt bescheinigung urkunde geburt geburtsurkunde ehe standesamt amt geboren name vorname datum ort",
    "pt": "o os as do da dos das que para com por em uma um é são este esta ao no na "
          "câmara município certidão certificado nascimento casamento óbito registo registro conservatória nascido "
          "nascida apelido data local",
}
_LANG_SETS = {lang: set(words.split()) for lang, words in _LANG_WORDS.items()}
_ADDRESS_RE = re.compile(
    r"^(via|viale|piazza|piazzale|corso|largo|vicolo|strada|contrada|loc\.?|località|calle|avenida|avda\.?|plaza|paseo|"
    r"rua|travessa|praça|rue|avenue|boulevard|place|chemin|straße|strasse|str\.|platz|weg|street|road|st\.)\s+\S.*\d",
    re.I,
)
_WORD_RE = re.compile(r"[^\W\d_]+")


def _norm(text: str) -> str:
    return " ".join(fold_text(text).split())


def _kept_on_purpose(ctx: _Ctx) -> tuple[list[str], set[str]]:
    """Approved glossary targets and the team's memory translations for this pair; text matching them is intentional."""
    from app.dependencies.feature_guard import project_has_feature
    from app.models.translation_memory import TranslationMemory
    from app.services import tm_keys
    from app.services.glossary_service import get_glossary

    terms: list[str] = []
    if project_has_feature(ctx.db, ctx.project, "glossaries"):
        rows = get_glossary(ctx.db, ctx.project.team_id, project_source_language(ctx.project), ctx.project.target_language)
        terms = sorted({g.target_term for g in rows if (g.target_term or "").strip()}, key=len, reverse=True)
    family = tm_keys.family(ctx.project.target_language)
    memory: set[str] = set()
    if family:
        rows = (
            ctx.db.query(TranslationMemory.translated_text, TranslationMemory.target_language)
            .filter(TranslationMemory.team_id == ctx.project.team_id, TranslationMemory.origin != "machine")
            .limit(5000)
            .all()
        )
        memory = {_norm(t) for t, lang in rows if tm_keys.family(lang) == family}
    return terms, memory


def _looks_untranslated(text: str, src: str, tgt: str, source_lines: set[str], name_words: set[str]) -> bool:
    from app.services import cert_locale

    words = _WORD_RE.findall(text)
    low = [w.lower() for w in words]
    src_only = _LANG_SETS[src] - _LANG_SETS.get(tgt, set())
    tgt_only = _LANG_SETS.get(tgt, set()) - _LANG_SETS[src]
    src_hits = [w for w in low if w in src_only and w not in name_words]
    tgt_hits = [w for w in low if w in tgt_only]
    if len(words) >= 8:
        detected = cert_locale.detect_language(text)
        if detected:
            return detected == src
        return len(src_hits) >= 3 and len(src_hits) >= 2 * len(tgt_hits)
    if tgt_hits:
        return False
    # A content word that isn't a name: lowercase in the text, or a known source-language term. ALL CAPS alone could be a name.
    content = [
        w for w, lw in zip(words, low)
        if len(w) >= 4 and lw not in name_words and lw not in _LANG_SETS.get(tgt, set())
        and (w.islower() or lw in _LANG_SETS[src])
    ]
    if not content:
        return False
    if any(w.lower() in _LANG_SETS[src] for w in content) and src_hits:
        return True
    return _norm(text) in source_lines


def check_possibly_untranslated(ctx: _Ctx, names: Optional[list[dict]]) -> list[dict]:
    """Lines the model check never sees (short headings, text not in the source) still in the source language."""
    src, tgt = lang_key(project_source_language(ctx.project)), lang_key(ctx.project.target_language)
    src, tgt = src.split("-")[0], tgt.split("-")[0]
    if not src or src == tgt or src not in _LANG_SETS:
        return []
    handled = {p["id"] for p in _untranslated_candidates(ctx)}
    terms, memory = _kept_on_purpose(ctx)
    # People and places stay as printed; institutions ("Comune di ...") are meant to be translated.
    name_words = {
        w.lower() for n in names or [] if n.get("kind") in ("person", "place") for w in _WORD_RE.findall(n.get("source") or "")
    }
    source_lines = {_norm(s["src"]) for s in ctx.segments if (s.get("src") or "").strip()}
    items = []
    for p in ctx.paras:
        if p["id"] in handled or _norm(p["text"]) in memory:
            continue
        text = _BRACKET_RE.sub(" ", p["text"]).strip()
        if not text or _ADDRESS_RE.match(text):
            continue
        for term in terms:
            text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", " ", text, flags=re.I)
        if not _looks_untranslated(text, src, tgt, source_lines, name_words):
            continue
        snippet = " ".join(p["text"].split())[:60]
        items.append(_item(
            "possibly_untranslated", hashlib.sha1(p["text"].encode()).hexdigest()[:16], "warning",
            f"Possibly not translated: “{snippet}”", p["id"], ctx.source_for_block(p["id"]),
        ))
    return items


def _notation_kind(note: str) -> Optional[str]:
    low = source_map.fold(note)
    for kind, words in _NOTATION_KINDS:
        if any(source_map.fold(w) in low for w in words):
            return kind
    return None


def check_notations(ctx: _Ctx) -> list[dict]:
    elements = [e for e in ctx.smap.get("elements") or [] if e.get("kind") != "handwriting" or e.get("text")]
    if not elements:
        elements = [
            {"kind": {"signature": "signature", "stamp": "stamp", "handwritten": "handwriting"}[s["placeholder"]],
             "page": s["page"], "bbox": s["bbox"], "text": "", "block_id": ""}
            for s in ctx.segments
            if s.get("placeholder") in ("signature", "stamp", "handwritten")
        ]
    notes_by_block: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for p in ctx.paras:
        for note in _BRACKET_RE.findall(p["text"]):
            kind = _notation_kind(note)
            notes_by_block.setdefault(p["id"], []).append(kind or "other")
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
    items = []
    for kind in ("revenue_stamp", "signature", "stamp", "handwriting"):
        of_kind = [e for e in elements if (e["kind"] if e["kind"] != "seal" else "stamp") == kind]
        if not of_kind:
            continue
        covered = [e for e in of_kind if e.get("block_id") in notes_by_block]
        uncovered = [e for e in of_kind if e not in covered]
        missing = len(of_kind) - max(counts.get(kind, 0), len(covered))
        label = {"revenue_stamp": "Revenue stamp", "signature": "Signature", "stamp": "Stamp or seal", "handwriting": "Handwritten note"}[kind]
        note = {"revenue_stamp": "[Revenue stamp: …]", "signature": "[Signature]", "stamp": "[Stamp: …]", "handwriting": "[Handwritten: …]"}[kind]
        for e in uncovered[:max(0, missing)]:
            text = f" ({e['text'][:60]})" if e.get("text") else ""
            key = f"{kind}:{e['page']}:{round(e['bbox'][0], 2) if e.get('bbox') else ''}:{round(e['bbox'][1], 2) if e.get('bbox') else ''}"
            items.append(_item(
                "notation", key, "warning", f"{label} in the source{text} has no {note} note", None,
                {"page": e["page"], "bbox": e["bbox"]} if e.get("bbox") else None,
            ))
    return items


def check_glossary(ctx: _Ctx) -> list[dict]:
    from app.services.learning import team_terms

    items = []
    folded = fold_text(ctx.translation)
    for g in team_terms(ctx.db, ctx.project, ctx.source_text):
        if term_in_text(g.target_term, folded):
            continue
        seg = _segment_for(ctx.segments, g.source_term, fold_match=True)
        items.append(_item(
            "glossary", f"{g.source_term}|{g.target_term}", "warning",
            f"Team term: {g.source_term} → {g.target_term} isn't used",
            ctx.block_for(seg), ctx.ref_for(seg, ctx.block_for(seg)), origin=g.origin,
        ))
    return items


def certifications_enabled(db: Session, user) -> bool:
    from app.core.plan_features import PLAN_FEATURES
    from app.dependencies.feature_guard import effective_plan

    if (user.role or "").upper() in ("ADMIN", "SUPER_ADMIN"):
        return True
    return bool(PLAN_FEATURES.get(effective_plan(db, user), {}).get("certifications"))


def check_certification(ctx: _Ctx, data: bytes, enabled: bool) -> list[dict]:
    if not enabled:
        return []
    from app.services import docx_certification

    fields = docx_certification.read_fields(data)
    if fields is None:
        return [_item("certification", "missing", "warning", "No certification page yet; Certify & deliver adds it")]
    labels = {"translator": "translator", "date": "date", "document": "document", "source_language": "source language", "target_language": "target language"}
    # A translator's own template may leave some of these fields out; only flag the ones it has.
    empty = [labels[k] for k in labels if k in fields and not (fields.get(k) or "").strip()]
    if not empty:
        return []
    first = ctx.cert_paras[0]["id"] if ctx.cert_paras else None
    return [_item("certification", "fields:" + ",".join(empty), "error", f"Certification page: fill in the {', '.join(empty)}", first)]


def check_uncertain(ctx: _Ctx) -> list[dict]:
    items = []
    for p in ctx.paras:
        e = ctx.blocks.get(p["id"]) or {}
        snippet = " ".join(p["text"].split())[:50]
        source = ctx.source_for_block(p["id"])
        if _ILLEGIBLE_RE.search(p["text"]):
            items.append(_item("uncertain", f"illegible:{p['id']}", "warning", f"Marked illegible: “{snippet}”. Check the original", p["id"], source))
            continue
        reading = e.get("reading")
        if reading in ("low", "medium") and e.get("page") is not None:
            reason = e.get("reason") or "hard to read in the original"
            items.append(_item(
                "uncertain", f"{reading}:{p['id']}", "warning" if reading == "low" else "info",
                f"Uncertain reading: {reason}", p["id"], source, reason=reason, reading=reading,
            ))
    return items


def glossary_signature(db: Session, project: TranslationProject) -> str:
    from app.dependencies.feature_guard import project_has_feature
    from app.services.glossary_service import get_glossary

    if not project_has_feature(db, project, "glossaries"):
        return ""
    try:
        rows = get_glossary(db, project.team_id, project_source_language(project), project.target_language)
    except Exception:
        return ""
    raw = "|".join(sorted(f"{g.id}:{g.source_term}:{g.target_term}:{g.origin}" for g in rows))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def compute(db: Session, project: TranslationProject, user, data: bytes, state, smap: dict) -> dict:
    info = source_pages.page_info(project)
    paras = source_map.document_paragraphs(data)
    segments = source_map.segment_boxes(db, project, info)
    ctx = _Ctx(db, project, user, paras, smap, segments)
    names = source_names(db, project, state, ctx.source_text)
    dtp = is_dtp(project)
    items: list[dict] = []
    for name, fn in (
        ("numbers", lambda: check_numbers(ctx)),
        ("codes", lambda: check_codes(ctx)),
        ("names", lambda: check_names(ctx, names)),
        ("untranslated", lambda: check_untranslated(ctx, state)),
        ("possibly_untranslated", lambda: [] if dtp else check_possibly_untranslated(ctx, names)),
        ("notations", lambda: check_notations(ctx)),
        # An editable copy has no glossary to follow and is never certified.
        ("glossary", lambda: [] if dtp else check_glossary(ctx)),
        ("certification", lambda: check_certification(ctx, data, not dtp and certifications_enabled(db, user))),
        ("uncertain", lambda: check_uncertain(ctx)),
    ):
        try:
            items.extend(fn())
        except Exception:
            logger.exception("Check %s failed (project=%s)", name, project.id)
    unique: dict[str, dict] = {}
    for it in items:
        unique.setdefault(it["id"], it)
    order = {p["id"]: i for i, p in enumerate(paras)}
    ordered = sorted(unique.values(), key=lambda i: (SEVERITY_ORDER[i["severity"]], order.get(i.get("block_id"), 10**6)))
    return {"items": ordered, "names_checked": names is not None}


def view(result: dict, dismissed: dict, version: int, pending: bool, checked_at: str) -> dict:
    items = [{**i, "dismissed": i["id"] in dismissed} for i in result["items"]]
    ready = not any(i["severity"] in ("error", "warning") and not i["dismissed"] for i in items)
    return {
        "ready": ready,
        "document_version": version,
        "items": items,
        "checked_at": checked_at,
        "pending": pending,
        "counts": {s: sum(1 for i in items if i["severity"] == s and not i["dismissed"]) for s in SEVERITY_ORDER},
    }


def run(db: Session, project: TranslationProject, user, data: bytes, smap: dict, refresh: bool = False) -> dict:
    """Checks for the current document version, cached until the version, the map or the glossary changes."""
    state = source_map.get_state(db, project)
    version = project.document_version or 0
    enabled = certifications_enabled(db, user)
    key = f"{CHECKS_VERSION}|{version}|{state.map_revision or 0}|{glossary_signature(db, project)}|{int(enabled)}"
    pending = smap.get("status") == "running"
    cached = state.checks or {}
    if not refresh and cached.get("key") == key:
        db.commit()
        return view(cached["result"], state.dismissed or {}, version, pending, cached["checked_at"])
    result = compute(db, project, user, data, state, smap)
    checked_at = datetime.utcnow().isoformat() + "Z"
    state.checks = {"key": key, "result": result, "checked_at": checked_at}
    state.updated_at = datetime.utcnow()
    db.commit()
    return view(result, state.dismissed or {}, version, pending, checked_at)


def dismiss(db: Session, project: TranslationProject, item_id: str, on: bool = True) -> dict:
    state = source_map.get_state(db, project, lock=True)
    dismissed = dict(state.dismissed or {})
    if on:
        dismissed[item_id] = project.document_version or 0
    else:
        dismissed.pop(item_id, None)
    state.dismissed = dismissed
    state.updated_at = datetime.utcnow()
    db.commit()
    return dismissed
