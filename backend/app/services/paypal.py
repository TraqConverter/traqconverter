"""PayPal.me handles and payment links. Clients pay on PayPal; nothing here touches payment details."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_AMOUNT_CENTS = 100_000 * 100
CURRENCIES = ("EUR", "GBP", "USD")
_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}

_HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,20}$")
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:paypal\.me|paypal\.biz|paypal\.com/paypalme|paypal\.com/biz/profile)/([^/?#\s]+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)


def normalise_handle(value: str | None) -> str | None:
    """'EspressoTranslations', '@EspressoTranslations' or a paypal.me / paypal.biz / paypal.com/paypalme /
    paypal.com/biz/profile URL -> the handle.

    None or blank clears it. Raises ValueError for anything else.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    match = _URL_RE.match(raw)
    raw = match.group(1) if match else raw.removeprefix("@")
    if not _HANDLE_RE.match(raw) or raw.lower().startswith(("paypal.", "www.")):
        raise ValueError("A PayPal.me name is 1–20 letters, digits, dots, dashes or underscores")
    return raw


def to_cents(amount) -> int:
    """45, '45.5' or Decimal('45.50') -> 4550. Raises ValueError outside 0 < amount <= 100000."""
    try:
        cents = int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter the amount as a number")
    if cents <= 0 or cents > MAX_AMOUNT_CENTS:
        raise ValueError("The amount must be more than 0 and at most 100000")
    return cents


def amount_text(cents: int) -> str:
    """4500 -> '45', 4550 -> '45.50' (the form paypal.me takes)."""
    whole, rest = divmod(int(cents), 100)
    return str(whole) if rest == 0 else f"{whole}.{rest:02d}"


def display_amount(cents: int, currency: str = "EUR") -> str:
    symbol = _SYMBOLS.get(currency)
    return f"{symbol}{amount_text(cents)}" if symbol else f"{amount_text(cents)} {currency}"


def payment_url(handle: str, cents: int, currency: str = "EUR") -> str:
    return f"https://paypal.me/{handle}/{amount_text(cents)}{currency.upper()}"
