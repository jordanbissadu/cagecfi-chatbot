"""Tests des fiches produit structurees."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ingestion.product_sheet import ProductSheet, sheet_to_markdown


@pytest.mark.unit
def test_product_sheet_requires_known_category() -> None:
    """Une categorie hors taxonomie est rejetee."""
    with pytest.raises(ValidationError):
        ProductSheet(
            product="PERFECT", category="inconnue",  # type: ignore[arg-type]
            target_audience=["SFD"], features=["Gestion de la clientele"],
            benefits=["Automatisation"], summary="Logiciel de gestion integre.",
        )


@pytest.mark.unit
def test_sheet_to_markdown_renders_all_sections() -> None:
    """La fiche rendue expose le produit, la cible, les fonctionnalites et les benefices."""
    sheet = ProductSheet(
        product="PERFECT",
        category="core_banking",
        target_audience=["Systemes financiers decentralises", "Institutions de microfinance"],
        features=["Gestion de la clientele", "Gestion du portefeuille-credit"],
        benefits=["Automatisation des transactions"],
        summary="Logiciel de gestion integre des systemes financiers decentralises.",
    )

    rendu = sheet_to_markdown(sheet)

    assert "# PERFECT" in rendu
    assert "core_banking" in rendu
    assert "Institutions de microfinance" in rendu
    assert "Gestion du portefeuille-credit" in rendu
    assert "Automatisation des transactions" in rendu


@pytest.mark.unit
def test_sheet_to_markdown_handles_empty_lists() -> None:
    """Une fiche sans benefice reste rendue sans lever d'erreur."""
    sheet = ProductSheet(
        product="VISUEL", category="corporate", target_audience=[],
        features=[], benefits=[], summary="Plaquette institutionnelle.",
    )

    rendu = sheet_to_markdown(sheet)

    assert "# VISUEL" in rendu
    assert "Plaquette institutionnelle." in rendu


@pytest.mark.unit
def test_write_sheet_marks_doc_type_product_sheet(tmp_path: Path) -> None:
    """La fiche ecrite porte doc_type=product_sheet dans son front-matter."""
    import frontmatter

    from src.ingestion.product_sheet import write_sheet

    sheet = ProductSheet(
        product="PERFECT", category="core_banking",
        target_audience=["SFD"], features=["Gestion de la clientele"],
        benefits=["Automatisation"], summary="Logiciel de gestion integre.",
    )

    chemin = write_sheet(sheet, "PERFECT", tmp_path)
    charge = frontmatter.loads(chemin.read_text(encoding="utf-8"))

    assert chemin.name == "PERFECT_fiche.md"
    assert charge["doc_type"] == "product_sheet"
    assert charge["product"] == "PERFECT"
    assert charge["category"] == "core_banking"
    assert "Gestion de la clientele" in charge.content
