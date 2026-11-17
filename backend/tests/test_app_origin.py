"""The app runs on its own host; the API must accept it and let it frame the source preview."""
from app.config import Settings, settings


def test_default_cors_allows_the_app_host():
    assert "https://app.onlinedoctranslator.ai" in Settings.model_fields["CORS_ORIGINS"].default.split(",")


def test_frontend_origin_drops_path_and_slash():
    s = settings.model_copy(update={"FRONTEND_URL": "https://app.onlinedoctranslator.ai/"})
    assert s.frontend_origin == "https://app.onlinedoctranslator.ai"
    assert settings.model_copy(update={"FRONTEND_URL": ""}).frontend_origin == ""


def test_preview_can_be_framed_by_the_frontend(client):
    # Only after the client fixture: importing app.main any earlier breaks caplog in later tests.
    from app import main

    assert settings.frontend_origin
    assert settings.frontend_origin in main._PREVIEW_FRAME_ANCESTORS.split()
    assert "  " not in main._PREVIEW_FRAME_ANCESTORS
