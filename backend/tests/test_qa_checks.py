import io
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import fitz
import httpx2
import pytest
from docx import Document

from app.models.ai_usage import AiUsage
from app.models.credit import CreditTransaction
from app.models.project import ProjectStatus, TranslationProject
from app.models.translation_segment import TranslationSegment
from app.services import ai_allowance, ai_usage, claude_params, deep_check, docx_blocks, document_editor, qa_checks, review_checks, source_map

IBAN = "IT60 X054 2811 1010 0000 0123 456"


def _docx(paras) -> bytes:
    doc = Document()
    for text in paras:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _pdf(lines) -> tuple[bytes, list[dict]]:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    layouts = []
    for i, src in enumerate(lines):
        y = 60 + i * 22
        page.insert_text((40, y), src, fontsize=8)
        layouts.append({"kind": "pdf_line", "page": 0, "bbox": [40, y - 8, 40 + 4 * len(src), y + 2]})
    data = doc.tobytes()
    doc.close()
    return data, layouts


@pytest.fixture(autouse=True)
def page_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_PAGE_CACHE", str(tmp_path / "pages"))


@pytest.fixture()
def model(monkeypatch):
    """No real model calls: names and untranslated verdicts come back empty unless a test sets them."""
    def all_translated(kwargs):
        rows = [line.split(": ", 1)[0] for line in kwargs["messages"][0]["content"].split("\n") if line.startswith("_b")]
        return {"results": [{"id": b, "untranslated": False} for b in rows]}

    answers = {"names": {"names": []}, "untranslated": all_translated}

    def fake(client, **kwargs):
        schema = kwargs["output_config"]["format"]["schema"]
        kind = "names" if schema is review_checks.NAMES_SCHEMA else "untranslated" if schema is review_checks.UNTRANSLATED_SCHEMA else "vision"
        body = answers.get(kind) or {"paragraphs": [], "elements": []}
        if callable(body):
            body = body(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5), model=kwargs["model"],
        )

    monkeypatch.setattr(claude_params, "create_message", fake)
    monkeypatch.setattr(claude_params, "api_key", lambda: "test-key")
    return answers


@pytest.fixture()
def qa_project(db, storage, make_user):
    """pairs: (source line, segment translation); translation: the delivered document's paragraphs."""

    def _make(pairs, translation=None, src="Italian", tgt="English", plan="BASIC", pages=1, credits=100, owner=None,
              authored=True, mode=None, used=0):
        owner = owner or make_user(plan=plan, credits=credits)
        data, layouts = _pdf([s for s, _ in pairs])
        key = f"uploads/{uuid.uuid4()}_source.pdf"
        storage["objects"][key] = data
        doc_key = f"uploads/{uuid.uuid4()}_authored.docx"
        storage["objects"][doc_key] = _docx(translation if translation is not None else [t for _, t in pairs])
        project = TranslationProject(
            user_id=owner["user"].id, team_id=owner["team"].id, file_name="source.pdf", file_path=key,
            page_count=pages, credits_used=pages, status=ProjectStatus.COMPLETED, source_language=src,
            target_language=tgt, model="claude-sonnet-4-6", authored_docx_s3_key=doc_key if authored else doc_key,
            ai_edits_used=used,
        )
        if mode:
            project.mode = mode
        db.add(project)
        db.flush()
        for i, ((s, t), layout) in enumerate(zip(pairs, layouts)):
            db.add(TranslationSegment(project_id=project.id, segment_index=i, source_text=s, translated_text=t, layout_meta=layout))
        db.commit()
        if not authored:
            project.authored_docx_s3_key = None
            db.commit()
        return owner, project

    return _make


def _checks(client, owner, project, refresh=False):
    r = client.get(f"/projects/{project.id}/checks" + ("?refresh=1" if refresh else ""), headers=owner["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _by_kind(result, kind):
    return [i for i in result["items"] if i["kind"] == kind]


def _messages(result, severity=None):
    return [i["message"] for i in result["items"] if severity is None or i["severity"] == severity]


def _issues(result):
    return [(i["kind"], i["message"]) for i in result["items"] if i["severity"] in ("error", "warning")]


# --- number parsing ------------------------------------------------------------


@pytest.mark.parametrize("tok,comma,value", [
    ("1.234,56", True, "1234.56"),
    ("1,234.56", False, "1234.56"),
    ("1.500", True, "1500"),
    ("1.500", False, "1.5"),
    ("12,5", True, "12.5"),
    ("12,5", False, "12.5"),
    ("1.000.000", True, "1000000"),
    ("2011", True, "2011"),
])
def test_numbers_parse_with_the_language_separators(tok, comma, value):
    assert qa_checks.parse_number(tok, comma) == Decimal(value).normalize()


def test_dates_and_ranges_are_not_numbers():
    assert qa_checks.parse_number("12/07/2011", True) is None
    assert qa_checks.parse_number("2010-2011", False) is None


def test_kept_and_misread_formats():
    assert qa_checks.misread_in_target("1.500", "de", "en")
    assert not qa_checks.misread_in_target("1.000,00", "it", "en")
    assert qa_checks.kept_source_format("1.000,00", "it", "en")
    assert qa_checks.kept_source_format("12,5", "de", "en")
    assert not qa_checks.kept_source_format("1,000.00", "it", "en")
    assert not qa_checks.kept_source_format("1.000,00", "it", "de")
    assert not qa_checks.kept_source_format("5582", "it", "en")


def test_page_numbers_and_list_markers_are_left_out_of_the_number_check():
    assert qa_checks.numbers_text("Pagina 1 di 3") .strip() == ""
    assert qa_checks.numbers_text("- 12 -") == ""
    assert qa_checks.numbers_text("12/34") == ""
    assert "12" not in qa_checks.numbers_text("12) Il venditore consegna")
    assert "12" in qa_checks.numbers_text("12. März 2020 in Berlin")
    assert "5582" in qa_checks.numbers_text("Protocollo 5582, pag. 2")
    assert "2" not in qa_checks.numbers_text("Protocollo 5582, pag. 2").replace("5582", "")


def test_iban_checksum():
    assert qa_checks.iban_valid(IBAN)
    assert qa_checks.iban_valid("DE89 3704 0044 0532 0130 00")
    assert not qa_checks.iban_valid("IT60 X054 2811 1010 0000 0123 457")
    assert qa_checks.ibans(f"Bonifico su IBAN {IBAN}.") == [IBAN]


def test_brackets_ignore_list_enumerators():
    assert not qa_checks.unbalanced("a) the seller delivers")
    assert not qa_checks.unbalanced("3) [Stamp: Comune di Bari]")
    assert qa_checks.unbalanced("the seller (Mr Rossi delivers")


# --- dates: Italian to English ----------------------------------------------------


def test_italian_month_name_date_rendered_in_english_is_a_note(client, qa_project, model):
    owner, project = qa_project([("Nato a Roma il 12 luglio 2011", "Born in Rome on 12 July 2011")])
    result = _checks(client, owner, project)
    assert result["ready"], _issues(result)
    assert "Date 12 luglio 2011 is written as 12 July 2011" in _messages(result, "info")


def test_italian_date_with_a_changed_month_is_an_error(client, qa_project, model):
    owner, project = qa_project([("Nato a Roma il 12 luglio 2011", "Born in Rome on 12 June 2011")])
    result = _checks(client, owner, project)
    [item] = _by_kind(result, "date")
    assert item["severity"] == "error"
    assert item["message"] == "Date 12 luglio 2011 reads 12 June 2011 in the translation"
    assert item["block_id"] and item["source"]["page"] == 0


def test_numeric_date_reformatted_with_month_name_is_fine_but_a_changed_month_is_not(client, qa_project, model):
    owner, project = qa_project([("Data di emissione: 12/07/2011", "Date of issue: 12 July 2011")])
    assert _checks(client, owner, project)["ready"]
    owner, project = qa_project([("Data di emissione: 12/07/2011", "Date of issue: 12 June 2011")])
    [item] = _by_kind(_checks(client, owner, project), "date")
    assert item["severity"] == "error" and "reads 12 June 2011" in item["message"]


def test_us_order_numeric_date_is_accepted(client, qa_project, model):
    owner, project = qa_project([("Scadenza 25/12/2030", "Expiry 12/25/2030")], tgt="English (US)")
    assert _checks(client, owner, project)["ready"]


# --- numbers: German decimal commas ---------------------------------------------


def test_german_decimal_comma_converted_to_english_is_a_note(client, qa_project, model):
    owner, project = qa_project([("Gesamtbetrag: 1.234,56 EUR", "Total amount: EUR 1,234.56")], src="German")
    result = _checks(client, owner, project)
    assert result["ready"], _issues(result)
    assert "1.234,56 is formatted as 1,234.56" in _messages(result, "info")


def test_changed_digits_are_an_error(client, qa_project, model):
    owner, project = qa_project([("Gesamtbetrag: 1.234,56 EUR", "Total amount: EUR 1,234.65")], src="German")
    result = _checks(client, owner, project)
    assert "Number 1.234,56 from the source isn't in the translation" in _messages(result, "error")


def test_dropped_zero_decimals_match_by_value(client, qa_project, model):
    owner, project = qa_project([("Importo dovuto 1.000,00 euro", "Amount due 1,000 euros")])
    result = _checks(client, owner, project)
    assert result["ready"], _issues(result)
    assert "1.000,00 is formatted as 1,000" in _messages(result, "info")


def test_german_thousands_kept_in_english_would_be_misread(client, qa_project, model):
    owner, project = qa_project([("Gebühr: 1.500 Euro pro Jahr", "Fee: 1.500 euros per year")], src="German")
    result = _checks(client, owner, project)
    [item] = _by_kind(result, "number_format")
    assert item["severity"] == "warning" and "1.500" in item["message"]
    assert item["block_id"]


def test_page_numbers_dropped_by_the_layout_are_not_reported(client, qa_project, model):
    pairs = [("Certificato di residenza n. 5582", "Residence certificate no. 5582"), ("Pagina 1 di 12", "")]
    owner, project = qa_project(pairs, translation=["Residence certificate no. 5582"])
    result = _checks(client, owner, project)
    assert not [m for m in _messages(result) if "12" in m], result["items"]


# --- identifiers ------------------------------------------------------------------


def test_iban_copied_exactly_passes_and_a_changed_digit_is_an_error(client, qa_project, model):
    owner, project = qa_project([(f"Accredito su IBAN {IBAN}", f"Credit to IBAN {IBAN}")])
    result = _checks(client, owner, project)
    assert not _by_kind(result, "identifier") and result["ready"], _issues(result)

    wrong = IBAN.replace("0123 456", "0132 456")
    owner, project = qa_project([(f"Accredito su IBAN {IBAN}", f"Credit to IBAN {wrong}")])
    result = _checks(client, owner, project)
    [item] = _by_kind(result, "identifier")
    assert item["severity"] == "error" and item["message"].startswith(f"IBAN {IBAN}")
    # The IBAN's digit groups are not reported again as numbers.
    assert not [i for i in result["items"] if i["kind"] == "number" and i["severity"] == "error"]


def test_iban_without_spaces_in_the_translation_is_the_same_iban(client, qa_project, model):
    owner, project = qa_project([(f"IBAN {IBAN}", f"IBAN {IBAN.replace(' ', '')}")])
    assert not _by_kind(_checks(client, owner, project), "identifier")


def test_email_url_and_fiscal_code(client, qa_project, model):
    pairs = [
        ("Contatti: anagrafe@comune.bari.it, www.comune.bari.it", "Contacts: registry@comune.bari.it, comune.bari.it"),
        ("Codice fiscale RSSMRA80A01H501U", "Tax code RSSMRA80A01H501V"),
    ]
    result = _checks(client, *qa_project(pairs))
    messages = _messages(result)
    assert "Email anagrafe@comune.bari.it isn't copied exactly" in messages
    assert not [m for m in messages if m.startswith("Web address")]
    assert "Code RSSMRA80A01H501U from the source isn't in the translation" in _messages(result, "error")


# --- names ------------------------------------------------------------------------


def test_names_fall_back_to_capitalised_words_at_low_severity(client, qa_project, monkeypatch):
    monkeypatch.setattr(claude_params, "api_key", lambda: None)
    pairs = [("Il sottoscritto Mario Rossi dichiara", "The undersigned Marco Bianchi declares"),
             ("che Giulia Verdi risiede a Bari", "that Giulia Verdi lives in Bari")]
    result = _checks(client, *qa_project(pairs))
    names = _by_kind(result, "name")
    assert [n["message"] for n in names] == ["Name Mario Rossi may be missing (fine if transliterated or translated)"]
    assert names[0]["severity"] == "info"


def test_no_name_fallback_into_a_non_latin_script(client, qa_project, monkeypatch):
    monkeypatch.setattr(claude_params, "api_key", lambda: None)
    result = _checks(client, *qa_project([("Il sottoscritto Mario Rossi dichiara", "Нижеподписавшийся Марио Росси заявляет")], tgt="Russian"))
    assert not _by_kind(result, "name")


# --- missing, dropped and untranslated -------------------------------------------------


LONG = "Il presente certificato viene rilasciato su richiesta dell'interessato per uso amministrativo all'estero"
LONG_EN = "This certificate is issued at the request of the person concerned for administrative use abroad"


def test_dropped_source_passage_is_flagged_next_to_where_it_belongs(client, qa_project, model):
    pairs = [
        ("CERTIFICATO DI RESIDENZA", "CERTIFICATE OF RESIDENCE"),
        ("Si certifica che il signor Luca Bianchi risiede in via Roma", "It is certified that Mr Luca Bianchi resides in via Roma"),
        (LONG, LONG_EN),
        ("L'Ufficiale d'Anagrafe", "The Registrar"),
    ]
    translation = [pairs[0][1], pairs[1][1], pairs[3][1]]
    owner, project = qa_project(pairs, translation=translation)
    result = _checks(client, owner, project)
    [item] = _by_kind(result, "missing")
    assert item["severity"] == "warning" and "may be missing" in item["message"]
    ids = {p["text"]: p["id"] for p in source_map.document_paragraphs(_doc(client, owner, project))}
    assert item["block_id"] == ids[pairs[1][1]]
    assert item["source"]["page"] == 0


def test_empty_segment_translation_on_a_segment_built_document_is_an_error(client, db, qa_project, model):
    pairs = [("CERTIFICATO DI RESIDENZA", "CERTIFICATE OF RESIDENCE"), (LONG, "")]
    owner, project = qa_project(pairs, translation=["CERTIFICATE OF RESIDENCE"])
    ctx = review_checks.context(db, project, owner["user"], _doc(client, owner, project), {})
    qa = qa_checks.QA(ctx, review_checks._item)
    [item] = qa.missing_text(authored=False)
    assert item["severity"] == "error" and item["message"].startswith("No translation for")
    # An authored document was translated on its own, so an empty segment says nothing there.
    assert qa.missing_text(authored=True) == []


def test_much_shorter_paragraph_is_flagged(client, qa_project, model):
    owner, project = qa_project([(LONG, LONG_EN)], translation=["This certificate is issued"])
    [item] = _by_kind(_checks(client, owner, project), "short")
    assert item["severity"] == "warning" and "shorter than the source" in item["message"]


def test_legitimately_shorter_target_languages_are_not_flagged(client, qa_project, model):
    owner, project = qa_project([(LONG, "本证明应当事人要求签发，供国外行政使用")], tgt="Chinese")
    result = _checks(client, owner, project)
    assert not _by_kind(result, "short") and not _by_kind(result, "missing")


def test_long_sentence_left_in_the_source_language_is_an_error(client, qa_project, model):
    model["untranslated"] = {"results": []}
    owner, project = qa_project([("CERTIFICATO", "CERTIFICATE"), (LONG, LONG_EN)], translation=["CERTIFICATE", LONG])
    items = [i for i in _checks(client, owner, project)["items"] if i["kind"] == "untranslated"]
    assert len(items) == 1 and items[0]["severity"] == "error" and "identical to the source" in items[0]["message"]


def test_untranslated_verdict_from_the_model_overrides_the_copy_check(client, db, qa_project, model):
    import hashlib

    owner, project = qa_project([("CERTIFICATO", "CERTIFICATE"), (LONG, LONG_EN)], translation=["CERTIFICATE", LONG])
    state = source_map.get_state(db, project)
    state.untranslated = {hashlib.sha1(LONG.encode()).hexdigest()[:16]: False}
    db.commit()
    result = _checks(client, owner, project)
    assert not [i for i in result["items"] if i["kind"] == "untranslated"]


# --- consistency and formatting --------------------------------------------------------------


def test_same_source_sentence_translated_two_ways(client, qa_project, model):
    rep = "Il presente atto è esente da imposta di bollo"
    pairs = [(rep, "This deed is exempt from stamp duty"), ("Nota intermedia del registro", "Intermediate registry note"),
             (rep, "This deed is exempt from stamp duty")]
    translation = ["This deed is exempt from stamp duty", "Intermediate registry note", "This act is exempt from revenue stamp duty"]
    owner, project = qa_project(pairs, translation=translation)
    [item] = _by_kind(_checks(client, owner, project), "consistency")
    assert item["severity"] == "warning" and "2 ways" in item["message"]
    ids = {p["text"]: p["id"] for p in source_map.document_paragraphs(_doc(client, owner, project))}
    assert item["block_id"] == ids[translation[2]]


def test_consistent_repeats_are_not_flagged(client, qa_project, model):
    rep = "Il presente atto è esente da imposta di bollo"
    pairs = [(rep, "This deed is exempt from stamp duty"), (rep, "This deed is exempt from stamp duty")]
    assert not _by_kind(_checks(client, *qa_project(pairs)), "consistency")


def test_placeholder_bracket_and_double_space(client, qa_project, model):
    pairs = [("Gentile {{Nome}}, la pratica è chiusa", "Dear Sir, the file is closed"),
             ("Il venditore (Mario Rossi) consegna", "The seller (Mario Rossi delivers"),
             ("Il documento è valido", "The document  is valid")]
    result = _checks(client, *qa_project(pairs))
    assert "Placeholder {{Nome}} from the source isn't in the translation" in _messages(result, "warning")
    assert any(i["kind"] == "brackets" and i["severity"] == "info" for i in result["items"])
    assert any(i["kind"] == "spacing" and i["severity"] == "info" for i in result["items"])


# --- false-positive guard: a clean, realistic certificate -------------------------------------


def test_clean_italian_certificate_has_no_errors_or_warnings(client, qa_project, model):
    model["names"] = {"names": [
        {"source": "BIANCHI LUCA", "kind": "person", "renderings": ["BIANCHI LUCA"]},
        {"source": "Bari", "kind": "place", "renderings": ["Bari"]},
    ]}
    pairs = [
        ("COMUNE DI BARI", "MUNICIPALITY OF BARI"),
        ("CERTIFICATO DI RESIDENZA", "CERTIFICATE OF RESIDENCE"),
        ("1) Si certifica che BIANCHI LUCA, nato a Bari il 1° gennaio 1987,", "1) It is certified that BIANCHI LUCA, born in Bari on 1 January 1987,"),
        ("2) risiede in Via Roma 12, 70121 Bari (BA)", "2) resides at Via Roma 12, 70121 Bari (BA)"),
        ("Diritti di segreteria: 0,52 euro", "Administrative fee: EUR 0.52"),
        ("Rilasciato il 14/09/2026, protocollo n. 5582", "Issued on 14 September 2026, protocol no. 5582"),
        (f"Pagamento su IBAN {IBAN}", f"Payment to IBAN {IBAN}"),
        (LONG, LONG_EN),
        ("Pagina 1 di 1", "Page 1 of 1"),
    ]
    result = _checks(client, *qa_project(pairs))
    assert result["ready"], _issues(result)


def _doc(client, owner, project):
    r = client.get(f"/projects/{project.id}/document", headers=owner["headers"])
    assert r.status_code == 200, r.text
    return r.content


# --- AI deep check ---------------------------------------------------------------------------


CONTRACT = [
    ("CONTRATTO DI COMPRAVENDITA", "SALES CONTRACT"),
    ("Il venditore non è responsabile dei vizi occulti dell'immobile", "The seller is liable for hidden defects in the property"),
    ("Le spese notarili sono a carico dell'acquirente", "Notary fees are borne by the buyer"),
]


def _message_json(model_id, text, stop="end_turn"):
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": model_id,
        "content": [{"type": "text", "text": text}], "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 3000, "output_tokens": 800, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1500},
    }


@pytest.fixture()
def deep_model(monkeypatch, model):
    calls = []
    state = {"findings": [], "stop": "end_turn"}

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx2.Response(200, json=_message_json(body["model"], json.dumps({"findings": state["findings"]}), state["stop"]))

    real = anthropic.Anthropic(api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(deep_check.anthropic, "Anthropic", lambda **kw: real)
    # The deep check goes through the SDK for real, so the usage hook sees it.
    others = claude_params.create_message

    def create(client, **kw):
        if kw["output_config"]["format"]["schema"] is deep_check.SCHEMA:
            return client.messages.create(**kw)
        return others(client, **kw)

    monkeypatch.setattr(claude_params, "create_message", create)
    ai_usage.install_hooks()
    state["calls"] = calls
    return state


NEGATION = {
    "category": "negation", "severity": "error", "block_id": "_bdeadbeef",
    "source_quote": "Il venditore non è responsabile",
    "translation_quote": "The seller is liable",
    "explanation": "The source says the seller is not liable; the translation says the seller is liable.",
}
INVENTED = {
    "category": "amount", "severity": "error", "block_id": "",
    "source_quote": "prezzo di 250.000 euro", "translation_quote": "price of EUR 205,000",
    "explanation": "The price differs.",
}


def _deep(client, owner, project):
    return client.post(f"/projects/{project.id}/checks/deep", headers=owner["headers"])


def test_deep_check_returns_located_findings_and_drops_invented_quotes(client, db, qa_project, deep_model):
    deep_model["findings"] = [NEGATION, INVENTED]
    owner, project = qa_project(CONTRACT, pages=5)
    r = _deep(client, owner, project)
    assert r.status_code == 200, r.text
    out = r.json()
    meaning = _by_kind(out, "meaning")
    assert len(meaning) == 1, meaning
    item = meaning[0]
    ids = {p["text"]: p["id"] for p in source_map.document_paragraphs(_doc(client, owner, project))}
    assert item["block_id"] == ids[CONTRACT[1][1]]
    assert item["severity"] == "error" and item["message"].startswith("Negation flipped: ")
    assert item["quote_source"] == NEGATION["source_quote"]
    assert out["deep"]["checked_at"] and not out["deep"]["stale"]
    assert not out["ready"]

    [body] = deep_model["calls"]
    assert body["model"] == deep_check.MODEL == "claude-sonnet-5"
    assert body["output_config"]["format"]["schema"] == deep_check.SCHEMA
    assert body["output_config"]["effort"] == "medium"
    assert "SOURCE (Italian)" in body["messages"][0]["content"][0]["text"]
    assert "_b" in body["messages"][0]["content"][1]["text"]

    # Five pages at four pages per edit: two AI edits from the allowance, recorded in ai_usage.
    db.expire_all()
    assert db.get(TranslationProject, project.id).ai_edits_used == 2
    rows = db.query(AiUsage).filter(AiUsage.action == "deep_check").all()
    assert len(rows) == 1 and rows[0].project_id == project.id and rows[0].user_id == owner["user"].id
    assert rows[0].model == "claude-sonnet-5" and rows[0].usd > 0

    # The findings stay on the checks until the next deep check.
    again = _checks(client, owner, project, refresh=True)
    assert [i["id"] for i in _by_kind(again, "meaning")] == [item["id"]]
    assert again["deep_cost_edits"] == 2


def test_long_source_is_cached_for_rechecks(client, qa_project, deep_model):
    pairs = CONTRACT + [(f"Articolo {i}: {LONG}", f"Article {i}: {LONG_EN}") for i in range(1, 60)]
    owner, project = qa_project(pairs)
    assert _deep(client, owner, project).status_code == 200
    first = deep_model["calls"][0]["messages"][0]["content"][0]
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in deep_model["calls"][0]["messages"][0]["content"][1]


def test_fixed_finding_disappears_after_the_edit_and_dismiss_works(client, db, qa_project, deep_model):
    deep_model["findings"] = [NEGATION, {**NEGATION, "category": "parties", "source_quote": "a carico dell'acquirente",
                                         "translation_quote": "borne by the buyer", "severity": "warning",
                                         "explanation": "Check who pays."}]
    owner, project = qa_project(CONTRACT)
    out = _deep(client, owner, project).json()
    parties = next(i for i in _by_kind(out, "meaning") if "Parties" in i["message"])
    assert client.post(f"/projects/{project.id}/checks/{parties['id']}/dismiss", headers=owner["headers"]).status_code == 200

    data = _doc(client, owner, project)
    bid = next(p["id"] for p in source_map.document_paragraphs(data) if p["text"] == CONTRACT[1][1])
    new_data, _ = docx_blocks.apply_text_edits(data, [(bid, "The seller is not liable for hidden defects in the property")])
    db.expire_all()
    document_editor.save_version(db, db.get(TranslationProject, project.id), new_data, "test", None)
    db.commit()

    after = _checks(client, owner, project)
    meaning = _by_kind(after, "meaning")
    assert [i["id"] for i in meaning] == [parties["id"]]
    assert meaning[0]["dismissed"] and meaning[0]["stale"]
    assert after["deep"]["stale"]


def test_deep_check_out_of_allowance_without_credits_is_402_before_calling_claude(client, db, qa_project, deep_model):
    owner, project = qa_project(CONTRACT, credits=0, used=ai_allowance.included_edits(SimpleNamespace(page_count=1)))
    r = _deep(client, owner, project)
    assert r.status_code == 402
    assert deep_model["calls"] == []


def test_deep_check_past_the_allowance_pays_one_block(client, db, qa_project, deep_model):
    included = ai_allowance.included_edits(SimpleNamespace(page_count=1))
    owner, project = qa_project(CONTRACT, credits=10, used=included)
    assert _deep(client, owner, project).status_code == 200
    db.expire_all()
    charges = db.query(CreditTransaction).filter(CreditTransaction.reference_id == f"{project.id}:ai-edits:0").all()
    assert len(charges) == 1
    assert db.get(TranslationProject, project.id).ai_edits_used == included + 1


def test_failed_deep_check_is_not_counted(client, db, qa_project, deep_model):
    deep_model["stop"] = "refusal"
    owner, project = qa_project(CONTRACT)
    r = _deep(client, owner, project)
    assert r.status_code == 502 and "declined" in r.json()["detail"]
    db.expire_all()
    assert db.get(TranslationProject, project.id).ai_edits_used == 0


def test_deep_check_refuses_an_editable_copy_and_other_tenants(client, qa_project, deep_model, make_user):
    owner, project = qa_project(CONTRACT, mode="dtp")
    assert _deep(client, owner, project).status_code == 400
    owner, project = qa_project(CONTRACT)
    assert _deep(client, make_user(), project).status_code == 404
    assert deep_model["calls"] == []


# --- allowance accounting for multi-edit actions ---------------------------------------------------


def test_reserving_several_edits_across_a_block_boundary_pays_each_block_once(db, make_user, make_project):
    owner = make_user(credits=10)
    project = make_project(owner, pages=1)
    included = ai_allowance.included_edits(project)
    per_block = ai_allowance.edits_per_block()
    project.ai_edits_used = included - 1
    db.commit()
    ai_allowance.reserve_edit(db, project, owner["user"], count=per_block + 2)
    ai_allowance.count_edit(db, project, owner["user"], count=per_block + 2)
    db.commit()
    refs = sorted({r for (r,) in db.query(CreditTransaction.reference_id).filter(CreditTransaction.reference_id.like(f"{project.id}:ai-edits:%"))})
    assert refs == [f"{project.id}:ai-edits:0", f"{project.id}:ai-edits:1"]
    assert project.ai_edits_used == included + per_block + 1


def test_edits_per_deep_check_scale_with_pages():
    assert deep_check.edits_for(SimpleNamespace(page_count=1)) == 1
    assert deep_check.edits_for(SimpleNamespace(page_count=4)) == 1
    assert deep_check.edits_for(SimpleNamespace(page_count=5)) == 2
    assert deep_check.edits_for(SimpleNamespace(page_count=None)) == 1
