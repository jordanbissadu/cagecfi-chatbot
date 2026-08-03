"""Tests des fiches produit structurees."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
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
    """Une fiche sans listes ne rend aucune section orpheline."""
    sheet = ProductSheet(
        product="VISUEL", category="corporate", target_audience=[],
        features=[], benefits=[], summary="Plaquette institutionnelle.",
    )

    rendu = sheet_to_markdown(sheet)

    assert "# VISUEL" in rendu
    assert "Plaquette institutionnelle." in rendu
    assert "## Pour qui" not in rendu
    assert "## Fonctionnalites" not in rendu
    assert "## Benefices" not in rendu


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_sheet_does_not_truncate_below_max_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un document de 30 000 caracteres est envoye en entier au LLM.

    Deux plaquettes du corpus (24502 et 21828 caracteres) depassaient l'ancien
    seuil de troncature (12000 caracteres) : la moitie de leur contenu
    n'atteignait jamais le modele. Ce test echoue si le markdown envoye au
    LLM est coupe avant sa fin.
    """
    import src.ingestion.product_sheet as mod
    from src.settings_supabase import SupabaseSettings

    markdown = "A" * 30000
    captured: dict[str, str] = {}

    async def fake_create(**kwargs: object) -> MagicMock:
        messages = kwargs["messages"]
        captured["content"] = messages[0]["content"]  # type: ignore[index]
        payload = json.dumps(
            {
                "product": "TEST", "category": "corporate",
                "target_audience": [], "features": [], "benefits": [],
                "summary": "Resume de test.",
            }
        )
        return MagicMock(choices=[MagicMock(message=MagicMock(content=payload))])

    fake_client = MagicMock()
    fake_client.chat.completions.create = fake_create
    monkeypatch.setattr(mod.openai, "AsyncOpenAI", lambda **kwargs: fake_client)

    sheet = await mod.build_sheet(markdown, "slug-test", SupabaseSettings())

    assert sheet is not None
    assert markdown in captured["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_all_sheets_continues_after_parsing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une erreur de parsing sur une plaquette n'interrompt pas le traitement des suivantes.

    Sans le correctif, l'exception levee par ``frontmatter.loads`` remonte
    hors de ``build_all_sheets`` et empeche le traitement des documents
    suivants : ce test echoue si l'appel n'est pas protege par un try/except
    cible.
    """
    import frontmatter

    import src.ingestion.product_sheet as mod

    (tmp_path / "A.md").write_text("# A\n\nContenu A", encoding="utf-8")
    (tmp_path / "B.md").write_text("# B\n\nContenu B", encoding="utf-8")
    (tmp_path / "C.md").write_text("# C\n\nContenu C", encoding="utf-8")

    original_loads = frontmatter.loads

    def fake_loads(text: str, *args: object, **kwargs: object) -> frontmatter.Post:
        if "Contenu B" in text:
            raise yaml.YAMLError("front-matter invalide (simule)")
        return original_loads(text, *args, **kwargs)

    monkeypatch.setattr(mod.frontmatter, "loads", fake_loads)
    monkeypatch.setattr(mod, "load_settings", lambda: object())

    async def fake_build_sheet(
        markdown: str, slug: str, settings: object
    ) -> ProductSheet:
        return ProductSheet(
            product=slug, category="corporate", target_audience=[],
            features=[], benefits=[], summary="Resume de test.",
        )

    monkeypatch.setattr(mod, "build_sheet", fake_build_sheet)

    ecrites = await mod.build_all_sheets(tmp_path)

    noms = {p.stem for p in ecrites}
    assert noms == {"A_fiche", "C_fiche"}
