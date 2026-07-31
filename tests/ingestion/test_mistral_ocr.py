"""Tests du client Mistral OCR et du nettoyage des artefacts."""

import pytest

from src.ingestion.mistral_ocr import OcrPage, OcrResult, clean_artifacts


@pytest.mark.unit
def test_clean_artifacts_removes_latex_bullets() -> None:
    """Les puces LaTeX produites par l'OCR sont supprimees."""
    brut = "\\(\\odot\\) Administrations publiques\n\\(\\mathbb{O}\\) Serveur local"

    propre = clean_artifacts(brut)

    assert "\\odot" not in propre
    assert "mathbb" not in propre
    assert "Administrations publiques" in propre
    assert "Serveur local" in propre


@pytest.mark.unit
def test_clean_artifacts_preserves_normal_markdown() -> None:
    """Le markdown legitime traverse le nettoyage sans alteration."""
    brut = "# FONCTIONNALITES GENERALES\n\nGestion de la clientele\n"

    assert clean_artifacts(brut) == brut


@pytest.mark.unit
def test_clean_artifacts_collapses_blank_lines() -> None:
    """Les lignes vides laissees par la suppression des puces sont compactees."""
    brut = "Titre\n\n\n\n\nSuite"

    assert clean_artifacts(brut) == "Titre\n\nSuite"


@pytest.mark.unit
def test_ocr_result_computes_image_ratio() -> None:
    """Le ratio d'images rapporte les references d'images au nombre de pages."""
    result = OcrResult(
        pages=[
            OcrPage(index=0, markdown="# Titre\n![img-0.jpeg](img-0.jpeg)", image_refs=1),
            OcrPage(index=1, markdown="![img-1.jpeg](img-1.jpeg)\n![img-2.jpeg](img-2.jpeg)", image_refs=2),
        ],
        markdown="peu importe",
    )

    assert result.image_ratio == pytest.approx(1.5)


@pytest.mark.unit
def test_ocr_result_image_ratio_is_zero_without_pages() -> None:
    """Un resultat vide ne provoque pas de division par zero."""
    assert OcrResult(pages=[], markdown="").image_ratio == 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ocr_pdf_on_real_document() -> None:
    """Appel reel a l'API sur une plaquette connue du corpus."""
    from pathlib import Path

    from src.ingestion.mistral_ocr import ocr_pdf
    from src.settings_supabase import load_settings

    chemin = Path("documents/plaquettes/PERFECT.pdf")
    if not chemin.exists():
        pytest.skip("Corpus absent : lancer d'abord src.ingestion.drive_source")

    result = await ocr_pdf(chemin, load_settings())

    assert len(result.pages) == 4
    assert "PERFECT" in result.markdown
    assert "Gestion de la clientèle" in result.markdown
    assert "\\odot" not in result.markdown
