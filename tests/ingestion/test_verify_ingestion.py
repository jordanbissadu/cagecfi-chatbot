"""Tests de la recette post-ingestion."""

import pytest

from src.ingestion.verify_ingestion import IngestionCheck, summarize_checks


@pytest.mark.unit
def test_summarize_flags_document_without_chunks() -> None:
    """Un document sans chunk fait echouer la recette."""
    checks = [
        IngestionCheck(title="PERFECT", chunks=12, passed=True),
        IngestionCheck(title="GOMISE", chunks=0, passed=False),
    ]

    ok, message = summarize_checks(checks)

    assert ok is False
    assert "GOMISE" in message


@pytest.mark.unit
def test_summarize_passes_when_all_documents_have_chunks() -> None:
    """La recette passe quand chaque document porte au moins un chunk."""
    checks = [
        IngestionCheck(title="PERFECT", chunks=12, passed=True),
        IngestionCheck(title="GOMISE", chunks=7, passed=True),
    ]

    ok, message = summarize_checks(checks)

    assert ok is True
    assert "2" in message


@pytest.mark.unit
def test_summarize_handles_empty_base() -> None:
    """Une base vide echoue la recette plutot que de passer par defaut."""
    ok, message = summarize_checks([])

    assert ok is False
    assert "aucun document" in message.lower()
