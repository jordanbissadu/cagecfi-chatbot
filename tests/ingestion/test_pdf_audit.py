"""Tests de l'audit d'extractibilite des plaquettes."""

from pathlib import Path

import pytest

from src.ingestion.pdf_audit import (
    ENGLISH_SLUGS,
    DocumentAudit,
    apply_exclusions,
    audit_pdf,
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
def test_duplicate_of_excluded_document_is_also_excluded() -> None:
    """Un doublon d'un document exclu est aussi exclu, meme s'il n'est pas anglais."""
    # Simulation: un document anglais vient en premier (alphabétiquement)
    # Son doublon non-anglais vient après
    audits = [
        DocumentAudit(filename="CORE_BANKING_PERFECT_ENG.pdf", md5="same-hash", pages=2, chars_per_page=0, kind="IMAGE"),
        DocumentAudit(filename="Z_duplicate_of_eng.pdf", md5="same-hash", pages=2, chars_per_page=0, kind="IMAGE"),
    ]

    resultat = apply_exclusions(audits)
    par_nom = {a.filename: a for a in resultat}

    # Le document anglais est exclu pour "document en anglais"
    assert par_nom["CORE_BANKING_PERFECT_ENG.pdf"].excluded_reason == "document en anglais"
    assert par_nom["CORE_BANKING_PERFECT_ENG.pdf"].language == "en"

    # Son doublon doit être aussi exclu pour "doublon exact de..."
    # (même s'il n'est pas dans ENGLISH_SLUGS)
    assert par_nom["Z_duplicate_of_eng.pdf"].is_duplicate_of == "CORE_BANKING_PERFECT_ENG.pdf"
    assert par_nom["Z_duplicate_of_eng.pdf"].excluded_reason == "doublon exact de CORE_BANKING_PERFECT_ENG.pdf"
    assert par_nom["Z_duplicate_of_eng.pdf"].language == "fr"  # Défaut, pas marqué anglais


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


@pytest.mark.unit
def test_audit_pdf_handles_corrupted_files(tmp_path: Path) -> None:
    """Un PDF corrompu ne leve pas d'exception, mais est route vers l'OCR."""
    # Créer un fichier qui ne contient pas un PDF valide
    pdf_path = tmp_path / "corrupted.pdf"
    pdf_path.write_bytes(b"This is not a valid PDF\x00\xff")

    # audit_pdf doit gérer l'erreur gracieusement
    result = audit_pdf(pdf_path)

    assert result.filename == "corrupted.pdf"
    assert result.pages == -1
    assert result.chars_per_page == 0
    assert result.kind == "IMAGE"
    assert result.md5 is not None and len(result.md5) == 32  # MD5 hex = 32 chars


@pytest.mark.unit
def test_audit_pdf_ignores_unmapped_glyphs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Des glyphes non mappes (/gidNNNNN, (cid:NN)) ne comptent pas comme texte exploitable.

    Ces motifs sont produits par pypdf sur les polices vectorisees sans table
    Unicode : ils contiennent des lettres alphabetiques ("g", "i", "d") qui,
    non filtrees, gonflent artificiellement chars_per_page et font router le
    document vers Docling au lieu de l'OCR.
    """

    class FakePage:
        """Page factice renvoyant du texte compose uniquement de glyphes non mappes."""

        def extract_text(self) -> str:
            return "/gid00010/gid00015/gid00020" * 50 + "(cid:12)(cid:34)"

    class FakeReader:
        """Lecteur factice imitant l'interface pypdf.PdfReader utilisee par audit_pdf."""

        def __init__(self, _path: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("src.ingestion.pdf_audit.PdfReader", FakeReader)

    pdf_path = tmp_path / "glyphes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 contenu factice")

    result = audit_pdf(pdf_path)

    assert result.chars_per_page == 0
    assert result.kind == "IMAGE"


@pytest.mark.unit
def test_audit_pdf_reads_valid_minimal_pdf(tmp_path: Path) -> None:
    """Un PDF minimal valide est lu correctement."""
    import io

    from pypdf import PdfWriter

    # Créer un PDF minimal avec une page vide
    pdf_path = tmp_path / "valid_minimal.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_path.write_bytes(pdf_bytes.getvalue())

    result = audit_pdf(pdf_path)

    assert result.filename == "valid_minimal.pdf"
    assert result.pages >= 1
    assert result.md5 is not None and len(result.md5) == 32  # MD5 hex
    assert result.kind in ("TEXTE", "MIXTE", "IMAGE")  # Classification valide
