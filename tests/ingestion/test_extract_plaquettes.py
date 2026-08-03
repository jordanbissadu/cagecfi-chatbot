"""Tests de l'extraction routee des plaquettes."""

import json
from pathlib import Path

import pytest

from src.ingestion.extract_plaquettes import (
    ExtractionResult,
    clean_markdown_images,
    extract_all,
    route_extraction_method,
    write_markdown,
)
from src.ingestion.pdf_audit import DocumentAudit


@pytest.mark.unit
def test_write_markdown_includes_front_matter(tmp_path: Path) -> None:
    """Le markdown ecrit porte un front-matter tracant la provenance."""
    import frontmatter

    result = ExtractionResult(
        filename="PERFECT.pdf",
        slug="PERFECT",
        method="mistral_ocr",
        markdown="# PERFECT\n\nGestion de la clientele",
        image_ratio=0.75,
    )

    chemin = write_markdown(result, tmp_path)
    charge = frontmatter.loads(chemin.read_text(encoding="utf-8"))

    assert chemin.name == "PERFECT.md"
    assert charge["source_file"] == "PERFECT.pdf"
    assert charge["extraction"] == "mistral_ocr"
    assert charge["image_ratio"] == 0.75
    assert "Gestion de la clientele" in charge.content


@pytest.mark.unit
def test_clean_markdown_images_removes_refs_and_comments_keeps_text() -> None:
    """Les references d'images disparaissent, le texte utile est intact.

    Couvre les deux voies d'extraction : `![img-0.jpeg](img-0.jpeg)`
    (Mistral OCR) et `<!-- image -->` (Docling).
    """
    brut = (
        "# CAGECFI\n\n"
        "![img-0.jpeg](img-0.jpeg)\n\n"
        "QUI SOMMES-NOUS ?\n\n"
        "CAGECFI est une societe creee en 2001 a Lomé.\n\n"
        "<!-- image -->\n\n"
        "![img-1.jpeg](img-1.jpeg)\n\n"
        "À PROPOS\n"
    )

    propre = clean_markdown_images(brut)

    assert "img-0.jpeg" not in propre
    assert "img-1.jpeg" not in propre
    assert "<!-- image -->" not in propre
    assert "![" not in propre
    assert "CAGECFI est une societe creee en 2001 a Lomé." in propre
    assert "QUI SOMMES-NOUS ?" in propre
    assert "À PROPOS" in propre
    assert "\n\n\n" not in propre


@pytest.mark.unit
def test_write_markdown_strips_image_references_from_disk_content(
    tmp_path: Path,
) -> None:
    """Le fichier ecrit sur disque ne porte plus de references d'images."""
    import frontmatter

    result = ExtractionResult(
        filename="CAGECFI.pdf",
        slug="CAGECFI",
        method="mistral_ocr",
        markdown="# CAGECFI\n\n![img-0.jpeg](img-0.jpeg)\n\nQUI SOMMES-NOUS ?\n",
        image_ratio=1.0,
    )

    chemin = write_markdown(result, tmp_path)
    charge = frontmatter.loads(chemin.read_text(encoding="utf-8"))

    assert "img-0.jpeg" not in charge.content
    assert "QUI SOMMES-NOUS ?" in charge.content
    # image_ratio reste celui calcule sur le markdown brut, pas recalcule.
    assert charge["image_ratio"] == 1.0


@pytest.mark.unit
def test_write_markdown_skips_failed_extraction(tmp_path: Path) -> None:
    """Une extraction en echec n'ecrit aucun fichier."""
    result = ExtractionResult(
        filename="CASSE.pdf", slug="CASSE", method="mistral_ocr",
        markdown="", image_ratio=0.0, error="HTTP 500",
    )

    with pytest.raises(ValueError, match="echec"):
        write_markdown(result, tmp_path)

    assert list(tmp_path.glob("*.md")) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "attendu"),
    [
        ("TEXTE", "docling"),
        ("MIXTE", "mistral_ocr"),
        ("IMAGE", "mistral_ocr"),
    ],
)
def test_route_extraction_method_verrouille_le_routage(
    kind: str, attendu: str
) -> None:
    """TEXTE seul emprunte Docling ; MIXTE et IMAGE vont a Mistral OCR.

    En dessous de 400 caracteres/page, la couche texte est trop pauvre pour
    Docling : mesure sur l'unique document MIXTE du corpus (15 mots reels et
    texte mutile via Docling, contre 177 mots propres via Mistral OCR).
    """
    assert route_extraction_method(kind) == attendu  # type: ignore[arg-type]


@pytest.mark.unit
def test_extraction_result_rejects_unknown_method() -> None:
    """La methode d'extraction est contrainte aux deux voies prevues."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionResult(
            filename="X.pdf", slug="X", method="tesseract",  # type: ignore[arg-type]
            markdown="", image_ratio=0.0,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_all_continues_after_write_markdown_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une erreur d'ecriture disque sur un document n'interrompt pas le lot.

    Sans le correctif, l'OSError leve par `write_markdown` remonte hors de
    `extract_all` et empeche le traitement des documents suivants : ce test
    echoue si l'appel n'est pas protege par un try/except cible.
    """
    import src.ingestion.extract_plaquettes as mod

    audits = [
        DocumentAudit(filename="A.pdf", md5="a", pages=1, chars_per_page=500, kind="TEXTE"),
        DocumentAudit(filename="B.pdf", md5="b", pages=1, chars_per_page=500, kind="TEXTE"),
        DocumentAudit(filename="C.pdf", md5="c", pages=1, chars_per_page=500, kind="TEXTE"),
    ]
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps([a.model_dump() for a in audits]), encoding="utf-8"
    )
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    dest_dir = tmp_path / "md"

    async def fake_extract_document(
        audit: DocumentAudit, pdf_dir: Path, settings: object
    ) -> ExtractionResult:
        return ExtractionResult(
            filename=audit.filename,
            slug=Path(audit.filename).stem,
            method="docling",
            markdown=f"# {audit.filename}",
        )

    original_write_markdown = mod.write_markdown

    def fake_write_markdown(result: ExtractionResult, dest_dir_arg: Path) -> Path:
        if result.filename == "B.pdf":
            raise OSError("disque plein")
        return original_write_markdown(result, dest_dir_arg)

    monkeypatch.setattr(mod, "extract_document", fake_extract_document)
    monkeypatch.setattr(mod, "load_settings", lambda: object())
    monkeypatch.setattr(mod, "write_markdown", fake_write_markdown)

    resultats = await extract_all(pdf_dir, audit_path, dest_dir)

    par_nom = {r.filename: r for r in resultats}
    assert len(resultats) == 3
    assert par_nom["A.pdf"].succeeded
    assert par_nom["C.pdf"].succeeded
    assert not par_nom["B.pdf"].succeeded
    assert "disque plein" in (par_nom["B.pdf"].error or "")
    assert (dest_dir / "A.md").exists()
    assert (dest_dir / "C.md").exists()
    assert not (dest_dir / "B.md").exists()
