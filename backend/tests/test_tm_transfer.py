import csv
import io
import zipfile

import pytest
from lxml import etree

from app.models.glossary import Glossary
from app.models.translation_memory import TranslationMemory
from app.services import glossary_transfer, safe_xml, tm_keys, tm_transfer, tmx, xliff
from app.services import translation_memory_service as tm

# The parts of the TMX 1.4b DTD the export uses.
TMX14_DTD = """
<!ELEMENT tmx (header, body)>
<!ATTLIST tmx version CDATA #FIXED "1.4">
<!ELEMENT header (note|prop)*>
<!ATTLIST header creationtool CDATA #REQUIRED creationtoolversion CDATA #REQUIRED
  segtype (block|paragraph|sentence|phrase) #REQUIRED o-tmf CDATA #REQUIRED adminlang CDATA #REQUIRED
  srclang CDATA #REQUIRED datatype CDATA #REQUIRED creationdate CDATA #IMPLIED>
<!ELEMENT body (tu*)>
<!ELEMENT tu ((note|prop)*, tuv+)>
<!ATTLIST tu tuid CDATA #IMPLIED srclang CDATA #IMPLIED creationdate CDATA #IMPLIED changedate CDATA #IMPLIED>
<!ELEMENT tuv ((note|prop)*, seg)>
<!ATTLIST tuv xml:lang CDATA #REQUIRED>
<!ELEMENT seg (#PCDATA|bpt|ept|it|ph|hi|ut)*>
<!ELEMENT prop (#PCDATA)>
<!ATTLIST prop type CDATA #REQUIRED>
<!ELEMENT note (#PCDATA)>
"""
XML_LANG = safe_xml.XML_LANG


def _add(db, team_id, source, target, origin="approved", src="it", tgt="en-GB"):
    assert tm.upsert_entries(db, team_id, [{
        "source_language": src, "target_language": tgt, "source_text": source,
        "translated_text": target, "origin": origin,
    }]) == 1


def _rows(db, team_id):
    return {
        (r.source_language, r.target_language, r.source_text, r.translated_text, r.origin)
        for r in db.query(TranslationMemory).filter(TranslationMemory.team_id == team_id)
    }


def _upload(client, user, path, data, name="tm.tmx", **params):
    return client.post(path, headers=user["headers"], params=params, files={"file": (name, data, "application/octet-stream")})


def _seed(db, team_id):
    _add(db, team_id, "Stato Civile & <Anagrafe> \"x\"", "Civil Status & <Registry> 'y'")
    _add(db, team_id, "Comune", "Municipalité", "manual", tgt="fr")
    _add(db, team_id, "Ufficio", "Office", "import", tgt="en-GB")


# Languages

def test_cat_locale_fills_the_region_once():
    assert tm_keys.cat_locale("it") == "it-IT"
    assert tm_keys.cat_locale("en") == "en-GB" and tm_keys.cat_locale("en-US") == "en-US"
    assert tm_keys.cat_locale("pt-BR") == "pt-BR" and tm_keys.cat_locale("pt") == "pt-PT"
    assert tm_keys.cat_locale("zh-Hant") == "zh-TW" and tm_keys.cat_locale("zh") == "zh-CN"
    assert tm_keys.cat_locale("sr-Latn") == "sr-Latn-RS" and tm_keys.cat_locale("es-419") == "es-419"
    assert tm_keys.cat_locale("sw") == "sw"
    assert all(tm_keys.supported(x) for x in ("it-IT", "Italian", "EN_gb", "zh-Hant", "fil", "pt-BR"))
    assert not any(tm_keys.supported(x) for x in ("foo", "tlh", "x-klingon", "", "auto", "und"))


def test_glossary_language_names():
    assert glossary_transfer.stored_language("it-IT") == "Italian"
    assert glossary_transfer.stored_language("en-GB") == "English"
    assert glossary_transfer.stored_language("zh-TW") == "Chinese (Traditional)"
    assert glossary_transfer.export_code("English (UK)") == "en-GB"
    assert glossary_transfer.export_code("Italian") == "it"


def test_import_maps_languages_and_counts_unsupported(db, make_user):
    team = make_user()["team"].id
    counts = tm_transfer.import_pairs(db, team, [
        {"source_language": "it-IT", "target_language": "en-GB", "source_text": "Comune", "translated_text": "Town"},
        {"source_language": "IT", "target_language": "en_us", "source_text": "Comune", "translated_text": "City"},
        {"source_language": "x-klingon", "target_language": "en", "source_text": "a", "translated_text": "b"},
        {"source_language": "it", "target_language": "", "source_text": "a", "translated_text": "b"},
        {"source_language": "it", "target_language": "en", "source_text": " ", "translated_text": "b"},
        {"source_language": "it", "target_language": "en", "source_text": "x" * 1501, "translated_text": "b"},
    ])
    assert counts == {"imported": 2, "updated": 0, "duplicates": 0, "conflicts": 0, "unsupported_language": 2, "invalid": 2}
    assert _rows(db, team) == {("it", "en-GB", "Comune", "Town", "import"), ("it", "en-US", "Comune", "City", "import")}


# TMX export

def test_tmx_export_is_valid_tmx_14(client, db, make_user):
    owner = make_user()
    _seed(db, owner["team"].id)
    r = client.get("/tm/export", headers=owner["headers"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-tmx+xml")
    assert r.headers["content-disposition"] == 'attachment; filename="translation-memory.tmx"'
    root = etree.fromstring(r.content)
    assert etree.DTD(io.StringIO(TMX14_DTD)).validate(root), "export doesn't match the TMX 1.4 DTD"
    header = root.find("header")
    assert header.get("creationtool") == "OnlineDocTranslator" and header.get("srclang") == "*all*"
    assert (header.get("datatype"), header.get("segtype"), header.get("adminlang")) == ("plaintext", "sentence", "en-US")
    tus = root.findall("body/tu")
    assert len(tus) == 3
    for tu in tus:
        assert len(tu.get("creationdate")) == 16 and tu.get("creationdate").endswith("Z")
        assert [tuv.get(XML_LANG) for tuv in tu.findall("tuv")][0] == "it"
    assert b"&amp; &lt;Anagrafe&gt;" in r.content
    segs = {tuv.findtext("seg") for tuv in root.iter("tuv")}
    assert "Stato Civile & <Anagrafe> \"x\"" in segs and "Civil Status & <Registry> 'y'" in segs


def test_tmx_export_pair_filter_and_locales(client, db, make_user):
    owner = make_user()
    _seed(db, owner["team"].id)
    r = client.get("/tm/export", headers=owner["headers"], params={"source": "Italian", "target": "en-GB", "regions": True})
    root = etree.fromstring(r.content)
    assert root.find("header").get("srclang") == "it-IT"
    assert {tuv.get(XML_LANG) for tuv in root.iter("tuv")} == {"it-IT", "en-GB"}
    assert len(root.findall("body/tu")) == 2
    assert 'filename="translation-memory-it-IT-en-GB.tmx"' in r.headers["content-disposition"]
    empty = client.get("/tm/export", headers=owner["headers"], params={"source": "de", "target": "en"})
    assert empty.status_code == 404


def test_tmx_round_trip_gives_the_same_entries(client, db, make_user):
    owner, other = make_user(), make_user()
    _seed(db, owner["team"].id)
    body = client.get("/tm/export", headers=owner["headers"]).content
    r = _upload(client, other, "/tm/import", body)
    assert r.status_code == 200, r.text
    assert r.json()["format"] == "tmx" and r.json()["imported"] == 3 and r.json()["skipped"] == 0
    strip = {(s, t, a, b) for s, t, a, b, _ in _rows(db, owner["team"].id)}
    assert {(s, t, a, b) for s, t, a, b, _ in _rows(db, other["team"].id)} == strip
    assert {o for *_, o in _rows(db, other["team"].id)} == {"import"}


# XLIFF and CSV export

def test_xliff_12_export_and_round_trip(client, db, make_user):
    owner, other = make_user(), make_user()
    _seed(db, owner["team"].id)
    r = client.get("/tm/export", headers=owner["headers"], params={"format": "xliff", "source": "it", "target": "en-GB"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xliff+xml")
    root = etree.fromstring(r.content)
    ns = {"x": xliff.NS12}
    f = root.find("x:file", ns)
    assert (root.get("version"), f.get("source-language"), f.get("target-language")) == ("1.2", "it", "en-GB")
    units = root.findall(".//x:trans-unit", ns)
    assert len(units) == 2 and {u.find("x:target", ns).get("state") for u in units} == {"final"}
    assert _upload(client, other, "/tm/import", r.content, "tm.xlf").json()["imported"] == 2
    assert {(a, b) for _, _, a, b, _ in _rows(db, other["team"].id)} == {
        ("Stato Civile & <Anagrafe> \"x\"", "Civil Status & <Registry> 'y'"), ("Ufficio", "Office"),
    }


def test_xliff_all_pairs_is_a_zip_of_one_file_per_pair(client, db, make_user):
    owner, other = make_user(), make_user()
    _seed(db, owner["team"].id)
    r = client.get("/tm/export", headers=owner["headers"], params={"format": "xliff2", "regions": True})
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = sorted(z.namelist())
        assert names == ["translation-memory-it-IT-en-GB.xlf", "translation-memory-it-IT-fr-FR.xlf"]
        fr = etree.fromstring(z.read(names[1]))
        assert (fr.get("version"), fr.get("srcLang"), fr.get("trgLang")) == ("2.0", "it-IT", "fr-FR")
        assert _upload(client, other, "/tm/import", z.read(names[0]), "a.xlf").json()["imported"] == 2
    assert {(s, t) for s, t, *_ in _rows(db, other["team"].id)} == {("it", "en-GB")}


def test_csv_export(client, db, make_user):
    owner = make_user()
    _add(db, owner["team"].id, "=SOMMA(A1)", "-cmd|x", "approved")
    _add(db, owner["team"].id, "- elenco", "- list", "approved")
    r = client.get("/tm/export", headers=owner["headers"], params={"format": "csv", "regions": True})
    assert r.headers["content-type"].startswith("text/csv") and r.content.startswith("\ufeff".encode())
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["source_language", "target_language", "source_text", "target_text"]
    assert {tuple(x[:4]) for x in rows[1:]} == {("it-IT", "en-GB", "'=SOMMA(A1)", "'-cmd|x"), ("it-IT", "en-GB", "- elenco", "- list")}


# TMX import

def test_import_strips_inline_tags_and_counts_invalid_units(client, db, make_user):
    owner = make_user()
    data = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4"><header srclang="en-US" creationtool="SDL Language Platform" creationtoolversion="8.1" segtype="sentence" o-tmf="SDL TM8" adminlang="en-US" datatype="xml"/>
<body>
<tu><tuv xml:lang="en-US"><seg>Press <bpt i="1" type="bold">&lt;b&gt;</bpt>Save<ept i="1">&lt;/b&gt;</ept><ph x="2">{1}</ph> now</seg></tuv>
<tuv xml:lang="it-IT"><seg>Premi <hi type="b">Salva</hi> <it pos="begin">&lt;i&gt;</it>ora</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Only source</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Empty</seg></tuv><tuv xml:lang="it-IT"><seg> </seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Hello</seg></tuv><tuv xml:lang="tlh-x-klingon"><seg>nuqneH</seg></tuv></tu>
</body></tmx>""".encode()
    r = _upload(client, owner, "/tm/import", data)
    body = r.json()
    assert (body["units"], body["imported"], body["invalid"], body["unsupported_language"]) == (4, 1, 2, 1)
    assert _rows(db, owner["team"].id) == {("en", "it-IT", "Press Save now", "Premi Salva ora", "import")}


def test_duplicates_conflicts_and_replace(client, db, make_user):
    owner = make_user()
    team = owner["team"].id
    _add(db, team, "Comune", "Town (checked)", "manual", tgt="en")
    _add(db, team, "Provincia", "Province (AI)", "machine", tgt="en")
    _add(db, team, "Regione", "Region", "approved", tgt="en")

    def tmx_of(units):
        tus = "".join(
            f'<tu><tuv xml:lang="it"><seg>{s}</seg></tuv><tuv xml:lang="en"><seg>{t}</seg></tuv></tu>' for s, t in units
        )
        return f'<tmx version="1.4"><header srclang="it"/><body>{tus}</body></tmx>'.encode()

    data = tmx_of([("Comune", "Municipality"), ("Provincia", "Province"), ("Regione", " Region "),
                   ("Nuovo", "New"), ("Nuovo", "New again")])
    body = _upload(client, owner, "/tm/import", data).json()
    assert {k: body[k] for k in ("imported", "updated", "duplicates", "conflicts")} == {
        "imported": 1, "updated": 1, "duplicates": 2, "conflicts": 1,
    }
    db.expire_all()
    assert _rows(db, team) == {
        ("it", "en", "Comune", "Town (checked)", "manual"),
        ("it", "en", "Provincia", "Province", "import"),
        ("it", "en", "Regione", "Region", "approved"),
        ("it", "en", "Nuovo", "New", "import"),
    }
    again = _upload(client, owner, "/tm/import", data).json()
    assert again["imported"] == 0 and again["duplicates"] == 4 and again["conflicts"] == 1
    replaced = _upload(client, owner, "/tm/import", data, replace=True).json()
    assert replaced["updated"] == 1 and replaced["conflicts"] == 0
    db.expire_all()
    assert ("it", "en", "Comune", "Municipality", "import") in _rows(db, team)


# sdlxliff and XLIFF import

SDLXLIFF = b"""<?xml version="1.0" encoding="utf-8"?>
<xliff xmlns:sdl="http://sdl.com/FileTypes/SdlXliff/1.0" xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2" sdl:version="1.0">
<file original="C:\\docs\\cert.docx" datatype="x-sdlfilterframework2" source-language="it-IT" target-language="en-GB">
<header/>
<body><group><trans-unit id="1">
<source><g id="5">Ufficio Anagrafe.</g> Stato Civile.</source>
<seg-source><g id="5"><mrk mtype="seg" mid="1">Ufficio <x id="9"/>Anagrafe.</mrk></g> <mrk mtype="seg" mid="2">Stato Civile.</mrk></seg-source>
<target><g id="5"><mrk mtype="seg" mid="1">Registry <x id="9"/>Office.</mrk></g> <mrk mtype="seg" mid="2">Civil Status.</mrk></target>
<sdl:seg-defs><sdl:seg id="1" conf="ApprovedTranslation" origin="interactive"/><sdl:seg id="2" conf="Draft"/></sdl:seg-defs>
</trans-unit>
<trans-unit id="2" translate="no"><source>LOGO</source></trans-unit>
<trans-unit id="3">
<seg-source><mrk mtype="seg" mid="3">Comune di Bari</mrk></seg-source>
<target><mrk mtype="seg" mid="3">Municipality of Bari</mrk></target>
<sdl:seg-defs><sdl:seg id="3" conf="Translated"/></sdl:seg-defs>
</trans-unit></group></body></file></xliff>"""


def test_sdlxliff_import_reads_confirmed_segments_only(client, db, make_user):
    owner = make_user()
    body = _upload(client, owner, "/tm/import", SDLXLIFF, "cert.docx.sdlxliff").json()
    assert body["format"] == "sdlxliff"
    assert (body["units"], body["imported"], body["unconfirmed"]) == (3, 2, 1)
    assert _rows(db, owner["team"].id) == {
        ("it", "en-GB", "Ufficio Anagrafe.", "Registry Office.", "import"),
        ("it", "en-GB", "Comune di Bari", "Municipality of Bari", "import"),
    }


def test_plain_xliff_needs_a_confirmed_state():
    root = safe_xml.parse(b"""<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
<file source-language="en" target-language="de" datatype="plaintext" original="x"><body>
<trans-unit id="a"><source>Yes</source><target state="translated">Ja</target></trans-unit>
<trans-unit id="b"><source>No</source><target state="needs-review-translation">Nein</target></trans-unit>
<trans-unit id="c" approved="yes"><source>Hi <ph id="1">&lt;br/&gt;</ph>there</source><target>Hallo <ph id="1">&lt;br/&gt;</ph>da</target></trans-unit>
<trans-unit id="d"><source>Draft</source><target>Entwurf</target></trans-unit>
</body></file></xliff>""")
    parsed = xliff.parse_root(root)
    assert [(p["source_text"], p["translated_text"]) for p in parsed.pairs] == [("Yes", "Ja"), ("Hi there", "Hallo da")]
    assert parsed.unconfirmed == 2 and parsed.units == 4


# Hostile files

BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>
<ROOT><x>&lol3;</x></ROOT>"""
XXE = b"""<?xml version="1.0"?><!DOCTYPE ROOT [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><ROOT><x>&xxe;</x></ROOT>"""
PARAM = b"""<?xml version="1.0"?><!DOCTYPE ROOT [<!ENTITY % remote SYSTEM "http://127.0.0.1:1/evil.dtd"> %remote;]><ROOT/>"""


@pytest.mark.parametrize("root,path,name", [
    ("tmx", "/tm/import", "a.tmx"),
    ("xliff", "/tm/import", "a.xlf"),
    ("martif", "/glossary/import", "a.tbx"),
])
@pytest.mark.parametrize("payload", [BOMB, XXE, PARAM], ids=["billion-laughs", "xxe", "parameter-entity"])
def test_entity_payloads_are_rejected(client, make_user, root, path, name, payload):
    owner = make_user()
    data = payload.replace(b"ROOT", root.encode()).replace(b"lolz", root.encode())
    r = _upload(client, owner, path, data, name)
    assert r.status_code == 400 and "entities" in r.json()["detail"]
    utf16 = _upload(client, owner, path, data.decode().replace('version="1.0"', 'version="1.0" encoding="UTF-16"').encode("utf-16"), name)
    assert utf16.status_code == 400


def test_external_dtd_is_never_fetched(client, db, make_user, monkeypatch):
    import socket

    def no_network(*a, **kw):
        raise AssertionError("network access")

    monkeypatch.setattr(socket, "create_connection", no_network)
    owner = make_user()
    data = b"""<?xml version="1.0"?><!DOCTYPE tmx SYSTEM "http://127.0.0.1:1/tmx14.dtd">
<tmx version="1.4"><header srclang="it"/><body><tu><tuv xml:lang="it"><seg>Si</seg></tuv><tuv xml:lang="en"><seg>Yes</seg></tuv></tu></body></tmx>"""
    assert _upload(client, owner, "/tm/import", data).json()["imported"] == 1


def test_size_limits(client, make_user):
    owner = make_user()
    big = b"<tmx>" + b" " * (safe_xml.MAX_BYTES + 1) + b"</tmx>"
    r = _upload(client, owner, "/tm/import", big)
    assert r.status_code == 413 and "20 MB" in r.json()["detail"]
    assert _upload(client, owner, "/glossary/import", big, "g.tbx").status_code == 413
    assert _upload(client, owner, "/tm/import", b"<html/>").status_code == 400


# Who may move the memory

def test_teams_never_reach_each_other(client, db, make_user):
    owner, other = make_user(), make_user()
    _seed(db, owner["team"].id)
    db.add(Glossary(team_id=owner["team"].id, source_language="Italian", target_language="English",
                    source_term="Comune", target_term="Municipality"))
    db.commit()
    assert client.get("/tm/export", headers=other["headers"]).status_code == 404
    assert client.get("/glossary/export", headers=other["headers"]).status_code == 404
    data = client.get("/tm/export", headers=owner["headers"]).content
    _upload(client, other, "/tm/import", data)
    _upload(client, other, "/glossary/import", b"source_language,target_language,source_term,target_term\nit,en,Comune,Town\n", "g.csv")
    assert len(_rows(db, owner["team"].id)) == 3
    assert db.query(Glossary).filter(Glossary.team_id == owner["team"].id).count() == 1
    assert db.query(Glossary).filter(Glossary.team_id == other["team"].id).count() == 1


def test_only_leads_move_the_memory(client, db, make_user):
    owner = make_user()
    member = make_user(team=owner["team"])
    pm = make_user(team=owner["team"], role="PM")
    _seed(db, owner["team"].id)
    data = client.get("/tm/export", headers=owner["headers"]).content
    assert client.get("/tm/export", headers=member["headers"]).status_code == 403
    assert _upload(client, member, "/tm/import", data).status_code == 403
    assert client.get("/glossary/export", headers=member["headers"]).status_code == 403
    assert _upload(client, member, "/glossary/import", b"it,en\na,b\n", "g.csv").status_code == 403
    assert client.get("/tm/summary", headers=member["headers"]).json()["can_transfer"] is False
    assert client.get("/glossary/access", headers=member["headers"]).json() == {"can_transfer": False}
    assert client.get("/tm/export", headers=pm["headers"]).status_code == 200
    assert client.get("/tm/summary", headers=pm["headers"]).json()["can_transfer"] is True
    assert client.get("/glossary/access", headers=owner["headers"]).json() == {"can_transfer": True}


@pytest.mark.parametrize("plan", ["TRIAL", "BASIC"])
def test_transfer_needs_pro(client, make_user, plan):
    user = make_user(plan=plan)
    assert client.get("/tm/export", headers=user["headers"]).status_code == 403
    assert _upload(client, user, "/tm/import", b"<tmx/>").status_code == 403
    assert client.get("/glossary/export", headers=user["headers"]).status_code == 403
    assert _upload(client, user, "/glossary/import", b"it,en\n", "g.csv").status_code == 403
    assert client.get("/glossary/access", headers=user["headers"]).status_code == 403


# Glossary

def _terms(db, team_id):
    return {
        (g.source_language, g.target_language, g.source_term, g.target_term, g.notes, g.origin)
        for g in db.query(Glossary).filter(Glossary.team_id == team_id)
    }


def _term(db, team_id, src, tgt, origin="manual", notes=None, sl="Italian", tl="English"):
    db.add(Glossary(team_id=team_id, source_language=sl, target_language=tl, source_term=src, target_term=tgt,
                    notes=notes, origin=origin, usage_count=0))
    db.commit()


@pytest.mark.parametrize("fmt", ["csv", "tbx"])
def test_glossary_round_trip(client, db, make_user, fmt):
    owner, other = make_user(), make_user()
    team = owner["team"].id
    _term(db, team, "Comune", "Municipality", notes="Not 'town' & never <city>")
    _term(db, team, "=Codice", "+Tax code", sl="Italian", tl="English (UK)")
    _term(db, team, "Prefettura", "Préfecture", tl="French")
    _term(db, team, "Rifiutato", "Rejected", origin="rejected")
    r = client.get("/glossary/export", headers=owner["headers"], params={"format": fmt})
    assert r.status_code == 200 and f'filename="glossary.{fmt}"' in r.headers["content-disposition"]
    if fmt == "tbx":
        root = etree.fromstring(r.content)
        assert root.tag == "martif" and root.get("type") == "TBX-Basic"
        entries = root.findall("text/body/termEntry")
        assert len(entries) == 3
        assert {ls.get(XML_LANG) for ls in root.iter("langSet")} == {"it", "en", "en-GB", "fr"}
    body = _upload(client, other, "/glossary/import", r.content, f"g.{fmt}").json()
    assert body["format"] == fmt and body["imported"] == 3 and body["skipped"] == 0
    assert _terms(db, other["team"].id) == {
        ("Italian", "English", "Comune", "Municipality", "Not 'town' & never <city>", "import"),
        ("Italian", "English", "=Codice", "+Tax code", None, "import"),
        ("Italian", "French", "Prefettura", "Préfecture", None, "import"),
    }
    again = _upload(client, other, "/glossary/import", r.content, f"g.{fmt}").json()
    assert again["imported"] == 0 and again["duplicates"] == 3
    only = client.get("/glossary/export", headers=owner["headers"], params={"format": fmt, "source": "it", "target": "fr"})
    assert b"Prefettura" in only.content and b"Comune" not in only.content


def test_glossary_csv_with_a_column_per_language(client, db, make_user):
    owner = make_user()
    data = "\ufeffen-GB;it-IT;de-DE;Note\nInvoice;Fattura;Rechnung;Tax doc\nVAT;IVA;;\n;Vuoto;Leer;\n".encode("utf-8")
    body = _upload(client, owner, "/glossary/import", data, "terms.csv").json()
    assert (body["imported"], body["invalid"]) == (3, 1)
    assert _terms(db, owner["team"].id) == {
        ("English", "Italian", "Invoice", "Fattura", "Tax doc", "import"),
        ("English", "German", "Invoice", "Rechnung", "Tax doc", "import"),
        ("English", "Italian", "VAT", "IVA", None, "import"),
    }
    picked = _upload(client, make_user(), "/glossary/import", data, "terms.csv", source="it").json()
    assert picked["imported"] == 4
    assert _upload(client, owner, "/glossary/import", b"foo,bar\n1,2\n", "x.csv").status_code == 400


def test_tbx_v3_and_source_choice():
    data = b"""<?xml version="1.0"?>
<tbx type="TBX-Basic" style="dca" xml:lang="en" xmlns="urn:iso:std:iso:30042:ed-2"><text><body>
<conceptEntry id="c1"><descrip type="definition">A town council</descrip>
<langSec xml:lang="en"><termSec><term>council</term></termSec></langSec>
<langSec xml:lang="it"><termSec><term>comune</term></termSec><termSec><term>municipio</term></termSec></langSec>
</conceptEntry>
<conceptEntry id="c2"><langSec xml:lang="en"><termSec><term>orphan</term></termSec></langSec></conceptEntry>
</body></text></tbx>"""
    pairs, invalid = glossary_transfer.parse_tbx(data)
    assert invalid == 1
    assert pairs == [{"source_language": "en", "target_language": "it", "source_term": "council",
                      "target_term": "comune", "notes": "A town council"}]
    pairs, _ = glossary_transfer.parse_tbx(data, source="Italian")
    assert (pairs[0]["source_term"], pairs[0]["target_term"]) == ("comune", "council")


def test_glossary_import_conflicts(client, db, make_user):
    owner = make_user()
    team = owner["team"].id
    _term(db, team, "Comune", "Municipality")
    _term(db, team, "Anagrafe", "Registry (guess)", origin="learned")
    _term(db, team, "Sindaco", "Major", origin="rejected")
    data = b"source_language,target_language,source_term,target_term\nit,en,comune,Town\nit,en,Anagrafe,Registry office\nit,en,Sindaco,Major\nit,xx-unknown-tag,a,b\nit,it,a,b\n"
    body = _upload(client, owner, "/glossary/import", data, "g.csv").json()
    assert {k: body[k] for k in ("imported", "updated", "conflicts", "unsupported_language", "invalid")} == {
        "imported": 0, "updated": 2, "conflicts": 1, "unsupported_language": 1, "invalid": 1,
    }
    db.expire_all()
    terms = _terms(db, team)
    assert ("Italian", "English", "Comune", "Municipality", None, "manual") in terms
    assert ("Italian", "English", "Anagrafe", "Registry office", None, "import") in terms
    assert ("Italian", "English", "Sindaco", "Major", None, "import") in terms
    _upload(client, owner, "/glossary/import", data, "g.csv", replace=True)
    db.expire_all()
    assert ("Italian", "English", "Comune", "Town", None, "import") in _terms(db, team)
