"""Stripe Connect: each team's own account, card payments on protected links, and the unlock webhook. Stripe is mocked."""
import io
import uuid

import pytest

from app.models.delivery_link import DeliveryLink
from app.models.stripe_event import StripeEvent
from tests.test_protected_links import _pdf, _translation_pdf

ACCOUNT = "acct_translator"


@pytest.fixture()
def stub_export(monkeypatch):
    import app.routers.export as export_router
    import app.services.export_service as export_service

    monkeypatch.setattr(export_router, "generate_docx", lambda *a, **kw: io.BytesIO(b"docx"))
    monkeypatch.setattr(export_service, "_convert_docx_to_pdf", lambda data: _translation_pdf())
    monkeypatch.setattr(export_router, "capture_template_in_background", lambda pid, uid: None)


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    import stripe

    def refuse(*a, **kw):
        raise AssertionError("tests must not call Stripe")

    for target, name in (
        (stripe.Account, "create"),
        (stripe.Account, "retrieve"),
        (stripe.AccountLink, "create"),
        (stripe.checkout.Session, "create"),
        (stripe.Webhook, "construct_event"),
    ):
        monkeypatch.setattr(target, name, refuse)
    import requests

    monkeypatch.setattr(requests, "request", refuse)


@pytest.fixture()
def accounts_v1(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "STRIPE_CONNECT_ACCOUNTS_API", "v1")


@pytest.fixture()
def calls(monkeypatch, accounts_v1):
    """Records each mocked Stripe call (v1 accounts); the account starts fully onboarded."""
    import stripe

    log = {"accounts": [], "links": [], "retrieved": [], "sessions": []}
    state = {"charges_enabled": True, "details_submitted": True, "requirements": {"currently_due": [], "past_due": []}}

    def account(**kw):
        log["accounts"].append(kw)
        return {"id": ACCOUNT, "charges_enabled": False, "details_submitted": False}

    def account_link(**kw):
        log["links"].append(kw)
        return {"url": f"https://connect.stripe.test/setup/{kw['account']}"}

    def retrieve(account_id, **kw):
        log["retrieved"].append(account_id)
        return {"id": account_id, **state}

    def session(**kw):
        log["sessions"].append(kw)
        return {"id": "cs_test_1", "url": "https://checkout.stripe.test/cs_test_1"}

    monkeypatch.setattr(stripe.Account, "create", account)
    monkeypatch.setattr(stripe.AccountLink, "create", account_link)
    monkeypatch.setattr(stripe.Account, "retrieve", retrieve)
    monkeypatch.setattr(stripe.checkout.Session, "create", session)
    log["state"] = state
    return log


@pytest.fixture()
def connect_secret(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", "whsec_connect")


@pytest.fixture()
def team_with_stripe(client, db, storage, make_user, make_project, stub_export):
    owner = make_user(email="owner@traqtest.io")
    translator = make_user(email="translator@traqtest.io", team=owner["team"])
    project = make_project(owner)
    storage["objects"][project.file_path] = _pdf(3, "Originale")
    project.file_name = "diploma.pdf"
    owner["team"].name = "Espresso Translations"
    owner["team"].stripe_account_id = ACCOUNT
    owner["team"].stripe_account_status = "active"
    db.commit()
    return owner, translator, project


def _protected(client, user, project, **extra):
    body = {"protected": True, "amount": "45.50", **extra}
    r = client.post(f"/projects/{project.id}/delivery-links", json=body, headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json(), r.json()["url"].rsplit("/d/", 1)[1]


def _event(link_id, *, account=ACCOUNT, event_id=None, type="checkout.session.completed", payment_status="paid"):
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": type,
        "account": account,
        "data": {"object": {
            "id": "cs_test_1",
            "object": "checkout.session",
            "payment_status": payment_status,
            "payment_intent": "pi_123",
            "metadata": {"link_id": str(link_id)},
        }},
    }


def _post(client, monkeypatch, event):
    import stripe

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda payload, sig, secret: event)
    return client.post("/stripe/connect/webhook", content=b"{}", headers={"stripe-signature": "t=1"})


# Connecting the team's account


def test_connect_creates_the_account_once_and_returns_an_onboarding_link(client, db, make_user, calls):
    owner = make_user(email="owner@traqtest.io")
    r = client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.json() == {"url": f"https://connect.stripe.test/setup/{ACCOUNT}"}
    [created] = calls["accounts"]
    assert created["country"] == "IT" and created["email"] == "owner@traqtest.io"
    assert created["controller"] == {
        "stripe_dashboard": {"type": "full"},
        "fees": {"payer": "account"},
        "losses": {"payments": "stripe"},
    }
    assert created["metadata"] == {"team_id": str(owner["team"].id)}
    back = "http://localhost:3000/settings/account?stripe=return#payments"
    assert calls["links"][0] == {"account": ACCOUNT, "type": "account_onboarding", "refresh_url": back, "return_url": back}
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_id == ACCOUNT and owner["team"].stripe_account_status == "pending"

    # Coming back to finish onboarding reuses the account.
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 200
    assert len(calls["accounts"]) == 1 and len(calls["links"]) == 2


def test_connect_is_for_the_owner_or_an_admin(client, make_user, calls):
    owner = make_user()
    member = make_user(team=owner["team"])
    assert client.post("/settings/payments/stripe/connect", headers=member["headers"]).status_code == 403
    assert client.delete("/settings/payments/stripe", headers=member["headers"]).status_code == 403
    admin = make_user(team=owner["team"], role="ADMIN")
    assert client.post("/settings/payments/stripe/connect", headers=admin["headers"]).status_code == 200
    assert calls["accounts"][0]["email"] == admin["user"].email


def test_status_is_refreshed_from_stripe_until_active(client, db, make_user, calls):
    owner = make_user()
    client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    calls["state"].update(charges_enabled=False, details_submitted=True,
                          requirements={"currently_due": ["individual.verification.document"], "past_due": ["tos"]})
    body = client.get("/settings/payments", headers=owner["headers"]).json()
    assert body["stripe_status"] == "restricted"
    assert body["stripe_charges_enabled"] is False and body["stripe_details_submitted"] is True
    assert body["stripe_requirements_due"] == 2

    calls["state"].update(charges_enabled=True, requirements={"currently_due": [], "past_due": []})
    # Back from onboarding: asks Stripe straight away, whatever the throttle says.
    body = client.get("/settings/payments?refresh=1", headers=owner["headers"]).json()
    assert body["stripe_status"] == "active" and body["stripe_charges_enabled"] is True
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_status == "active"

    # Once active, a plain GET doesn't call Stripe.
    before = len(calls["retrieved"])
    assert client.get("/settings/payments", headers=owner["headers"]).json()["stripe_status"] == "active"
    assert len(calls["retrieved"]) == before


def test_pending_status_is_asked_of_stripe_at_most_every_five_minutes(client, db, make_user, calls):
    from datetime import datetime, timedelta

    owner = make_user()
    member = make_user(team=owner["team"])
    client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    calls["state"].update(charges_enabled=False, details_submitted=False)

    before = len(calls["retrieved"])
    client.get("/settings/payments", headers=owner["headers"])
    client.get("/settings/payments", headers=owner["headers"])
    client.get("/settings/payments", headers=member["headers"])
    # Only an editor's return from onboarding skips the wait.
    client.get("/settings/payments?refresh=1", headers=member["headers"])
    assert len(calls["retrieved"]) == before + 1

    team = owner["team"]
    db.refresh(team)
    team.stripe_account_checked_at = datetime.utcnow() - timedelta(minutes=6)
    db.commit()
    client.get("/settings/payments", headers=member["headers"])
    assert len(calls["retrieved"]) == before + 2

    client.get("/settings/payments?refresh=1", headers=owner["headers"])
    assert len(calls["retrieved"]) == before + 3


def test_dashboard_and_disconnect(client, db, make_user, calls):
    owner = make_user()
    assert client.post("/settings/payments/stripe/dashboard", headers=owner["headers"]).status_code == 409
    client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    r = client.post("/settings/payments/stripe/dashboard", headers=owner["headers"])
    assert r.json() == {"url": "https://dashboard.stripe.com/"}

    r = client.delete("/settings/payments/stripe", headers=owner["headers"])
    assert r.status_code == 200 and r.json()["stripe_status"] is None
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_id is None


# Paying a link


def test_protected_link_with_stripe_only(client, db, team_with_stripe, calls):
    owner, translator, project = team_with_stripe
    _, token = _protected(client, translator, project)
    info = client.get(f"/public/delivery/{token}").json()
    assert info["card_payment"] is True and info["paypal_url"] is None


def test_checkout_is_a_direct_charge_on_the_team_account(client, db, team_with_stripe, calls):
    owner, translator, project = team_with_stripe
    body, token = _protected(client, translator, project)
    r = client.post(f"/public/delivery/{token}/checkout")
    assert r.status_code == 200, r.text
    assert r.json() == {"checkout_url": "https://checkout.stripe.test/cs_test_1"}
    [kw] = calls["sessions"]
    assert kw["stripe_account"] == ACCOUNT
    assert kw["mode"] == "payment"
    [item] = kw["line_items"]
    assert item["quantity"] == 1
    assert item["price_data"] == {
        "currency": "eur",
        "unit_amount": 4550,
        "product_data": {"name": "Translation: diploma - translation.pdf"},
    }
    meta = {"link_id": body["id"], "project_id": str(project.id), "team_id": str(owner["team"].id)}
    assert kw["metadata"] == meta
    assert "application_fee_amount" not in kw["payment_intent_data"]
    assert "payment_method_types" not in kw and "automatic_tax" not in kw
    assert kw["success_url"] == f"http://localhost:3000/d/{token}?paid=1"
    assert kw["cancel_url"] == f"http://localhost:3000/d/{token}"


def test_application_fee_only_when_above_zero(client, monkeypatch, team_with_stripe, calls):
    from app.config import settings

    owner, translator, project = team_with_stripe
    _, token = _protected(client, translator, project)
    monkeypatch.setattr(settings, "PLATFORM_FEE_PERCENT", 2.5)
    assert client.post(f"/public/delivery/{token}/checkout").status_code == 200
    assert calls["sessions"][-1]["payment_intent_data"]["application_fee_amount"] == 114  # 2.5% of 45.50
    monkeypatch.setattr(settings, "PLATFORM_FEE_PERCENT", 0.001)
    assert client.post(f"/public/delivery/{token}/checkout").status_code == 200
    assert "application_fee_amount" not in calls["sessions"][-1]["payment_intent_data"]


def test_checkout_409_when_not_payable(client, db, team_with_stripe, calls):
    owner, translator, project = team_with_stripe
    body, token = _protected(client, translator, project)

    owner["team"].stripe_account_status = "restricted"
    db.commit()
    assert client.post(f"/public/delivery/{token}/checkout").status_code == 409
    owner["team"].stripe_account_status = "active"
    owner["team"].stripe_account_id = None
    db.commit()
    assert client.post(f"/public/delivery/{token}/checkout").status_code == 409
    owner["team"].stripe_account_id = ACCOUNT
    db.commit()

    client.post(f"/projects/{project.id}/delivery-links/{body['id']}/unlock", headers=owner["headers"])
    assert client.post(f"/public/delivery/{token}/checkout").status_code == 409

    body2, token2 = _protected(client, translator, project)
    client.delete(f"/projects/{project.id}/delivery-links/{body2['id']}", headers=owner["headers"])
    assert client.post(f"/public/delivery/{token2}/checkout").status_code == 409

    plain = client.post(f"/projects/{project.id}/delivery-links", json={}, headers=owner["headers"]).json()
    assert client.post(f"/public/delivery/{plain['url'].rsplit('/d/', 1)[1]}/checkout").status_code == 409
    assert calls["sessions"] == []


def test_checkout_is_rate_limited(client, team_with_stripe, calls):
    owner, translator, project = team_with_stripe
    _, token = _protected(client, translator, project)
    codes = [client.post(f"/public/delivery/{token}/checkout").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


# The webhook


def test_webhook_unlocks_and_emails_the_creator(client, db, storage, monkeypatch, team_with_stripe, calls, emails,
                                                connect_secret):
    owner, translator, project = team_with_stripe
    body, token = _protected(client, translator, project)
    assert client.get(f"/public/delivery/{token}/preview/1").status_code == 200
    row = db.query(DeliveryLink).one()
    db.refresh(row)
    previews = list(row.preview_keys)
    assert client.get(f"/public/delivery/{token}/file").status_code == 403

    event = _event(body["id"])
    r = _post(client, monkeypatch, event)
    assert r.status_code == 200 and r.json() == {"status": "unlocked"}
    db.refresh(row)
    assert row.unlocked_at is not None and row.paid_at is not None and row.unlocked_by is None
    assert row.stripe_payment_intent == "pi_123"
    assert row.preview_keys is None and set(previews) <= set(storage["deleted"])
    assert client.get(f"/public/delivery/{token}/file").status_code == 200
    assert client.get(f"/public/delivery/{token}").json()["locked"] is False

    [mail] = emails
    assert mail["to"] == "translator@traqtest.io"
    assert mail["subject"] == "Your client paid €45.50"
    assert ("Your client paid €45.50 for diploma - translation.pdf. "
            "The document is now unlocked for them.") in mail["text_fallback"]
    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0]
    assert listed["payment_status"] == "paid" and listed["paid_at"] is not None

    # The same event again, and a later event for the same payment, change nothing.
    assert _post(client, monkeypatch, event).json() == {"status": "already_processed"}
    again = _event(body["id"], type="checkout.session.async_payment_succeeded")
    assert _post(client, monkeypatch, again).status_code == 200
    assert len(emails) == 1


def test_webhook_stores_nothing_from_customer_details(client, db, monkeypatch, caplog, team_with_stripe, calls,
                                                      emails, connect_secret):
    owner, translator, project = team_with_stripe
    body, _ = _protected(client, translator, project)
    before = {c.name: getattr(db.query(DeliveryLink).one(), c.name) for c in DeliveryLink.__table__.columns}
    event = _event(body["id"])
    event["data"]["object"].update(
        customer_details={
            "email": "mario.rossi@example.com",
            "name": "Mario Rossi",
            "phone": "+39 333 1234567",
            "address": {"line1": "Via Roma 1", "city": "Milano", "postal_code": "20100", "country": "IT"},
        },
        customer_email="mario.rossi@example.com",
        customer="cus_123",
    )
    with caplog.at_level("DEBUG"):
        assert _post(client, monkeypatch, event).json() == {"status": "unlocked"}

    row = db.query(DeliveryLink).one()
    db.refresh(row)
    after = {c.name: getattr(row, c.name) for c in DeliveryLink.__table__.columns}
    changed = {k for k in after if after[k] != before[k]}
    assert changed <= {"stripe_payment_intent", "paid_at", "unlocked_at", "preview_keys"}
    assert row.stripe_payment_intent == "pi_123" and row.paid_at is not None and row.amount_cents == 4550
    for needle in ("Mario", "mario.rossi", "Via Roma", "Milano", "333 1234567", "cus_123"):
        assert not any(needle in str(v) for v in after.values())
        assert needle not in caplog.text
        assert all(needle not in m["subject"] and needle not in m["text_fallback"] for m in emails)
    stored = db.query(StripeEvent).filter(StripeEvent.id == event["id"]).one()
    assert {c.name for c in StripeEvent.__table__.columns} == {"id", "event_type", "created_at"}
    assert stored.event_type == "checkout.session.completed"


def test_webhook_ignores_another_account(client, db, monkeypatch, team_with_stripe, calls, emails, connect_secret):
    owner, translator, project = team_with_stripe
    body, token = _protected(client, translator, project)
    r = _post(client, monkeypatch, _event(body["id"], account="acct_someone_else"))
    assert r.json() == {"status": "ignored"}
    assert db.query(DeliveryLink).one().unlocked_at is None
    assert client.get(f"/public/delivery/{token}/file").status_code == 403
    assert emails == []


def test_webhook_waits_for_async_payments(client, db, monkeypatch, team_with_stripe, calls, emails, connect_secret):
    owner, translator, project = team_with_stripe
    body, token = _protected(client, translator, project)
    assert _post(client, monkeypatch, _event(body["id"], payment_status="unpaid")).json() == {"status": "ignored"}
    assert client.get(f"/public/delivery/{token}/file").status_code == 403
    r = _post(client, monkeypatch, _event(body["id"], type="checkout.session.async_payment_succeeded"))
    assert r.json() == {"status": "unlocked"}
    assert client.get(f"/public/delivery/{token}/file").status_code == 200


def test_webhook_falls_back_to_the_owner(client, db, monkeypatch, team_with_stripe, calls, emails, connect_secret):
    owner, translator, project = team_with_stripe
    body, _ = _protected(client, translator, project)
    row = db.query(DeliveryLink).one()
    row.created_by = None  # what deleting the translator's account leaves behind
    db.commit()
    _post(client, monkeypatch, _event(body["id"]))
    assert [m["to"] for m in emails] == ["owner@traqtest.io"]


def test_webhook_rejects_a_bad_signature_and_needs_the_secret(client, monkeypatch, connect_secret):
    import stripe

    def bad(*a, **kw):
        raise stripe.error.SignatureVerificationError("bad", "t=1")

    monkeypatch.setattr(stripe.Webhook, "construct_event", bad)
    assert client.post("/stripe/connect/webhook", content=b"{}", headers={"stripe-signature": "x"}).status_code == 400

    from app.config import settings

    monkeypatch.setattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", None)
    assert client.post("/stripe/connect/webhook", content=b"{}").status_code == 503


def test_account_updated_refreshes_the_status(client, db, monkeypatch, make_user, connect_secret):
    owner = make_user()
    owner["team"].stripe_account_id = ACCOUNT
    owner["team"].stripe_account_status = "pending"
    db.commit()
    event = {"id": "evt_acct_1", "type": "account.updated", "account": ACCOUNT,
             "data": {"object": {"id": ACCOUNT, "charges_enabled": True, "details_submitted": True}}}
    assert _post(client, monkeypatch, event).json() == {"status": "updated"}
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_status == "active"
    assert db.query(StripeEvent).filter(StripeEvent.id == "evt_acct_1").count() == 1

    event = {"id": "evt_acct_2", "type": "account.updated", "account": ACCOUNT,
             "data": {"object": {"id": ACCOUNT, "charges_enabled": False, "details_submitted": True}}}
    _post(client, monkeypatch, event)
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_status == "restricted"


# Who hears about a payment


def test_paid_claim_emails_the_creator_not_the_owner(client, db, storage, make_user, make_project, stub_export,
                                                    emails):
    owner = make_user(email="owner@traqtest.io")
    translator = make_user(email="translator@traqtest.io", team=owner["team"])
    project = make_project(owner)
    storage["objects"][project.file_path] = _pdf(2, "Originale")
    owner["team"].paypal_me = "Espresso"
    db.commit()
    _, token = _protected(client, translator, project)
    assert client.post(f"/public/delivery/{token}/paid").status_code == 200
    assert [m["to"] for m in emails] == ["translator@traqtest.io"]


def test_connect_explains_when_the_platform_setup_is_unfinished(client, make_user, monkeypatch, accounts_v1):
    import stripe

    def refuse(**kwargs):
        raise stripe.InvalidRequestError(
            "You must complete your platform profile to use Connect and create live connected accounts.", None
        )

    monkeypatch.setattr(stripe.Account, "create", refuse)
    owner = make_user()
    r = client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    assert r.status_code == 503
    assert "Stripe setup isn't finished" in r.json()["detail"]


def test_a_failed_connect_is_retried_fresh_not_replayed(client, make_user, monkeypatch, accounts_v1):
    # Stripe replays a reused idempotency key's first answer for 24h, errors included,
    # so each attempt needs its own key or a fixed setup still looks broken.
    import stripe

    keys = []

    def create(**kw):
        keys.append(kw["idempotency_key"])
        if len(keys) == 1:
            raise stripe.InvalidRequestError("You must complete your platform profile to use Connect.", None)
        return {"id": ACCOUNT, "charges_enabled": False, "details_submitted": False}

    monkeypatch.setattr(stripe.Account, "create", create)
    monkeypatch.setattr(stripe.AccountLink, "create", lambda **kw: {"url": "https://connect.stripe.test/setup"})
    owner = make_user()
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 503
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 200
    assert len(keys) == 2 and keys[0] != keys[1]


# Accounts v2 (the default): direct HTTPS calls, requests mocked


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _v2_account(card_status="restricted", entries=()):
    """Entries are (description, deadline status) or (description, deadline status, awaiting_action_from)."""
    return {
        "id": ACCOUNT,
        "object": "v2.core.account",
        "configuration": {"merchant": {"capabilities": {"card_payments": {"status": card_status}}}},
        "requirements": {"entries": [
            {"description": e[0], "awaiting_action_from": e[2] if len(e) > 2 else "user",
             "minimum_deadline": {"status": e[1]}}
            for e in entries
        ]},
    }


# As Stripe test mode answers for a full-Dashboard account nobody has onboarded yet.
FRESH = [
    ("configuration.merchant.mcc", "past_due"),
    ("defaults.profile.business_url", "past_due"),
    ("external_account", "past_due"),
    ("identity.attestations.terms_of_service.account.date", "past_due"),
    ("identity.attestations.terms_of_service.account.ip", "past_due"),
]


@pytest.fixture()
def v2(monkeypatch):
    """Records each v2 request; answers with `state["account"]` or `state["error"]`."""
    import requests

    log = []
    state = {"account": _v2_account(entries=FRESH), "error": None}

    def request(method, url, **kw):
        log.append({"method": method, "url": url, **kw})
        if state["error"]:
            return _Resp(400, {"error": state["error"]})
        if url.endswith("/v2/core/account_links"):
            return _Resp(200, {"object": "v2.core.account_link",
                               "url": f"https://accounts.stripe.test/r/{kw['json']['account']}",
                               "expires_at": "2026-10-07T12:10:00.000Z"})
        return _Resp(200, state["account"])

    monkeypatch.setattr(requests, "request", request)
    return {"log": log, "state": state}


def test_v2_connect_sends_the_account_and_link_requests(client, db, make_user, v2):
    from app.config import settings

    owner = make_user(email="owner@traqtest.io")
    owner["team"].name = "Espresso Translations"
    db.commit()
    r = client.post("/settings/payments/stripe/connect", json={"country": "de"}, headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.json() == {"url": f"https://accounts.stripe.test/r/{ACCOUNT}"}

    create, link = v2["log"]
    assert (create["method"], create["url"]) == ("POST", "https://api.stripe.com/v2/core/accounts")
    assert create["json"] == {
        "contact_email": "owner@traqtest.io",
        "display_name": "Espresso Translations",
        "identity": {"country": "de"},
        "dashboard": "full",
        "defaults": {"responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}},
        "configuration": {"merchant": {"capabilities": {"card_payments": {"requested": True}}}},
        "include": ["configuration.merchant", "requirements", "identity", "defaults"],
        "metadata": {"team_id": str(owner["team"].id)},
    }
    headers = create["headers"]
    assert headers["Authorization"] == f"Bearer {settings.stripe_secret_key}"
    assert headers["Stripe-Version"] == "2026-09-30.endive"
    assert headers["Content-Type"] == "application/json"
    assert headers["Idempotency-Key"].startswith(f"connect-account-{owner['team'].id}-")
    assert create["timeout"]

    back = "http://localhost:3000/settings/account?stripe=return#payments"
    assert (link["method"], link["url"]) == ("POST", "https://api.stripe.com/v2/core/account_links")
    assert link["json"] == {"account": ACCOUNT, "use_case": {"type": "account_onboarding", "account_onboarding": {
        "return_url": back, "refresh_url": back}}}

    db.refresh(owner["team"])
    assert owner["team"].stripe_account_id == ACCOUNT and owner["team"].stripe_account_status == "pending"

    # Back again: the stored account is reused, only a new link is made.
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 200
    assert [c["url"].rsplit("/", 1)[1] for c in v2["log"]] == ["accounts", "account_links", "account_links"]


def test_v2_default_country_is_lowercased(client, make_user, v2):
    owner = make_user()
    client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    assert v2["log"][0]["json"]["identity"] == {"country": "it"}


def test_v2_idempotency_key_is_fresh_per_attempt(client, make_user, v2):
    owner = make_user()
    v2["state"]["error"] = {"code": "connect_profile_not_submitted", "message": "Complete your platform profile."}
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 503
    v2["state"]["error"] = None
    assert client.post("/settings/payments/stripe/connect", headers=owner["headers"]).status_code == 200
    keys = [c["headers"]["Idempotency-Key"] for c in v2["log"] if c["url"].endswith("/accounts")]
    assert len(keys) == 2 and keys[0] != keys[1]


@pytest.mark.parametrize("card_status, entries, status, charges, submitted, due", [
    ("active", [], "active", True, True, 0),
    ("active", [("tax_id", "eventually_due")], "active", True, True, 0),
    ("active", [("external_account", "past_due")], "active", True, False, 1),
    # Never onboarded: Stripe's terms are still to accept.
    ("restricted", FRESH, "pending", False, False, 5),
    # Onboarded, Stripe still verifying: nothing for the translator to do.
    ("pending", [("identity.individual.surname", "past_due", "stripe"),
                 ("identity.individual.date_of_birth.year", "past_due", "stripe")], "restricted", False, True, 0),
    ("pending", [("tax_id", "eventually_due")], "restricted", False, True, 0),
    (None, [], "restricted", False, True, 0),
    ("restricted", [], "restricted", False, True, 0),
    ("pending", [("individual.id", "currently_due"), ("tos", "past_due")], "restricted", False, False, 2),
])
def test_v2_status_mapping(card_status, entries, status, charges, submitted, due):
    from app.services import stripe_connect

    account = stripe_connect.from_v2(_v2_account(card_status, entries))
    assert account["status"] == status
    assert account["charges_enabled"] is charges and account["details_submitted"] is submitted
    assert stripe_connect.requirements_due(account) == due


def test_v2_status_refresh(client, db, make_user, v2):
    owner = make_user()
    owner["team"].stripe_account_id = ACCOUNT
    owner["team"].stripe_account_status = "pending"
    db.commit()
    v2["state"]["account"] = _v2_account("restricted", [("individual.id", "currently_due"), ("tos", "past_due")])
    body = client.get("/settings/payments", headers=owner["headers"]).json()
    assert body["stripe_status"] == "restricted"
    assert body["stripe_charges_enabled"] is False and body["stripe_details_submitted"] is False
    assert body["stripe_requirements_due"] == 2
    [get] = v2["log"]
    assert (get["method"], get["url"]) == ("GET", f"https://api.stripe.com/v2/core/accounts/{ACCOUNT}")
    assert get["params"] == [("include[0]", "configuration.merchant"), ("include[1]", "requirements")]
    assert "Idempotency-Key" not in get["headers"]

    # Back from onboarding: asked straight away, whatever the throttle says.
    v2["state"]["account"] = _v2_account("active")
    body = client.get("/settings/payments?refresh=1", headers=owner["headers"]).json()
    assert body["stripe_status"] == "active" and body["stripe_charges_enabled"] is True
    assert body["stripe_requirements_due"] == 0
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_status == "active"


def test_v2_refresh_survives_a_stripe_error(client, db, make_user, v2):
    owner = make_user()
    owner["team"].stripe_account_id = ACCOUNT
    owner["team"].stripe_account_status = "pending"
    db.commit()
    v2["state"]["error"] = {"code": "not_found", "message": "No such account."}
    assert client.get("/settings/payments", headers=owner["headers"]).json()["stripe_status"] == "pending"


@pytest.mark.parametrize("code, http, detail", [
    ("connect_profile_not_submitted", 503, "Stripe setup isn't finished"),
    ("connect_identity_not_verified", 503, "Stripe setup isn't finished"),
    ("platform_registration_required", 503, "Stripe setup isn't finished"),
    ("account_create_activation_required", 503, "Stripe setup isn't finished"),
    ("cross_border_connected_account_creation_not_allowed", 422,
     "Card payments aren't available for accounts in this country yet."),
    ("email_invalid", 502, "Stripe isn't reachable"),
])
def test_v2_errors_are_explained(client, db, make_user, v2, code, http, detail):
    owner = make_user()
    v2["state"]["error"] = {"code": code, "message": "Stripe says no."}
    r = client.post("/settings/payments/stripe/connect", headers=owner["headers"])
    assert r.status_code == http and detail in r.json()["detail"]
    db.refresh(owner["team"])
    assert owner["team"].stripe_account_id is None


def test_v2_error_parsing_and_network_failure(monkeypatch):
    import requests

    from app.services import stripe_connect

    refused = _Resp(400, {"error": {"code": "email_invalid", "message": "Bad email"}})
    monkeypatch.setattr(requests, "request", lambda *a, **kw: refused)
    with pytest.raises(stripe_connect.StripeV2Error) as err:
        stripe_connect._v2_request("POST", "/v2/core/accounts", json={})
    assert (err.value.code, err.value.message, err.value.status) == ("email_invalid", "Bad email", 400)

    def down(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "request", down)
    with pytest.raises(stripe_connect.StripeV2Error) as err:
        stripe_connect._v2_request("GET", "/v2/core/accounts/acct_1")
    assert err.value.code == "api_connection_error"
