"""Stripe Connect end to end against Stripe TEST mode: connect, onboarding, a direct-charge checkout, the webhook.

    cd backend
    DATABASE_URL=postgresql+psycopg2://dan@localhost:5432/traqconverter_e2e_test \\
    STRIPE_TEST_SECRET_KEY=sk_test_... PYTHONPATH=. venv/bin/python scripts/connect_e2e_testmode.py
    # or --key-file ~/stripe-test-key; --pay-with-node DIR pays with Playwright (a node_modules dir that has it)

Refuses anything but an sk_test_ key and a *_test database. Storage and email are faked in memory, so only
Stripe's test API is called. Rows are added to the test DB, never truncated; test connected accounts are
deleted at the end unless --keep.

Hosted onboarding of a full-Dashboard account can't be scripted: Stripe asks for an hCaptcha and won't let a
platform accept its terms for an account whose requirements Stripe collects. So by default steps 3-4 run on a
stand-in account the platform verifies itself (dashboard none). --onboarding manual prints the real account's
link and waits while you finish it in a browser, then runs everything on that account.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

STRIPE_API = "https://api.stripe.com"
AMOUNT_CENTS = 4500
PAYER = {"email": "e2e-payer@example.com", "name": "Mario Pagatore E2E", "postal": "76125"}

PAY_MJS = r"""
import { chromium } from "playwright";
const [url, email, name, postal] = process.argv.slice(2);
const b = await chromium.launch();
const p = await b.newPage({ locale: "en-GB" });
try {
  await p.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await p.waitForSelector("#email, #cardNumber", { timeout: 60000 });
  // With several payment methods the card form sits in a collapsed accordion; its button is zero-size.
  if (!(await p.locator("#cardNumber").isVisible())) {
    await p.locator("#payment-method-accordion-item-title-card, [data-testid=card-accordion-item]").first().click();
    await p.waitForSelector("#cardNumber", { state: "visible", timeout: 15000 });
  }
  if (await p.locator("#email").isVisible()) await p.fill("#email", email);
  await p.fill("#cardNumber", "4242424242424242");
  await p.fill("#cardExpiry", "12 / 34");
  await p.fill("#cardCvc", "123");
  if (await p.locator("#billingName").isVisible()) await p.fill("#billingName", name);
  if (await p.locator("#billingCountry").isVisible()) await p.selectOption("#billingCountry", "IT");
  if (await p.locator("#billingPostalCode").isVisible()) await p.fill("#billingPostalCode", postal);
  await p.click("[data-testid=hosted-payment-submit-button]");
  await p.waitForURL((u) => !u.href.includes("checkout.stripe.com"), { timeout: 90000 }).catch(() => {});
  console.log("submitted");
} catch (e) {
  await p.screenshot({ path: "connect_e2e_pay_error.png", fullPage: true });
  console.log("pay-error:", e.message.split("\n")[0]);
  process.exitCode = 1;
} finally { await b.close(); }
"""


def _load_key(args) -> str:
    key = os.environ.get("STRIPE_TEST_SECRET_KEY") or ""
    if not key and args.key_file:
        key = Path(args.key_file).expanduser().read_text().strip()
    if not key.startswith("sk_test_"):
        sys.exit("Refusing to run: give an sk_test_ key (STRIPE_TEST_SECRET_KEY or --key-file).")
    return key


def _db_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


class Report:
    def __init__(self):
        self.rows = []

    def step(self, name, ok, detail=""):
        self.rows.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""), flush=True)
        return ok

    def note(self, text):
        print(f"       {text}", flush=True)

    @property
    def failed(self):
        return [r for r in self.rows if not r[1]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key-file", help="file holding the sk_test_ key (else STRIPE_TEST_SECRET_KEY)")
    parser.add_argument("--onboarding", choices=["api", "manual"], default="api")
    parser.add_argument("--pay-with-node", metavar="DIR",
                        help="directory whose node_modules has playwright; without it, pay the printed URL by hand")
    parser.add_argument("--fee-percent", type=float, default=0,
                        help="also run a checkout with PLATFORM_FEE_PERCENT set to this")
    parser.add_argument("--country", default="it")
    parser.add_argument("--keep", action="store_true", help="don't delete the test connected accounts")
    parser.add_argument("--wait", type=int, default=600, help="seconds to wait for onboarding or payment")
    args = parser.parse_args()

    key = _load_key(args)
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("database_url") or ""
    if not _db_name(db_url).endswith("_test"):
        sys.exit("Refusing to run: DATABASE_URL must point at a *_test database.")
    os.environ["database_url"] = db_url
    os.environ["stripe_secret_key"] = key
    os.environ["STRIPE_CONNECT_WEBHOOK_SECRET"] = f"whsec_local_{secrets.token_hex(16)}"
    os.environ["PLATFORM_FEE_PERCENT"] = "0"
    os.environ.setdefault("RUN_WORKER_INLINE", "0")
    os.chdir(BACKEND)
    return E2E(args, key).run()


class E2E:
    def __init__(self, args, key):
        self.args = args
        self.key = key
        self.report = Report()
        self.created_accounts: list[str] = []
        self.sent_emails: list[dict] = []

    # Setup

    def _boot(self):
        import alembic.config
        from alembic import command

        from app.config import settings

        assert settings.stripe_secret_key.startswith("sk_test_")
        assert _db_name(settings.database_url).endswith("_test")
        os.environ["DATABASE_URL"] = settings.database_url
        command.upgrade(alembic.config.Config(str(BACKEND / "alembic.ini")), "head")
        self._fake_storage_and_email()

        from fastapi.testclient import TestClient

        from app.database import SessionLocal
        from app.main import app

        self.settings = settings
        self.db = SessionLocal()
        self.client = TestClient(app)

    def _fake_storage_and_email(self):
        import app.routers.project as project_router
        import app.services.email_service as email_service
        import app.services.s3_service as s3

        self.objects: dict[str, bytes] = {}
        s3.upload_file_to_s3 = lambda path, prefix="uploads": self._put(Path(path).read_bytes(), prefix)
        s3.download_file_from_s3 = lambda k, dest: Path(dest).write_bytes(self.objects[k])
        s3.delete_objects_from_s3 = lambda keys: None
        s3.stream_object = lambda k, chunk_size=65536: iter([self.objects[k]])
        s3.generate_presigned_download_url = lambda k, **kw: f"https://storage.test/{k}"
        s3.object_exists = lambda k: k in self.objects
        project_router.upload_file_to_s3 = s3.upload_file_to_s3
        email_service.send_email = lambda **kw: self.sent_emails.append(kw) or True

    def _put(self, data: bytes, prefix: str) -> str:
        k = f"{prefix}/{uuid.uuid4()}"
        self.objects[k] = data
        return k

    def _team_and_owner(self):
        from app.core.security import create_access_token, hash_password
        from app.models.credit import CreditWallet
        from app.models.team import Team
        from app.models.user import User

        tag = uuid.uuid4().hex[:8]
        user = User(email=f"connect-e2e-{tag}@traqtest.io", password_hash=hash_password(secrets.token_hex(12)),
                    full_name="Connect E2E")
        self.db.add(user)
        self.db.flush()
        team = Team(name=f"Connect E2E {tag}", owner_id=user.id)
        self.db.add(team)
        self.db.flush()
        self.db.add(CreditWallet(team_id=team.id, subscription_credits=10, purchased_credits=0, plan_type="PRO",
                                 subscription_status="ACTIVE",
                                 subscription_expires_at=datetime.utcnow() + timedelta(days=30)))
        self.db.commit()
        self.user, self.team = user, team
        self.headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)}, token_version=0)}"}

    def _protected_link(self, amount_cents=AMOUNT_CENTS):
        from app.models.delivery_link import DeliveryLink
        from app.models.project import ProjectStatus, TranslationProject
        from app.services import delivery_links

        project = TranslationProject(
            user_id=self.user.id, team_id=self.team.id, file_name="diploma.pdf",
            file_path=self._put(b"%PDF-1.4 e2e", "uploads"), page_count=1, credits_used=1,
            status=ProjectStatus.COMPLETED, source_kind="PDF", source_language="Italian",
            target_language="English", model="claude-sonnet-4-6",
        )
        self.db.add(project)
        self.db.flush()
        token = secrets.token_urlsafe(delivery_links.TOKEN_BYTES)
        link = DeliveryLink(
            project_id=project.id, token_hash=delivery_links.hash_token(token), token_prefix=token[:6],
            kind="delivery_pdf", file_name="diploma_EN.pdf", file_key=self._put(b"%PDF-1.4 translated", "delivery"),
            file_size=19, expires_at=datetime.utcnow() + timedelta(days=30), created_by=self.user.id,
            protected=True, amount_cents=amount_cents, currency="EUR", preview_pages=1, original_pages=0,
        )
        self.db.add(link)
        self.db.commit()
        return link, token

    # Stripe helpers (test mode only; the key was checked at start)

    def _v1(self, method, path, account=None, **params):
        import requests

        headers = {"Stripe-Account": account} if account else {}
        r = requests.request(method, f"{STRIPE_API}{path}", auth=(self.key, ""), headers=headers,
                             params=params if method == "GET" else None,
                             data=params if method != "GET" else None, timeout=30)
        return r.status_code, r.json()

    def _v2(self, method, path, body=None):
        from app.services import stripe_connect

        return stripe_connect._v2_request(method, path, json=body)

    def _card_status(self, raw):
        return (((raw.get("configuration") or {}).get("merchant") or {}).get("capabilities") or {}) \
            .get("card_payments", {}).get("status")

    def _retrieve_v2(self, account_id):
        return self._v2("GET", f"/v2/core/accounts/{account_id}?include=configuration.merchant&include=requirements")

    # Steps

    def step_connect(self):
        from app.services import stripe_connect

        r = self.client.post("/settings/payments/stripe/connect", json={"country": self.args.country},
                             headers=self.headers)
        self.db.refresh(self.team)
        ok = r.status_code == 200 and "url" in r.json() and bool(self.team.stripe_account_id)
        detail = f"HTTP {r.status_code}" + ("" if ok else f" {r.text[:300]}")
        if not self.report.step("1. connect: POST /v2/core/accounts + /v2/core/account_links", ok, detail):
            return False
        self.account_id = self.team.stripe_account_id
        self.created_accounts.append(self.account_id)
        self.onboarding_link = r.json()["url"]
        raw = self._retrieve_v2(self.account_id)
        self.report.note(f"account {self.account_id}: dashboard={raw.get('dashboard')}, "
                         f"configuration.merchant.capabilities.card_payments.status={self._card_status(raw)}, "
                         f"stored status={self.team.stripe_account_status}")
        self.report.note(f"onboarding link host: {self.onboarding_link.split('/setup/')[0]}")
        back = f"{self.settings.FRONTEND_URL.rstrip('/')}/settings/account"
        try:
            self._v2("POST", "/v2/core/account_links", {"account": self.account_id, "use_case": {
                "type": "account_onboarding",
                "account_onboarding": {"configurations": ["merchant"], "return_url": back, "refresh_url": back}}})
            self.report.note("account_links with configurations=[merchant]: accepted")
        except stripe_connect.StripeV2Error as exc:
            self.report.note(f"account_links with configurations=[merchant]: rejected ({exc.code}), so we omit it")
        return True

    def step_onboarding(self):
        if self.args.onboarding == "manual":
            print(f"\nFinish onboarding in a browser (test mode):\n  {self.onboarding_link}\n", flush=True)
            target = self.account_id
        else:
            target = self._api_onboarded_account()
            if target is None:
                return False
            # The team now points at the stand-in, stored as not yet active, like a team back from onboarding.
            self.team.stripe_account_id = target
            self.team.stripe_account_status = "pending"
            self.db.commit()
        deadline = time.time() + self.args.wait
        body = {}
        while time.time() < deadline:
            body = self.client.get("/settings/payments?refresh=1", headers=self.headers).json()
            if body.get("stripe_status") == "active":
                break
            time.sleep(10)
        raw = self._retrieve_v2(target)
        ok = body.get("stripe_status") == "active" and body.get("stripe_charges_enabled") is True
        self.report.step("2. onboarding + status refresh (v2 retrieve, from_v2)", ok,
                         f"stripe_status={body.get('stripe_status')}, charges_enabled={body.get('stripe_charges_enabled')}"
                         f", requirements_due={body.get('stripe_requirements_due')}")
        self.report.note(f"real path configuration.merchant.capabilities.card_payments.status = {self._card_status(raw)}")
        self.connected = target
        return ok

    def _api_onboarded_account(self):
        from app.services import stripe_connect

        individual = {
            "given_name": "Jenny", "surname": "Rosen", "email": "connect-e2e@traqtest.io", "phone": "+393331234567",
            "date_of_birth": {"day": 1, "month": 1, "year": 1902},
            "address": {"line1": "address_full_match", "city": "Trani", "postal_code": "76125", "country": "it"},
            "documents": {"primary_verification": {"type": "front_back",
                                                   "front_back": {"front": "file_identity_document_success"}}},
        }
        try:
            raw = self._v2("POST", "/v2/core/accounts", {
                "contact_email": "connect-e2e@traqtest.io",
                "display_name": "Connect E2E stand-in",
                "dashboard": "none",
                "identity": {
                    "country": "it", "entity_type": "individual", "individual": individual,
                    "attestations": {"terms_of_service": {"account": {
                        "date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "ip": "127.0.0.1"}}},
                },
                "defaults": {
                    "currency": "eur",
                    "profile": {"business_url": "https://www.onlinedoctranslator.ai",
                                "product_description": "Translation services"},
                    "responsibilities": {"fees_collector": "application", "losses_collector": "application"},
                },
                "configuration": {"merchant": {"mcc": "7399", "support": {"phone": "+393331234567"},
                                               "capabilities": {"card_payments": {"requested": True}}}},
                "include": ["configuration.merchant", "requirements"],
                "metadata": {"purpose": "connect_e2e_testmode"},
            })
        except stripe_connect.StripeV2Error as exc:
            self.report.step("2. onboarding: create API-verified stand-in account", False, f"{exc.code}: {exc.message}")
            return None
        self.created_accounts.append(raw["id"])
        self.report.note(f"full-Dashboard account {self.account_id} can't be onboarded by script (hCaptcha, "
                         f"tos_acceptance_on_behalf_not_allowed); stand-in {raw['id']} (dashboard none) is used")
        return raw["id"]

    def step_checkout(self, label="3. checkout: direct charge on the connected account", fee_percent=0.0):
        self.settings.PLATFORM_FEE_PERCENT = fee_percent
        link, token = self._protected_link()
        r = self.client.post(f"/public/delivery/{token}/checkout")
        if r.status_code != 200:
            self.report.step(label, False, f"HTTP {r.status_code} {r.text[:300]}")
            return None
        url = r.json()["checkout_url"]
        session_id = re.search(r"cs_test_[A-Za-z0-9]+", url).group(0)
        status, session = self._v1("GET", f"/v1/checkout/sessions/{session_id}", account=self.connected)
        self.report.note(f"session {session_id} on {self.connected}: HTTP {status}, amount_total="
                         f"{session.get('amount_total')} {session.get('currency')}, status={session.get('status')}")
        self._pay(url)
        deadline = time.time() + self.args.wait
        while time.time() < deadline:
            status, session = self._v1("GET", f"/v1/checkout/sessions/{session_id}", account=self.connected)
            if session.get("payment_status") == "paid":
                break
            time.sleep(5)
        ok = session.get("payment_status") == "paid"
        self.report.step(label, ok, f"payment_status={session.get('payment_status')}, "
                                    f"payment_intent={session.get('payment_intent')}")
        if ok and fee_percent:
            _, pi = self._v1("GET", f"/v1/payment_intents/{session['payment_intent']}", account=self.connected)
            self.report.note(f"application_fee_amount on the PaymentIntent: {pi.get('application_fee_amount')}")
        self.settings.PLATFORM_FEE_PERCENT = 0
        return (link, token, session) if ok else None

    def _pay(self, url):
        if not self.args.pay_with_node:
            print(f"\nPay with 4242 4242 4242 4242, any future expiry, CVC 123:\n  {url}\n", flush=True)
            return
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", dir=self.args.pay_with_node, delete=False) as f:
            f.write(PAY_MJS)
        try:
            out = subprocess.run(["node", f.name, url, PAYER["email"], PAYER["name"], PAYER["postal"]],
                                 cwd=self.args.pay_with_node, capture_output=True, text=True, timeout=240)
            self.report.note(f"playwright: {(out.stdout + out.stderr).strip()[:300]}")
        finally:
            os.unlink(f.name)

    def step_webhook(self, link, token, session):
        from app.models.delivery_link import DeliveryLink

        event = None
        deadline = time.time() + 120
        while time.time() < deadline and event is None:
            _, page = self._v1("GET", "/v1/events", account=self.connected, type="checkout.session.completed", limit=20)
            event = next((e for e in page.get("data", []) if e["data"]["object"]["id"] == session["id"]), None)
            if event is None:
                time.sleep(5)
        if event is None:
            return self.report.step("4. webhook: fetch the real checkout.session.completed", False, "no event")
        if event.get("account"):
            self.report.note(f"events API returned account={event['account']}")
        else:
            event["account"] = self.connected
            self.report.note("events API returned no 'account' field; added it as a Connect delivery would")
        payload = json.dumps(event)
        t = int(time.time())
        secret = self.settings.STRIPE_CONNECT_WEBHOOK_SECRET
        sig = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
        headers = {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}
        r = self.client.post("/stripe/connect/webhook", content=payload, headers=headers)
        again = self.client.post("/stripe/connect/webhook", content=payload, headers=headers)
        self.db.expire_all()
        link = self.db.query(DeliveryLink).filter(DeliveryLink.id == link.id).one()
        file_ok = self.client.get(f"/public/delivery/{token}/file").status_code == 200
        emails = [m for m in self.sent_emails if m.get("to") == self.user.email and "paid" in m.get("subject", "")]
        leaked = self._tables_containing(PAYER["email"], PAYER["name"])
        checks = {
            "webhook 200 unlocked": r.status_code == 200 and r.json().get("status") == "unlocked",
            "replay already_processed": again.json().get("status") == "already_processed",
            "unlocked_at": link.unlocked_at is not None,
            "paid_at": link.paid_at is not None,
            "payment intent stored": link.stripe_payment_intent == session.get("payment_intent"),
            "file downloadable": file_ok,
            "creator emailed": len(emails) == 1,
            "no client data stored": not leaked,
        }
        failed = [k for k, v in checks.items() if not v]
        return self.report.step("4. webhook: real event, signed, posted to /stripe/connect/webhook", not failed,
                                f"event {event['id']}; " + ("all checks passed" if not failed else f"failed: {failed}")
                                + (f"; client data found in {leaked}" if leaked else ""))

    def _tables_containing(self, *needles):
        from sqlalchemy import text

        tables = [r[0] for r in self.db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))]
        hits = []
        for table in tables:
            for needle in needles:
                found = self.db.execute(text(f'SELECT 1 FROM "{table}" t WHERE t::text ILIKE :n LIMIT 1'),
                                        {"n": f"%{needle}%"}).first()
                if found:
                    hits.append(table)
        return sorted(set(hits))

    def step_fee(self):
        pct = self.args.fee_percent
        paid = self.step_checkout(f"5. checkout with PLATFORM_FEE_PERCENT={pct:g} on {self.connected}", pct)
        # The production shape (fees_collector=stripe) can only be charged once the full-Dashboard account
        # is onboarded; until then, see whether Stripe takes the session at all.
        if self.connected != self.account_id:
            from types import SimpleNamespace

            from app.services import stripe_connect

            link, token = self._protected_link()
            self.settings.PLATFORM_FEE_PERCENT = pct
            try:
                stripe_connect.checkout_url(link, SimpleNamespace(id=self.team.id, stripe_account_id=self.account_id),
                                            token)
                self.report.note(f"fee session on full-Dashboard {self.account_id} (fees_collector=stripe): accepted")
            except Exception as exc:
                self.report.note(f"fee session on full-Dashboard {self.account_id} (fees_collector=stripe): "
                                 f"{getattr(exc, 'code', '')} {str(exc)[:200]}")
            finally:
                self.settings.PLATFORM_FEE_PERCENT = 0
        return paid is not None

    def cleanup(self):
        if self.args.keep:
            self.report.note(f"kept test accounts: {self.created_accounts}")
            return
        for account in self.created_accounts:
            status, body = self._v1("DELETE", f"/v1/accounts/{account}")
            self.report.note(f"delete {account}: HTTP {status} deleted={body.get('deleted')}"
                             + (f" {body.get('error', {}).get('code')}" if status >= 400 else ""))

    def run(self) -> int:
        self._boot()
        self._team_and_owner()
        try:
            if self.step_connect() and self.step_onboarding():
                paid = self.step_checkout()
                if paid:
                    self.step_webhook(*paid)
                if self.args.fee_percent:
                    self.step_fee()
        finally:
            self.cleanup()
            self.db.close()
        failed = self.report.failed
        print(f"\n{len(self.report.rows) - len(failed)}/{len(self.report.rows)} steps passed", flush=True)
        return 1 if failed or len(self.report.rows) < 4 else 0


if __name__ == "__main__":
    sys.exit(main())
