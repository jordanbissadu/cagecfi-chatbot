"""Tests des metadonnees d'ingestion des plaquettes."""

from pathlib import Path

import pytest

from src.ingestion.ingest_supabase import (
    DocumentIngestionPipeline,
    IngestionConfig,
    read_plaquette_markdown,
)


@pytest.mark.unit
def test_read_plaquette_markdown_separates_front_matter(tmp_path: Path) -> None:
    """Le front-matter est retire du contenu et rendu comme metadonnees."""
    fichier = tmp_path / "PERFECT.md"
    fichier.write_text(
        "---\n"
        "source_file: PERFECT.pdf\n"
        "extraction: mistral_ocr\n"
        "image_ratio: 0.75\n"
        "extracted_at: '2026-07-31'\n"
        "---\n"
        "# PERFECT\n\nGestion de la clientele\n",
        encoding="utf-8",
    )

    contenu, meta = read_plaquette_markdown(fichier)

    assert contenu.startswith("# PERFECT")
    assert "source_file" not in contenu
    assert meta["source_file"] == "PERFECT.pdf"
    assert meta["extraction"] == "mistral_ocr"
    assert meta["image_ratio"] == 0.75


@pytest.mark.unit
def test_read_plaquette_markdown_without_front_matter(tmp_path: Path) -> None:
    """Un markdown sans front-matter est lu tel quel, avec des metadonnees vides."""
    fichier = tmp_path / "simple.md"
    fichier.write_text("# Titre\n\nTexte\n", encoding="utf-8")

    contenu, meta = read_plaquette_markdown(fichier)

    assert contenu.strip() == "# Titre\n\nTexte"
    assert meta == {}


@pytest.mark.unit
def test_document_metadata_carries_extraction_provenance(tmp_path: Path) -> None:
    """Les metadonnees du document conservent la provenance d'extraction."""
    fichier = tmp_path / "GOMISE.md"
    fichier.write_text(
        "---\nsource_file: GOMISE.pdf\nextraction: mistral_ocr\nimage_ratio: 3.5\n---\n# GOMISE\n\nTexte\n",
        encoding="utf-8",
    )
    pipeline = DocumentIngestionPipeline.__new__(DocumentIngestionPipeline)

    contenu, front = read_plaquette_markdown(fichier)
    meta = pipeline._extract_document_metadata(contenu, str(fichier), front)

    assert meta["extraction"] == "mistral_ocr"
    assert meta["source_file"] == "GOMISE.pdf"
    assert meta["image_ratio"] == 3.5
    assert meta["doc_type"] == "chunk"
    assert meta["file_name"] == "GOMISE.md"


@pytest.mark.unit
def test_document_metadata_product_sheet_overrides_doc_type(tmp_path: Path) -> None:
    """Le front-matter d'une fiche produit ecrase le doc_type par defaut."""
    fichier = tmp_path / "SOLUTION_fiche.md"
    fichier.write_text(
        "---\n"
        "category: finance_digitale\n"
        "doc_type: product_sheet\n"
        "extraction: product_sheet\n"
        "product: Solutions de finance digitale\n"
        "source_file: SOLUTION.pdf\n"
        "---\n"
        "# Solutions de finance digitale\n\nTexte\n",
        encoding="utf-8",
    )
    pipeline = DocumentIngestionPipeline.__new__(DocumentIngestionPipeline)

    contenu, front = read_plaquette_markdown(fichier)
    meta = pipeline._extract_document_metadata(contenu, str(fichier), front)

    assert meta["doc_type"] == "product_sheet"
    assert meta["product"] == "Solutions de finance digitale"
    assert meta["category"] == "finance_digitale"
    assert meta["source_file"] == "SOLUTION.pdf"


@pytest.mark.unit
def test_document_metadata_without_front_matter_defaults_to_chunk(tmp_path: Path) -> None:
    """Sans front-matter (dict vide ou None), le doc_type par defaut reste 'chunk'."""
    fichier = tmp_path / "simple.md"
    fichier.write_text("# Titre\n\nTexte\n", encoding="utf-8")
    pipeline = DocumentIngestionPipeline.__new__(DocumentIngestionPipeline)

    contenu, front = read_plaquette_markdown(fichier)
    meta_avec_dict_vide = pipeline._extract_document_metadata(contenu, str(fichier), front)
    meta_sans_argument = pipeline._extract_document_metadata(contenu, str(fichier))

    assert front == {}
    assert meta_avec_dict_vide["doc_type"] == "chunk"
    assert meta_sans_argument["doc_type"] == "chunk"
