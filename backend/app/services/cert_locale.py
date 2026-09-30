"""Language names, dates and certification wording for the languages a certification page is written in."""
from __future__ import annotations

from datetime import date

CERT_LANGS = ("en", "it", "es", "fr", "de", "pt")

# Names of the languages the app translates between, as written in each certification language.
_NAMES: dict[str, tuple[str, str, str, str, str, str]] = {
    "en": ("English", "inglese", "inglés", "anglais", "Englisch", "inglês"),
    "fr": ("French", "francese", "francés", "français", "Französisch", "francês"),
    "es": ("Spanish", "spagnolo", "español", "espagnol", "Spanisch", "espanhol"),
    "pt": ("Portuguese", "portoghese", "portugués", "portugais", "Portugiesisch", "português"),
    "it": ("Italian", "italiano", "italiano", "italien", "Italienisch", "italiano"),
    "de": ("German", "tedesco", "alemán", "allemand", "Deutsch", "alemão"),
    "nl": ("Dutch", "olandese", "neerlandés", "néerlandais", "Niederländisch", "neerlandês"),
    "sv": ("Swedish", "svedese", "sueco", "suédois", "Schwedisch", "sueco"),
    "da": ("Danish", "danese", "danés", "danois", "Dänisch", "dinamarquês"),
    "no": ("Norwegian", "norvegese", "noruego", "norvégien", "Norwegisch", "norueguês"),
    "fi": ("Finnish", "finlandese", "finés", "finnois", "Finnisch", "finlandês"),
    "pl": ("Polish", "polacco", "polaco", "polonais", "Polnisch", "polaco"),
    "cs": ("Czech", "ceco", "checo", "tchèque", "Tschechisch", "checo"),
    "ro": ("Romanian", "rumeno", "rumano", "roumain", "Rumänisch", "romeno"),
    "hu": ("Hungarian", "ungherese", "húngaro", "hongrois", "Ungarisch", "húngaro"),
    "tr": ("Turkish", "turco", "turco", "turc", "Türkisch", "turco"),
    "vi": ("Vietnamese", "vietnamita", "vietnamita", "vietnamien", "Vietnamesisch", "vietnamita"),
    "id": ("Indonesian", "indonesiano", "indonesio", "indonésien", "Indonesisch", "indonésio"),
    "ja": ("Japanese", "giapponese", "japonés", "japonais", "Japanisch", "japonês"),
    "zh": ("Chinese", "cinese", "chino", "chinois", "Chinesisch", "chinês"),
    "ko": ("Korean", "coreano", "coreano", "coréen", "Koreanisch", "coreano"),
    "ru": ("Russian", "russo", "ruso", "russe", "Russisch", "russo"),
    "uk": ("Ukrainian", "ucraino", "ucraniano", "ukrainien", "Ukrainisch", "ucraniano"),
    "el": ("Greek", "greco", "griego", "grec", "Griechisch", "grego"),
    "ar": ("Arabic", "arabo", "árabe", "arabe", "Arabisch", "árabe"),
    "he": ("Hebrew", "ebraico", "hebreo", "hébreu", "Hebräisch", "hebraico"),
    "hi": ("Hindi", "hindi", "hindi", "hindi", "Hindi", "hindi"),
    "th": ("Thai", "thailandese", "tailandés", "thaï", "Thailändisch", "tailandês"),
    "sq": ("Albanian", "albanese", "albanés", "albanais", "Albanisch", "albanês"),
    "bg": ("Bulgarian", "bulgaro", "búlgaro", "bulgare", "Bulgarisch", "búlgaro"),
    "hr": ("Croatian", "croato", "croata", "croate", "Kroatisch", "croata"),
    "sr": ("Serbian", "serbo", "serbio", "serbe", "Serbisch", "sérvio"),
    "sk": ("Slovak", "slovacco", "eslovaco", "slovaque", "Slowakisch", "eslovaco"),
    "sl": ("Slovenian", "sloveno", "esloveno", "slovène", "Slowenisch", "esloveno"),
    "fa": ("Persian", "persiano", "persa", "persan", "Persisch", "persa"),
    "ur": ("Urdu", "urdu", "urdu", "ourdou", "Urdu", "urdu"),
    "bn": ("Bengali", "bengalese", "bengalí", "bengali", "Bengalisch", "bengali"),
}

_MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "it": ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"),
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"),
    "pt": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"),
}

# Word date-picker display formats matching format_date below.
DATE_PATTERNS = {
    "en": "d MMMM yyyy",
    "it": "d MMMM yyyy",
    "es": "d' de 'MMMM' de 'yyyy",
    "fr": "d MMMM yyyy",
    "de": "d. MMMM yyyy",
    "pt": "d' de 'MMMM' de 'yyyy",
}

LOCALE_IDS = {"en": "en-GB", "it": "it-IT", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "pt": "pt-PT"}

TEXT = {
    "en": {
        "title": "CERTIFIED TRANSLATION",
        "statement": "I, {translator}, a professional translator, certify that the attached document is a true, accurate and complete translation of the original, to the best of my knowledge and ability.",
        "document": "Document",
        "source_language": "Source language",
        "target_language": "Target language",
        "pages": "Pages",
        "date": "Date",
        "signature": "Signature",
    },
    "it": {
        "title": "TRADUZIONE CERTIFICATA",
        "statement": "Il/La sottoscritto/a {translator}, traduttore/traduttrice professionista, certifica che il documento allegato è una traduzione fedele, accurata e completa dell'originale, al meglio delle proprie conoscenze e capacità.",
        "document": "Documento",
        "source_language": "Lingua di partenza",
        "target_language": "Lingua di arrivo",
        "pages": "Pagine",
        "date": "Data",
        "signature": "Firma",
    },
    "es": {
        "title": "TRADUCCIÓN CERTIFICADA",
        "statement": "Yo, {translator}, traductor/a profesional, certifico que el documento adjunto es una traducción fiel, exacta y completa del original, según mi leal saber y entender.",
        "document": "Documento",
        "source_language": "Idioma de origen",
        "target_language": "Idioma de destino",
        "pages": "Páginas",
        "date": "Fecha",
        "signature": "Firma",
    },
    "fr": {
        "title": "TRADUCTION CERTIFIÉE",
        "statement": "Je soussigné(e), {translator}, traducteur/traductrice professionnel(le), certifie que le document ci-joint est une traduction fidèle, exacte et complète de l'original, au mieux de mes connaissances et de mes capacités.",
        "document": "Document",
        "source_language": "Langue source",
        "target_language": "Langue cible",
        "pages": "Pages",
        "date": "Date",
        "signature": "Signature",
    },
    "de": {
        "title": "BEGLAUBIGTE ÜBERSETZUNG",
        "statement": "Ich, {translator}, professionelle(r) Übersetzer(in), bestätige, dass das beigefügte Dokument eine getreue, genaue und vollständige Übersetzung des Originals ist, nach bestem Wissen und Gewissen.",
        "document": "Dokument",
        "source_language": "Ausgangssprache",
        "target_language": "Zielsprache",
        "pages": "Seiten",
        "date": "Datum",
        "signature": "Unterschrift",
    },
    "pt": {
        "title": "TRADUÇÃO CERTIFICADA",
        "statement": "Eu, {translator}, tradutor(a) profissional, certifico que o documento anexo é uma tradução fiel, exata e completa do original, de acordo com o meu melhor conhecimento e capacidade.",
        "document": "Documento",
        "source_language": "Língua de partida",
        "target_language": "Língua de chegada",
        "pages": "Páginas",
        "date": "Data",
        "signature": "Assinatura",
    },
}

# Heading of the page that separates a delivery PDF's translation from the copy of the original.
ORIGINAL_COPY = {
    "en": "Copy of the original document",
    "it": "Copia del documento originale",
    "es": "Copia del documento original",
    "fr": "Copie du document original",
    "de": "Kopie des Originaldokuments",
    "pt": "Cópia do documento original",
}

_BY_ENGLISH_NAME = {names[0].lower(): code for code, names in _NAMES.items()}


def language_code(value: str | None) -> str:
    """'it-IT', 'it', 'Italian' or 'English (UK)' -> 'it' / 'en'; '' when unknown or auto-detect."""
    raw = (value or "").strip()
    if not raw or raw.lower() == "auto":
        return ""
    base = raw.split("-")[0].split("_")[0].lower()
    if base in _NAMES:
        return base
    name = raw.split("(")[0].strip().lower()
    return _BY_ENGLISH_NAME.get(name, "")


def cert_language(target_language: str | None) -> str:
    code = language_code(target_language)
    return code if code in CERT_LANGS else "en"


def language_name(value: str | None, lang: str) -> str:
    code = language_code(value)
    if not code:
        raw = (value or "").strip()
        return "" if raw.lower() == "auto" else raw
    name = _NAMES[code][CERT_LANGS.index(lang)]
    return name[:1].upper() + name[1:]


_BY_ANY_NAME = {name.lower(): code for code, names in _NAMES.items() for name in names}


def relocalize(value: str, lang: str) -> str:
    """A language name written in any certification language ('inglese') re-written in `lang`; other text as is."""
    code = language_code(value) or _BY_ANY_NAME.get((value or "").strip().lower(), "")
    return language_name(code, lang) if code else value


def format_date(d: date, lang: str) -> str:
    month = _MONTHS[lang][d.month - 1]
    if lang in ("es", "pt"):
        return f"{d.day} de {month} de {d.year}"
    if lang == "de":
        return f"{d.day}. {month} {d.year}"
    return f"{d.day} {month} {d.year}"


_FUNCTION_WORDS = {
    "en": {"the", "of", "and", "that", "this", "is", "to", "in", "translation", "certify", "hereby", "from", "into"},
    "it": {"il", "la", "di", "del", "della", "che", "e", "è", "traduzione", "dichiaro", "sottoscritto", "dal", "al", "conforme"},
    "es": {"el", "la", "de", "del", "que", "y", "es", "traducción", "certifico", "suscrito", "fiel", "al", "los"},
    "fr": {"le", "la", "de", "du", "des", "que", "et", "est", "traduction", "certifie", "soussigné", "conforme", "au"},
    "de": {"der", "die", "das", "und", "ist", "dass", "übersetzung", "bestätige", "hiermit", "von", "aus", "ins"},
    "pt": {"o", "a", "de", "do", "da", "que", "e", "é", "tradução", "certifico", "abaixo", "fiel", "para"},
}


def detect_language(text: str) -> str | None:
    """The certification language a text is written in, from its function words; None when unclear."""
    import re

    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    if len(words) < 8:
        return None
    scores = {lang: sum(1 for w in words if w in vocab) for lang, vocab in _FUNCTION_WORDS.items()}
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 3 or ranked[0] < 1.4 * ranked[1]:
        return None
    return best
