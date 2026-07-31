"""Tests de l'audit d'extractibilite des plaquettes."""

from pathlib import Path

import pytest

from src.ingestion.pdf_audit import (
    ENGLISH_SLUGS,
    DocumentAudit,
    apply_exclusions,
    classify,
    write_audit,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("chars_per_page", "attendu"),
    [(0, "IMAGE"), (49, "IMAGE"), (50, "MIXTE"), (399, "MIXTE"), (400, "TEXTE"), (2579, "TEXTE")],
)
def test_classify_respects_thresholds(chars_per_page: int, attendu: str) -> None:
    """La classification respecte les seuils 400 et 50 caracteres par page."""
    assert classify(chars_per_page) == attendu


@pytest.mark.unit
def test_english_documents_are_excluded() -> None:
    """Les trois plaquettes anglaises portent un motif d'exclusion."""
    audits = [
        DocumentAudit(filename=slug, md5=f"h{i}", pages=4, chars_per_page=0, kind="IMAGE")
        for i, slug in enumerate(sorted(ENGLISH_SLUGS))
    ]

    resultat = apply_exclusions(audits)

    assert len(resultat) == len(ENGLISH_SLUGS)
    for audit in resultat:
        assert audit.excluded_reason == "document en anglais"
        assert audit.language == "en"


@pytest.mark.unit
def test_duplicates_are_flagged_by_md5() -> None:
    """Le second document d'un meme hash est marque comme doublon du premier."""
    audits = [
        DocumentAudit(filename="A.pdf", md5="hash-identique", pages=2, chars_per_page=900, kind="TEXTE"),
        DocumentAudit(filename="B.pdf", md5="hash-identique", pages=2, chars_per_page=900, kind="TEXTE"),
        DocumentAudit(filename="C.pdf", md5="autre-hash", pages=1, chars_per_page=0, kind="IMAGE"),
    ]

    resultat = apply_exclusions(audits)
    par_nom = {a.filename: a for a in resultat}

    assert par_nom["A.pdf"].is_duplicate_of is None
    assert par_nom["B.pdf"].is_duplicate_of == "A.pdf"
    assert par_nom["B.pdf"].excluded_reason == "doublon exact de A.pdf"
    assert par_nom["C.pdf"].is_duplicate_of is None
    assert par_nom["C.pdf"].excluded_reason is None


@pytest.mark.unit
def test_write_audit_produces_readable_json(tmp_path: Path) -> None:
    """Le rapport d'audit est ecrit en JSON UTF-8 relisible."""
    import json

    audits = [DocumentAudit(filename="PERFECT.pdf", md5="abc", pages=4, chars_per_page=0, kind="IMAGE")]
    dest = tmp_path / "audit.json"

    write_audit(audits, dest)

    charge = json.loads(dest.read_text(encoding="utf-8"))
    assert charge[0]["filename"] == "PERFECT.pdf"
    assert charge[0]["kind"] == "IMAGE"
