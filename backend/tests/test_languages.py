"""The added languages map the same way everywhere: picker code, English name and the names a detector writes."""
import re
from datetime import date
from pathlib import Path

import pytest

from app.services import cert_locale, tm_keys
from app.services.ai_translation_service import LANGUAGE_NAMES, humanize_lang
from app.services.glossary_service import lang_key, language_name
from app.services.layout_translator import _NOTO_SCRIPT_FONTS, _is_rtl_language, _shape_rtl

ADDED = {
    "sr-RS": "sr", "hr-HR": "hr", "bs-BA": "bs", "sl-SI": "sl", "sk-SK": "sk", "lt-LT": "lt", "lv-LV": "lv",
    "et-EE": "et", "bg-BG": "bg", "mk-MK": "mk", "sq-AL": "sq", "is-IS": "is", "mt-MT": "mt", "ca-ES": "ca",
    "gl-ES": "gl", "eu-ES": "eu", "ka-GE": "ka", "hy-AM": "hy", "az-AZ": "az", "kk-KZ": "kk", "uz-UZ": "uz",
    "mn-MN": "mn", "fa-IR": "fa", "prs-AF": "prs", "ps-AF": "ps", "ur-PK": "ur", "ku": "ku", "ckb": "ckb",
    "bn-BD": "bn", "pa-IN": "pa", "gu-IN": "gu", "ta-IN": "ta", "ne-NP": "ne", "si-LK": "si", "ms-MY": "ms",
    "fil-PH": "fil", "my-MM": "my", "km-KH": "km", "sw-KE": "sw", "am-ET": "am", "ti-ER": "ti", "so-SO": "so",
    "af-ZA": "af", "yo-NG": "yo", "ig-NG": "ig", "ha-NG": "ha", "ht-HT": "ht",
}

FRONTEND_LIST = Path(__file__).resolve().parents[2] / "traqconverter-frontend" / "src" / "lib" / "languages.ts"


@pytest.mark.parametrize("code,base", ADDED.items())
def test_every_added_language_has_one_key(code, base):
    name = LANGUAGE_NAMES[code]
    assert humanize_lang(code) == name
    assert lang_key(code) == base
    assert lang_key(name) == base
    assert tm_keys.source_lang(code) == base
    assert tm_keys.source_lang(name) == base
    assert tm_keys.family(code) == tm_keys.family(name) == base
    assert cert_locale.language_code(code) == base
    assert cert_locale.language_code(name) == base


@pytest.mark.parametrize(
    "detected,base",
    [
        ("Farsi", "fa"), ("Persian", "fa"), ("Dari", "prs"), ("Pashtu", "ps"), ("Tagalog", "fil"),
        ("Filipino", "fil"), ("Bangla", "bn"), ("Sinhalese", "si"), ("Azeri", "az"), ("Kiswahili", "sw"),
        ("Kurdish", "ku"), ("Sorani", "ckb"), ("Kurdish (Sorani)", "ckb"), ("Central Kurdish", "ckb"),
        ("Haitian Creole", "ht"), ("Burmese", "my"), ("Khmer", "km"), ("Tigrinya", "ti"),
    ],
)
def test_names_a_document_profile_may_write(detected, base):
    assert lang_key(detected) == base
    assert tm_keys.source_lang(detected) == base
    assert cert_locale.language_code(detected) == base


def test_detected_dari_is_not_the_persian_target():
    # Dari and Persian are written alike but certified separately.
    assert tm_keys.family("Dari") != tm_keys.family("fa-IR")
    assert tm_keys.family("Farsi") == tm_keys.family("fa-IR")


def test_old_languages_keep_their_keys():
    assert lang_key("Portuguese (Brazilian)") == "pt"
    assert lang_key("Chinese (Traditional)") == "zh-tw"
    assert lang_key("English (UK)") == "en"
    assert language_name("it") == "Italian"
    assert cert_locale.language_code("English (UK)") == "en"


def test_certification_wording_for_added_languages():
    # Six certification languages exist; every other target falls back to an English page and separator.
    assert cert_locale.cert_language("sr-RS") == "en"
    assert cert_locale.cert_language("ckb") == "en"
    assert cert_locale.language_name("ka-GE", "it") == "Georgiano"
    assert cert_locale.language_name("prs-AF", "fr") == "Dari"
    assert cert_locale.language_name("ckb", "en") == "Sorani Kurdish"
    assert cert_locale.language_name("Kurdish (Sorani)", "de") == "Sorani-Kurdisch"
    assert cert_locale.relocalize("lituano", "de") == "Litauisch"
    assert cert_locale.format_date(date(2026, 10, 23), cert_locale.cert_language("am-ET")) == "23 October 2026"


@pytest.mark.parametrize("code", ["ar-SA", "he-IL", "fa-IR", "prs-AF", "ps-AF", "ur-PK", "ckb"])
def test_right_to_left_targets(code):
    assert _is_rtl_language(code)


@pytest.mark.parametrize("code", ["ku", "pa-IN", "bn-BD", "am-ET", "sr-RS", "ka-GE"])
def test_left_to_right_targets(code):
    assert not _is_rtl_language(code)


@pytest.mark.parametrize("code", ["ps-AF", "prs-AF", "ckb", "ur-PK"])
def test_arabic_script_targets_are_reshaped(code):
    pytest.importorskip("arabic_reshaper")
    # Joined letters come out as presentation forms, which the plain input has none of.
    shaped = _shape_rtl("سلام دوست", code)
    assert any(0xFB50 <= ord(c) <= 0xFEFF for c in shaped)


def test_new_scripts_have_a_pdf_font():
    for lang in ("bn", "ta", "ka", "hy", "am", "ti", "my", "km", "si", "ne", "pa", "gu", "ps", "prs", "ckb"):
        assert lang in _NOTO_SCRIPT_FONTS


def test_backend_images_install_the_noto_fonts():
    backend = Path(__file__).resolve().parents[1]
    assert "fonts-noto-core" in (backend / "Dockerfile").read_text()
    assert '"fonts-noto-core"' in (backend / "nixpacks.toml").read_text()


@pytest.mark.skipif(not FRONTEND_LIST.exists(), reason="frontend not checked out")
def test_the_picker_and_the_backend_list_the_same_languages():
    codes = set(re.findall(r'code: "([^"]+)"', FRONTEND_LIST.read_text()))
    codes.discard("auto")
    assert codes, "no codes found in languages.ts"
    assert codes <= set(LANGUAGE_NAMES), codes - set(LANGUAGE_NAMES)
