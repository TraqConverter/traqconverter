"""DEPLOY.md and .env.example name everything production needs."""
from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = (BACKEND / ".env.example").read_text()
DEPLOY = (BACKEND.parent / "DEPLOY.md").read_text()


def _example_keys() -> set:
    return {
        line.lstrip("# ").split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.splitlines()
        if "=" in line and not line.lstrip("# ").startswith("-")
    }


def test_env_example_lists_every_required_setting():
    required = {name for name, field in Settings.model_fields.items() if field.is_required()}
    assert required - _example_keys() == set()


@pytest.mark.parametrize("key", ["FRONTEND_URL", "RESEND_API_KEY", "RESEND_FROM_EMAIL", "STRIPE_CONNECT_WEBHOOK_SECRET"])
def test_settings_without_a_production_default_are_documented(key):
    assert key in _example_keys()
    assert f"`{key}`" in DEPLOY


@pytest.mark.parametrize("event", [
    "checkout.session.completed",
    "invoice.payment_succeeded",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "checkout.session.async_payment_succeeded",
    "account.updated",
    "account.application.deauthorized",
])
def test_deploy_guide_subscribes_every_handled_stripe_event(event):
    assert f"`{event}`" in DEPLOY


def test_deploy_guide_has_both_webhook_endpoints():
    assert "/stripe/webhook" in DEPLOY
    assert "/stripe/connect/webhook" in DEPLOY
