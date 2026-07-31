"""Tests de l'extraction routee des plaquettes."""

from pathlib import Path

import pytest

from src.ingestion.extract_plaquettes import ExtractionResult, write_markdown


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
def test_extraction_result_rejects_unknown_method() -> None:
    """La methode d'extraction est contrainte aux deux voies prevues."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionResult(
            filename="X.pdf", slug="X", method="tesseract",  # type: ignore[arg-type]
            markdown="", image_ratio=0.0,
        )
