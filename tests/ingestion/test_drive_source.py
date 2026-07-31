"""Tests de l'inventaire et du telechargement Drive."""

from pathlib import Path

import pytest

from src.ingestion.drive_source import DRIVE_FILES, is_complete_pdf


@pytest.mark.unit
def test_inventory_has_32_unique_entries() -> None:
    """L'inventaire couvre les 32 fichiers du Drive (31 PDF + 1 JPG), sans doublon d'id."""
    assert len(DRIVE_FILES) == 32
    assert len({f.drive_id for f in DRIVE_FILES}) == 32
    assert len({f.slug for f in DRIVE_FILES}) == 32


@pytest.mark.unit
def test_inventory_contains_31_pdfs() -> None:
    """Les 31 plaquettes PDF sont presentes ; seul l'encart est une image."""
    pdfs = [f for f in DRIVE_FILES if f.slug.endswith(".pdf")]
    assert len(pdfs) == 31
    assert "VISUEL_CAGECFI.pdf" in {f.slug for f in pdfs}


@pytest.mark.unit
def test_slugs_are_filesystem_safe() -> None:
    """Les slugs ne contiennent ni espace, ni virgule, ni accent."""
    for item in DRIVE_FILES:
        assert " " not in item.slug
        assert "," not in item.slug
        assert item.slug.isascii()
        assert item.slug.endswith((".pdf", ".jpg"))


@pytest.mark.unit
def test_is_complete_pdf_detects_truncated_file(tmp_path: Path) -> None:
    """Un PDF sans marqueur %%EOF est considere incomplet."""
    complet = tmp_path / "complet.pdf"
    complet.write_bytes(b"%PDF-1.4\nblabla\n%%EOF\n")

    tronque = tmp_path / "tronque.pdf"
    tronque.write_bytes(b"%PDF-1.4\nblabla sans fin")

    assert is_complete_pdf(complet) is True
    assert is_complete_pdf(tronque) is False


@pytest.mark.unit
def test_is_complete_pdf_handles_missing_file(tmp_path: Path) -> None:
    """Un fichier absent est considere incomplet, sans lever d'exception."""
    assert is_complete_pdf(tmp_path / "absent.pdf") is False
