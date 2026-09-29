"""Certification page fields and the names translators use for them in Word merge fields and {{tokens}}."""
from __future__ import annotations

import re
import unicodedata

# Every field becomes a content control tagged cert.<name>, so the page can be updated in place.
LABELS: dict[str, str] = {
    "translator": "Translator",
    "date": "Date",
    "source_language": "Source language",
    "target_language": "Target language",
    "document": "Document",
    "pages": "Pages",
    "client": "Client",
    "translator_email": "Translator email",
    "company": "Company",
    "company_address": "Company address",
    "certificate_number": "Certificate number",
    "file_name": "Source file",
}
FIELDS = tuple(LABELS)

ALIASES: dict[str, tuple[str, ...]] = {
    "translator": (
        "Translator", "Traduttore", "TranslatorName", "Translator_Name", "Traduttrice", "NomeTraduttore",
        "TranslatorFullName", "Traductor", "Traducteur", "Übersetzer", "Tradutor", "SwornTranslator", "Firmatario",
    ),
    "date": (
        "Date", "Data", "Today", "Date_Long", "Oggi", "CurrentDate", "CertificationDate", "DataCertificazione",
        "DataOdierna", "Fecha", "Datum",
    ),
    "source_language": (
        "SourceLanguage", "LinguaOrigine", "Source_Language", "LinguaPartenza", "SourceLang", "Source",
        "FromLanguage", "OriginalLanguage", "LinguaDiOrigine", "LinguaDiPartenza", "LinguaSorgente", "IdiomaOrigen",
        "LangueSource", "Ausgangssprache",
    ),
    "target_language": (
        "TargetLanguage", "LinguaDestinazione", "Target_Language", "LinguaArrivo", "TargetLang", "Target",
        "ToLanguage", "LinguaDiDestinazione", "LinguaDiArrivo", "IdiomaDestino", "LangueCible", "Zielsprache",
    ),
    "document": (
        "Document", "Documento", "DocumentTitle", "Document_Name", "Title", "Titolo", "TitoloDocumento",
        "NomeDocumento", "TipoDocumento", "DocumentType",
    ),
    "pages": ("Pages", "Pagine", "Page_Count", "NumeroPagine", "NumberOfPages", "NumPagine", "Paginas", "Seiten"),
    "client": ("Client", "Cliente", "ClientName", "NomeCliente", "Customer", "CustomerName", "Committente", "Richiedente"),
    "translator_email": ("Email", "Translator_Email", "EmailTraduttore", "Mail"),
    "company": ("Company", "Azienda", "CompanyName", "Agenzia", "Team_Name", "Agency", "Ditta"),
    "company_address": ("Address", "Indirizzo", "Company_Address", "IndirizzoAzienda", "Sede"),
    "certificate_number": (
        "CertificateNumber", "NumeroCertificato", "Certificate_Number", "Protocollo", "CertificateNo", "CertNo",
        "CertNumber", "NumeroProtocollo", "Reference", "Riferimento",
    ),
    "file_name": ("FileName", "NomeFile", "SourceFile", "OriginalFile"),
}


def normalize(name: str) -> str:
    """'Lingua_Origine ' / 'lingua origine' / 'LinguaOrigine' -> 'linguaorigine'."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in decomposed if not unicodedata.combining(c)).lower())


_LOOKUP = {normalize(alias): field for field, names in ALIASES.items() for alias in (field, *names)}


def resolve(name: str) -> str | None:
    return _LOOKUP.get(normalize(name))
