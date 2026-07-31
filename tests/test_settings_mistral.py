"""Tests de la configuration Mistral OCR."""

import os

import pytest

from src.settings_supabase import SupabaseSettings


@pytest.mark.unit
def test_mistral_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """La cle et le modele Mistral sont lus depuis l'environnement."""
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-de-test")
    monkeypatch.setenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

    settings = SupabaseSettings()

    assert settings.mistral_api_key == "cle-de-test"
    assert settings.mistral_ocr_model == "mistral-ocr-latest"


@pytest.mark.unit
def test_mistral_ocr_model_has_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le modele OCR possede une valeur par defaut."""
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-de-test")
    monkeypatch.delenv("MISTRAL_OCR_MODEL", raising=False)

    settings = SupabaseSettings()

    assert settings.mistral_ocr_model == "mistral-ocr-latest"
