# Pipeline d'ingestion des plaquettes CAGECFI — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la base de connaissance du chatbot CAGECFI par le contenu des 22 plaquettes commerciales retenues, extraites via un routage Docling / Mistral OCR dicté par un audit d'extractibilité.

**Architecture:** Cinq modules autonomes chaînés par des artefacts sur disque (PDF → audit JSON → markdown → base). Chaque étape est rejouable seule : on peut ré-ingérer sans refaire l'OCR. Un point de contrôle humain sépare l'extraction de la vectorisation, parce que 94 % du contenu transite par un OCR.

**Tech Stack:** Python 3.13, UV, httpx, Pydantic v2, Docling, Mistral OCR (`mistral-ocr-latest`), asyncpg, Supabase/pgvector, pytest.

**Spec de référence :** [`docs/superpowers/specs/2026-07-31-ingestion-plaquettes-cagecfi-design.md`](../specs/2026-07-31-ingestion-plaquettes-cagecfi-design.md)

## Global Constraints

- **Annotations de type obligatoires** sur toute fonction, méthode et variable. Pas de `Any` sans justification explicite en commentaire.
- **Docstrings Google-style** pour tout module, classe et fonction publique.
- **Async pour toute I/O** : appels HTTP, PostgreSQL, embeddings. Nettoyage via `try/finally` ou gestionnaire de contexte.
- **Pydantic v2** pour toute structure de données échangée entre modules.
- **Aucune dépendance lourde dans les dépendances runtime** de `pyproject.toml` : le runtime Vercel ne doit embarquer ni Docling, ni Whisper, ni client OCR. Tout va dans l'extra `[ingestion]`.
- **Embeddings** : `text-embedding-3-small`, dimension **1536**, provider OpenAI (déjà configuré dans `.env`).
- **Tables** : `cagecfi_documents` et `cagecfi_chunks`, toujours lues depuis `settings.postgres_table_documents` / `settings.postgres_table_chunks`, jamais en dur.
- **Langue** : le corpus retenu est exclusivement français. Les 3 plaquettes anglaises sont exclues.
- **Un échec sur un document ne doit jamais interrompre le traitement des autres.** Journaliser, poursuivre, et lister les échecs en fin d'exécution.
- Le répertoire `tests/` est actuellement vide : créer `tests/__init__.py` et `tests/ingestion/__init__.py` à la première tâche qui en a besoin.

---

## Structure des fichiers

| Fichier | Responsabilité |
| --- | --- |
| `src/ingestion/drive_source.py` | Inventaire figé du Drive et téléchargement vérifié |
| `src/ingestion/pdf_audit.py` | Classification TEXTE/MIXTE/IMAGE, hash, dédoublonnage, exclusions |
| `src/ingestion/mistral_ocr.py` | Client Mistral OCR et nettoyage des artefacts |
| `src/ingestion/extract_plaquettes.py` | Orchestration du routage et écriture des markdown |
| `src/ingestion/product_sheet.py` | Génération des fiches produit structurées |
| `src/settings_supabase.py` | *(modifié)* configuration Mistral |
| `src/ingestion/ingest_supabase.py` | *(modifié)* lecture du front-matter, métadonnées enrichies, recette |
| `pyproject.toml` | *(modifié)* dépendances de l'extra `ingestion` |

---

### Task 1: Configuration Mistral et dépendances

**Files:**
- Modify: `src/settings_supabase.py:104` (après `default_text_weight`)
- Modify: `pyproject.toml` (extra `ingestion`)
- Create: `tests/__init__.py`, `tests/ingestion/__init__.py`
- Test: `tests/test_settings_mistral.py`

**Interfaces:**
- Consumes: rien
- Produces: `SupabaseSettings.mistral_api_key: str`, `SupabaseSettings.mistral_ocr_model: str`

- [ ] **Step 1: Créer les paquets de test**

```bash
mkdir -p tests/ingestion
touch tests/__init__.py tests/ingestion/__init__.py
```

- [ ] **Step 2: Écrire le test qui échoue**

Créer `tests/test_settings_mistral.py` :

```python
"""Tests de la configuration Mistral OCR."""

import os

import pytest

from src.settings_supabase import SupabaseSettings


@pytest.mark.unit
def test_mistral_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """La cle et le modele Mistral sont lus depuis l'environnement."""
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-de-test")
    monkeypatch.setenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

    settings = SupabaseSettings()

    assert settings.mistral_api_key == "cle-de-test"
    assert settings.mistral_ocr_model == "mistral-ocr-latest"


@pytest.mark.unit
def test_mistral_ocr_model_has_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le modele OCR possede une valeur par defaut."""
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-de-test")
    monkeypatch.delenv("MISTRAL_OCR_MODEL", raising=False)

    settings = SupabaseSettings()

    assert settings.mistral_ocr_model == "mistral-ocr-latest"
```

- [ ] **Step 3: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_settings_mistral.py -v`
Expected: FAIL — `AttributeError: 'SupabaseSettings' object has no attribute 'mistral_api_key'`

- [ ] **Step 4: Ajouter les champs dans `src/settings_supabase.py`**

Insérer juste après le champ `default_text_weight` (ligne 102-104) :

```python
    # Mistral OCR (ingestion locale uniquement, jamais appele depuis Vercel)
    mistral_api_key: str = Field(
        default="", description="Cle API Mistral pour l'OCR des plaquettes"
    )

    mistral_ocr_model: str = Field(
        default="mistral-ocr-latest", description="Modele OCR Mistral"
    )
```

- [ ] **Step 5: Lancer le test pour vérifier qu'il passe**

Run: `uv run pytest tests/test_settings_mistral.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Déclarer les dépendances d'ingestion**

Dans `pyproject.toml`, remplacer la liste `ingestion` par :

```toml
ingestion = [
    "docling>=2.14.0",
    "docling-core>=2.4.0",
    "transformers>=4.47.0",
    "openai-whisper>=20240930",
    "aiofiles>=24.1.0",
    "pypdf>=6.0.0",
    "python-frontmatter>=1.1.0",
]
```

`httpx` est déjà une dépendance runtime : ne pas la dupliquer.

- [ ] **Step 7: Installer et vérifier**

Run: `uv pip install -e ".[ingestion]"`
Then: `uv run python -c "import pypdf, frontmatter; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Déclarer les marqueurs pytest**

Ajouter à la fin de `pyproject.toml` si la section n'existe pas :

```toml
[tool.pytest.ini_options]
markers = [
    "unit: tests unitaires sans I/O reseau",
    "integration: tests necessitant un service externe",
]
asyncio_mode = "auto"
```

- [ ] **Step 9: Commit**

```bash
git add src/settings_supabase.py pyproject.toml tests/
git commit -m "feat: configuration Mistral OCR et dependances d'ingestion"
```

---

### Task 2: Inventaire et téléchargement du Drive

**Files:**
- Create: `src/ingestion/drive_source.py`
- Test: `tests/ingestion/test_drive_source.py`

**Interfaces:**
- Consumes: rien
- Produces:
  - `DriveFile` (Pydantic : `drive_id: str`, `original_name: str`, `slug: str`)
  - `DRIVE_FILES: list[DriveFile]` — inventaire figé de 32 entrées (31 PDF + 1 JPG)
  - `is_complete_pdf(path: Path) -> bool`
  - `download_file(client: httpx.AsyncClient, item: DriveFile, dest_dir: Path) -> Path`
  - `download_all(dest_dir: Path) -> list[Path]` (async)

**Contexte :** le dossier Drive est public. Deux téléchargements sur 31 sont arrivés tronqués lors de l'audit — la vérification d'intégrité n'est pas optionnelle.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_drive_source.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_drive_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.drive_source'`

- [ ] **Step 3: Implémenter `src/ingestion/drive_source.py`**

```python
"""Inventaire et telechargement des plaquettes commerciales depuis Google Drive.

Le dossier source est public :
https://drive.google.com/drive/folders/1C_FKZoXHt-ixNKbXnNzYLQQtb6DWJ3t-

L'inventaire est fige dans le module plutot que redecouvert a chaque execution :
le contenu du dossier est stable et le parsing du HTML de Drive est fragile.
"""

import asyncio
import logging
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={drive_id}"


class DriveFile(BaseModel):
    """Un fichier du dossier Drive des plaquettes."""

    drive_id: str = Field(..., description="Identifiant Google Drive")
    original_name: str = Field(..., description="Nom d'origine dans le Drive")
    slug: str = Field(..., description="Nom de fichier local, ASCII et sans espace")


DRIVE_FILES: list[DriveFile] = [
    DriveFile(drive_id="1jXDg6QDfb-zb5pP-4hA1pSRANHmxwV0W", original_name="CAGECFI Présentation_Insertion 21,5 x 27,5.pdf", slug="CAGECFI_Presentation_Insertion.pdf"),
    DriveFile(drive_id="178KYLq2ZJnOQncM_S7VLVjK72AqsM8dg", original_name="CAGECFI_PLAQUETTE PRESENTATION.pdf", slug="CAGECFI_PLAQUETTE_PRESENTATION.pdf"),
    DriveFile(drive_id="1NQ_8EXFvDalOJqfTfrQtA3eGEqsJAG2C", original_name="CAGECFI_QUI SOMMES NOUS.pdf", slug="CAGECFI_QUI_SOMMES_NOUS.pdf"),
    DriveFile(drive_id="10J6V1heLRTro2dONytCBSK1XIXpSClPJ", original_name="CAGECFI_SIG_PERFECT-V-min.pdf", slug="CAGECFI_SIG_PERFECT-V-min.pdf"),
    DriveFile(drive_id="1q8ei_Wl8217gT-xckLIc77nnD5Vvp4G9", original_name="CLOUD_Administrations.pdf", slug="CLOUD_Administrations.pdf"),
    DriveFile(drive_id="16jw8Qzs-UTtLddNsfApJlZUuK8Jc9aL2", original_name="CLOUD_SFD_IMF.pdf", slug="CLOUD_SFD_IMF.pdf"),
    DriveFile(drive_id="13_8U1biOXsZ9r23Cq25bEUqxyOQ2JxAV", original_name="CORE BANKING_PERFECT_ENG.pdf", slug="CORE_BANKING_PERFECT_ENG.pdf"),
    DriveFile(drive_id="17UP790DCvnJ0bTZxBy0mpiU3B5iD_nEz", original_name="DIGITAL FINANCE SOLUTIONS_ENG.pdf", slug="DIGITAL_FINANCE_SOLUTIONS_ENG.pdf"),
    DriveFile(drive_id="10Qp4F4eqz5Y7nb85HACAQ6THi8fo0mvo", original_name="ERP COMPTA.pdf", slug="ERP_COMPTA.pdf"),
    DriveFile(drive_id="1mJTYRzk_tm1Vt7VC-HYjC2GVEBQhiRC7", original_name="GOMISE.pdf", slug="GOMISE.pdf"),
    DriveFile(drive_id="1RNxJuzKkvOKr5eHXgEBBkj76MeFjhcW8", original_name="GOV MONITOR_Suivi Evaluations Projets_Programmes.pdf", slug="GOV_MONITOR.pdf"),
    DriveFile(drive_id="1mrQGm8bSymspCTuBrESWC0Tu4dmID8lx", original_name="GOV SOLUTIONS_ENG.pdf", slug="GOV_SOLUTIONS_ENG.pdf"),
    DriveFile(drive_id="1CLY6AokhmKa9huPjkGckLXEdfClfVuy6", original_name="IMMOS.pdf", slug="IMMOS.pdf"),
    DriveFile(drive_id="1uyer6j3lmTMKDMLJFH798gij8J5VDujT", original_name="Insertion 21,5 x 27,5_page-0001.jpg", slug="Insertion_page-0001.jpg"),
    DriveFile(drive_id="1Z4TsbwqO3nG5uybklV01Fc3YFCpXPsJH", original_name="INTEROPERABILITE des systemes financiers.pdf", slug="INTEROPERABILITE.pdf"),
    DriveFile(drive_id="1Djq9F75swUuyxUuzF8wUnspzhHkPISRc", original_name="IT BASED SOLUTIONS GOV_ENG.pdf", slug="IT_BASED_SOLUTIONS_GOV_ENG.pdf"),
    DriveFile(drive_id="1lGtUo6EuupNC5R2QL76pLk_t9mpmo7i-", original_name="Livret Solutions étatiques-min (2).pdf", slug="Livret_Solutions_etatiques-min.pdf"),
    DriveFile(drive_id="1Bj8zH0XgPfu7FRCC9415VUz33zCv-u-7", original_name="Livret Solutions étatiques.pdf", slug="Livret_Solutions_etatiques.pdf"),
    DriveFile(drive_id="1g2BTp_FkptyiGUt5c6NpZ4ah4EwWbc_R", original_name="MODULES REGLEMENTATAIRES_BIC_LBCFT.pdf", slug="MODULES_REGLEMENTAIRES_BIC_LBCFT.pdf"),
    DriveFile(drive_id="1nklYPMtlfD56yae94fVw_U7Wb4Dz-zSQ", original_name="PAY TAX.pdf", slug="PAY_TAX.pdf"),
    DriveFile(drive_id="1-UKBF2nPRN0b5SkaCoFwHmn-Nvc9510_", original_name="PERFECT-VISION-SIG.pdf", slug="PERFECT-VISION-SIG.pdf"),
    DriveFile(drive_id="1RELmduwYK5SPc9p1FQkNtE4cd8nI5WKg", original_name="PERFECT.pdf", slug="PERFECT.pdf"),
    DriveFile(drive_id="1h0cvJd-r_ayEqkTbdDYd1m4Yfe88vhn9", original_name="Plaquette Fiscalisation.pdf", slug="Plaquette_Fiscalisation.pdf"),
    DriveFile(drive_id="1QtGaMei9Xvpo5zjGu6YURmYIS0oH8zqf", original_name="Plaquette_PAY TAX.pdf", slug="Plaquette_PAY_TAX.pdf"),
    DriveFile(drive_id="18g3YoIHyScK9-BmEwU8wcLp5htyckGBE", original_name="PROCESSUS CREDIT_CAGECFI_JIWAY.pdf", slug="PROCESSUS_CREDIT_JIWAY.pdf"),
    DriveFile(drive_id="1whKQ1_-hLX_C2SQyXb7OXSVThv-sNSav", original_name="SICOM.pdf", slug="SICOM.pdf"),
    DriveFile(drive_id="1b6Ex6fWk0_584H2rnlxWJ08gAC4ciqKf", original_name="Solutions de finance digitale-min.pdf", slug="Solutions_finance_digitale-min.pdf"),
    DriveFile(drive_id="1ABz_7eR_kePhSurJF2yig2G2x9M33QVp", original_name="Solutions de finance digitale.pdf", slug="Solutions_finance_digitale.pdf"),
    DriveFile(drive_id="11zi3QKvJCUzAgIBaMPg32xPQe7NXcun_", original_name="SYCEBNL_CAGECFI.pdf", slug="SYCEBNL_CAGECFI.pdf"),
    DriveFile(drive_id="1kmGWI1A9c1o4w6qN9p7QWcyFHbi2sJaC", original_name="SYCEBNL.pdf", slug="SYCEBNL.pdf"),
    DriveFile(drive_id="1YCRb_k2Iz1A2wh8Yc3SdG4XFjB2KL_hw", original_name="TRADER.pdf", slug="TRADER.pdf"),
    DriveFile(drive_id="1ruFLqu59oJyhf81WMEYsN7Sjt0ZtYkFl", original_name="VISUEL CAGECFI.pdf", slug="VISUEL_CAGECFI.pdf"),
]


def is_complete_pdf(path: Path) -> bool:
    """Verifie qu'un PDF est complet via son marqueur de fin.

    Args:
        path: Chemin du fichier a verifier.

    Returns:
        True si le fichier existe et se termine par %%EOF, False sinon.
        Les fichiers non-PDF (.jpg) sont acceptes s'ils sont non vides.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    if path.suffix.lower() != ".pdf":
        return True
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 1024))
        return b"%%EOF" in handle.read()


async def download_file(
    client: httpx.AsyncClient, item: DriveFile, dest_dir: Path
) -> Path:
    """Telecharge un fichier du Drive, en sautant les fichiers deja complets.

    Args:
        client: Client HTTP asynchrone.
        item: Entree d'inventaire a telecharger.
        dest_dir: Repertoire de destination.

    Returns:
        Chemin du fichier telecharge.

    Raises:
        httpx.HTTPError: Si le telechargement echoue.
        ValueError: Si le fichier telecharge est incomplet.
    """
    dest = dest_dir / item.slug
    if is_complete_pdf(dest):
        logger.info("deja_present slug=%s", item.slug)
        return dest

    url = DOWNLOAD_URL.format(drive_id=item.drive_id)
    response = await client.get(url, follow_redirects=True, timeout=600.0)
    response.raise_for_status()
    dest.write_bytes(response.content)

    if not is_complete_pdf(dest):
        raise ValueError(f"Telechargement incomplet pour {item.slug}")

    logger.info("telecharge slug=%s octets=%d", item.slug, dest.stat().st_size)
    return dest


async def download_all(dest_dir: Path) -> list[Path]:
    """Telecharge tout l'inventaire, sequentiellement.

    Un echec sur un fichier est journalise et n'interrompt pas les suivants.

    Args:
        dest_dir: Repertoire de destination, cree si absent.

    Returns:
        Liste des chemins telecharges avec succes.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    ok: list[Path] = []
    echecs: list[str] = []

    async with httpx.AsyncClient() as client:
        for item in DRIVE_FILES:
            try:
                ok.append(await download_file(client, item, dest_dir))
            except (httpx.HTTPError, ValueError) as exc:
                logger.exception("telechargement_echoue slug=%s", item.slug)
                echecs.append(f"{item.slug}: {exc}")

    if echecs:
        logger.error("telechargements_en_echec n=%d: %s", len(echecs), echecs)
    logger.info("telechargement_termine ok=%d echecs=%d", len(ok), len(echecs))
    return ok


def main() -> None:
    """Point d'entree CLI : telecharge les plaquettes dans documents/plaquettes/."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    asyncio.run(download_all(Path("documents/plaquettes")))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_drive_source.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Télécharger réellement le corpus**

Run: `uv run python -m src.ingestion.drive_source`
Expected: `telechargement_termine ok=32 echecs=0`

Si `INTEROPERABILITE.pdf` (89 Mo) échoue par dépassement de délai, relancer la commande : les fichiers déjà complets sont sautés.

- [ ] **Step 6: Vérifier le résultat**

Run: `uv run python -c "from pathlib import Path; from src.ingestion.drive_source import DRIVE_FILES, is_complete_pdf; d=Path('documents/plaquettes'); print(sum(is_complete_pdf(d/f.slug) for f in DRIVE_FILES), '/32 complets')"`
Expected: `32 /32 complets`

- [ ] **Step 7: Commit**

```bash
git add src/ingestion/drive_source.py tests/ingestion/test_drive_source.py
git commit -m "feat: inventaire et telechargement verifie des plaquettes Drive"
```

Ne pas committer les PDF eux-mêmes : ajouter `documents/plaquettes/` à `.gitignore` s'il n'y figure pas.

---

### Task 3: Audit d'extractibilité et dédoublonnage

**Files:**
- Create: `src/ingestion/pdf_audit.py`
- Test: `tests/ingestion/test_pdf_audit.py`

**Interfaces:**
- Consumes: `documents/plaquettes/*.pdf` produits par la Task 2
- Produces:
  - `DocumentKind = Literal["TEXTE", "MIXTE", "IMAGE"]`
  - `DocumentAudit` (Pydantic : `filename`, `md5`, `pages`, `chars_per_page`, `kind`, `is_duplicate_of: str | None`, `language: Literal["fr","en"]`, `excluded_reason: str | None`)
  - `classify(chars_per_page: int) -> DocumentKind`
  - `audit_directory(pdf_dir: Path) -> list[DocumentAudit]`
  - `write_audit(audits: list[DocumentAudit], dest: Path) -> None`
  - `ENGLISH_SLUGS: set[str]`

**Seuils mesurés :** `TEXTE` ≥ 400 caractères/page, `MIXTE` ≥ 50, sinon `IMAGE`. Ces valeurs séparent nettement le corpus observé (documents texte à 942–2579 c/p, documents image à 0 c/p).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_pdf_audit.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_pdf_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.pdf_audit'`

- [ ] **Step 3: Implémenter `src/ingestion/pdf_audit.py`**

```python
"""Audit d'extractibilite du corpus de plaquettes.

Determine, pour chaque PDF, s'il possede une couche texte exploitable. Ce
routage n'est pas une optimisation : 94% des pages du corpus sont des visuels
sans aucun caractere extractible, et une ingestion naive les indexerait vides
sans lever d'erreur.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pypdf import PdfReader

logger = logging.getLogger(__name__)

DocumentKind = Literal["TEXTE", "MIXTE", "IMAGE"]

SEUIL_TEXTE = 400
SEUIL_MIXTE = 50

ENGLISH_SLUGS: set[str] = {
    "CORE_BANKING_PERFECT_ENG.pdf",
    "DIGITAL_FINANCE_SOLUTIONS_ENG.pdf",
    "GOV_SOLUTIONS_ENG.pdf",
    "IT_BASED_SOLUTIONS_GOV_ENG.pdf",
}


class DocumentAudit(BaseModel):
    """Resultat de l'audit d'extractibilite d'un PDF."""

    filename: str = Field(..., description="Nom du fichier local")
    md5: str = Field(..., description="Empreinte du contenu")
    pages: int = Field(..., description="Nombre de pages, -1 si illisible")
    chars_per_page: int = Field(..., description="Caracteres alphabetiques par page")
    kind: DocumentKind = Field(..., description="Voie d'extraction a emprunter")
    is_duplicate_of: Optional[str] = Field(default=None, description="Fichier original si doublon")
    language: Literal["fr", "en"] = Field(default="fr", description="Langue du document")
    excluded_reason: Optional[str] = Field(default=None, description="Motif d'exclusion, None si retenu")

    @property
    def is_retained(self) -> bool:
        """Indique si le document doit etre extrait puis ingere."""
        return self.excluded_reason is None


def classify(chars_per_page: int) -> DocumentKind:
    """Classe un document selon sa densite de texte extractible.

    Args:
        chars_per_page: Nombre de caracteres alphabetiques par page.

    Returns:
        TEXTE, MIXTE ou IMAGE.
    """
    if chars_per_page >= SEUIL_TEXTE:
        return "TEXTE"
    if chars_per_page >= SEUIL_MIXTE:
        return "MIXTE"
    return "IMAGE"


def audit_pdf(path: Path) -> DocumentAudit:
    """Audite un PDF unique.

    Args:
        path: Chemin du PDF.

    Returns:
        Resultat d'audit. Un fichier illisible recoit pages=-1 et kind=IMAGE,
        de sorte qu'il parte a l'OCR plutot que d'etre ignore silencieusement.
    """
    md5 = hashlib.md5(path.read_bytes()).hexdigest()
    try:
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        alpha = 0
        for page in reader.pages:
            try:
                alpha += sum(c.isalpha() for c in (page.extract_text() or ""))
            except Exception:  # noqa: BLE001 - page corrompue isolee
                logger.warning("page_illisible fichier=%s", path.name)
        per_page = alpha // max(pages, 1)
        return DocumentAudit(
            filename=path.name, md5=md5, pages=pages,
            chars_per_page=per_page, kind=classify(per_page),
        )
    except Exception:  # noqa: BLE001 - PDF corrompu, on route vers l'OCR
        logger.exception("pdf_illisible fichier=%s", path.name)
        return DocumentAudit(
            filename=path.name, md5=md5, pages=-1, chars_per_page=0, kind="IMAGE",
        )


def apply_exclusions(audits: list[DocumentAudit]) -> list[DocumentAudit]:
    """Marque les doublons et les documents anglais.

    L'exclusion est toujours tracee par un motif : aucun document ne disparait
    silencieusement du pipeline.

    Args:
        audits: Audits bruts.

    Returns:
        Audits enrichis de is_duplicate_of, language et excluded_reason.
    """
    premier_par_hash: dict[str, str] = {}
    resultat: list[DocumentAudit] = []

    for audit in sorted(audits, key=lambda a: a.filename):
        copie = audit.model_copy()

        if copie.filename in ENGLISH_SLUGS:
            copie.language = "en"
            copie.excluded_reason = "document en anglais"
        elif copie.md5 in premier_par_hash:
            original = premier_par_hash[copie.md5]
            copie.is_duplicate_of = original
            copie.excluded_reason = f"doublon exact de {original}"
        else:
            premier_par_hash[copie.md5] = copie.filename

        resultat.append(copie)

    return resultat


def audit_directory(pdf_dir: Path) -> list[DocumentAudit]:
    """Audite tous les PDF d'un repertoire et applique les exclusions.

    Args:
        pdf_dir: Repertoire contenant les plaquettes.

    Returns:
        Liste d'audits, triee par nom de fichier.
    """
    audits = [audit_pdf(p) for p in sorted(pdf_dir.glob("*.pdf"))]
    return apply_exclusions(audits)


def write_audit(audits: list[DocumentAudit], dest: Path) -> None:
    """Ecrit le rapport d'audit en JSON.

    Args:
        audits: Audits a serialiser.
        dest: Fichier de destination.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = [a.model_dump() for a in audits]
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("audit_ecrit fichier=%s n=%d", dest, len(audits))


def main() -> None:
    """Point d'entree CLI : audite documents/plaquettes/."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    audits = audit_directory(Path("documents/plaquettes"))
    write_audit(audits, Path("documents/plaquettes_audit.json"))

    retenus = [a for a in audits if a.is_retained]
    par_type: dict[str, int] = {}
    for audit in retenus:
        par_type[audit.kind] = par_type.get(audit.kind, 0) + 1

    print(f"Documents audites : {len(audits)}")
    print(f"Documents retenus : {len(retenus)}")
    for kind, n in sorted(par_type.items()):
        print(f"  {kind:<6}: {n}")
    print(f"Exclus            : {len(audits) - len(retenus)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_pdf_audit.py -v`
Expected: PASS (9 tests, dont 6 paramétrés)

- [ ] **Step 5: Auditer le corpus réel**

Run: `uv run python -m src.ingestion.pdf_audit`
Expected: `Documents retenus : 22` et `Exclus : 9` (6 doublons + 3 anglais ; `IT_BASED_SOLUTIONS_GOV_ENG.pdf` est à la fois doublon et anglais, il n'est compté qu'une fois).

Vérifier que la répartition des retenus est cohérente avec la spec : environ 14 `IMAGE` et 6 `TEXTE`/`MIXTE`, plus les 2 fichiers auparavant tronqués désormais classés.

- [ ] **Step 6: Commit**

```bash
git add src/ingestion/pdf_audit.py tests/ingestion/test_pdf_audit.py
git commit -m "feat: audit d'extractibilite et dedoublonnage du corpus"
```

---

### Task 4: Client Mistral OCR et nettoyage des artefacts

**Files:**
- Create: `src/ingestion/mistral_ocr.py`
- Test: `tests/ingestion/test_mistral_ocr.py`

**Interfaces:**
- Consumes: `SupabaseSettings.mistral_api_key`, `SupabaseSettings.mistral_ocr_model` (Task 1)
- Produces:
  - `OcrPage` (Pydantic : `index: int`, `markdown: str`, `image_refs: int`)
  - `OcrResult` (Pydantic : `pages: list[OcrPage]`, `markdown: str`, `image_ratio: float`)
  - `clean_artifacts(markdown: str) -> str`
  - `ocr_pdf(path: Path, settings: SupabaseSettings) -> OcrResult` (async)

**Défauts mesurés à corriger :** l'API renvoie `\(\odot\)` et `\(\mathbb{O}\)` à la place des puces graphiques. Les références `![img-N.jpeg]` signalent des infographies non transcrites — leur proportion pilote la priorité de relecture humaine.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_mistral_ocr.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_mistral_ocr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.mistral_ocr'`

- [ ] **Step 3: Implémenter `src/ingestion/mistral_ocr.py`**

```python
"""Client Mistral OCR pour les plaquettes sans couche texte.

Mesures relevees le 2026-07-31 sur le corpus reel : 1 a 5 secondes par page,
un envoi de 11,1 Mo accepte, et une qualite francaise nettement superieure a
l'OCR local (73 accents corrects contre 54 sur PERFECT.pdf).
"""

import base64
import logging
import re
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from src.settings_supabase import SupabaseSettings

logger = logging.getLogger(__name__)

OCR_ENDPOINT = "https://api.mistral.ai/v1/ocr"

# Puces graphiques rendues en LaTeX par l'OCR : \(\odot\), \(\mathbb{O}\), etc.
_ARTEFACTS_LATEX = re.compile(r"\\\(\s*\\[A-Za-z]+(?:\{[^}]*\})?\s*\\\)\s*")
_LIGNES_VIDES = re.compile(r"\n{3,}")
_REF_IMAGE = re.compile(r"!\[img-\d+\.\w+\]")


class OcrPage(BaseModel):
    """Une page transcrite."""

    index: int = Field(..., description="Numero de page, base 0")
    markdown: str = Field(..., description="Contenu markdown de la page")
    image_refs: int = Field(default=0, description="References d'images non transcrites")


class OcrResult(BaseModel):
    """Resultat complet d'une transcription."""

    pages: list[OcrPage] = Field(default_factory=list)
    markdown: str = Field(default="", description="Markdown concatene et nettoye")

    @property
    def image_ratio(self) -> float:
        """Nombre moyen de references d'images par page.

        Un ratio eleve signale une plaquette dont l'information est portee par
        des infographies non transcrites : elle doit etre relue en priorite.
        """
        if not self.pages:
            return 0.0
        return sum(p.image_refs for p in self.pages) / len(self.pages)


def clean_artifacts(markdown: str) -> str:
    """Supprime les artefacts LaTeX laisses par l'OCR sur les puces graphiques.

    Args:
        markdown: Markdown brut renvoye par l'API.

    Returns:
        Markdown nettoye, sans lignes vides superflues.
    """
    sans_latex = _ARTEFACTS_LATEX.sub("", markdown)
    return _LIGNES_VIDES.sub("\n\n", sans_latex)


async def ocr_pdf(path: Path, settings: SupabaseSettings) -> OcrResult:
    """Transcrit un PDF via l'API Mistral OCR.

    Args:
        path: Chemin du PDF a transcrire.
        settings: Configuration portant la cle et le modele.

    Returns:
        Resultat de transcription, markdown nettoye.

    Raises:
        ValueError: Si la cle API est absente.
        httpx.HTTPStatusError: Si l'API repond une erreur.
    """
    if not settings.mistral_api_key:
        raise ValueError("MISTRAL_API_KEY absente : impossible d'appeler l'OCR")

    encoded = base64.b64encode(path.read_bytes()).decode()
    payload = {
        "model": settings.mistral_ocr_model,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{encoded}",
        },
        "include_image_base64": False,
    }

    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            OCR_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    pages: list[OcrPage] = []
    for index, page in enumerate(data.get("pages", [])):
        brut = page.get("markdown", "")
        pages.append(
            OcrPage(
                index=index,
                markdown=clean_artifacts(brut),
                image_refs=len(_REF_IMAGE.findall(brut)),
            )
        )

    result = OcrResult(
        pages=pages,
        markdown="\n\n".join(p.markdown for p in pages).strip(),
    )
    logger.info(
        "ocr_termine fichier=%s pages=%d ratio_images=%.2f",
        path.name, len(pages), result.image_ratio,
    )
    return result
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_mistral_ocr.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Écrire le test d'intégration**

Ajouter à la fin de `tests/ingestion/test_mistral_ocr.py` :

```python
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
```

- [ ] **Step 6: Lancer le test d'intégration**

Run: `uv run pytest tests/ingestion/test_mistral_ocr.py -m integration -v`
Expected: PASS — durée d'environ 15 s

- [ ] **Step 7: Commit**

```bash
git add src/ingestion/mistral_ocr.py tests/ingestion/test_mistral_ocr.py
git commit -m "feat: client Mistral OCR avec nettoyage des artefacts LaTeX"
```

---

### Task 5: Extraction routée vers markdown

**Files:**
- Create: `src/ingestion/extract_plaquettes.py`
- Test: `tests/ingestion/test_extract_plaquettes.py`

**Interfaces:**
- Consumes: `DocumentAudit`, `audit_directory` (Task 3) ; `ocr_pdf`, `OcrResult` (Task 4)
- Produces:
  - `ExtractionResult` (Pydantic : `filename`, `slug`, `method: Literal["docling","mistral_ocr"]`, `markdown`, `image_ratio`, `error: str | None`)
  - `extract_with_docling(path: Path) -> str`
  - `extract_document(audit: DocumentAudit, pdf_dir: Path, settings: SupabaseSettings) -> ExtractionResult` (async)
  - `write_markdown(result: ExtractionResult, dest_dir: Path) -> Path`
  - `extract_all(pdf_dir: Path, audit_path: Path, dest_dir: Path) -> list[ExtractionResult]` (async)

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_extract_plaquettes.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_extract_plaquettes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.extract_plaquettes'`

- [ ] **Step 3: Implémenter `src/ingestion/extract_plaquettes.py`**

```python
"""Extraction routee des plaquettes vers du markdown relisible.

Le routage est dicte par l'audit : Docling sans OCR pour les documents ayant
une couche texte (l'OCR y degrade la qualite, mesure a l'appui), Mistral OCR
pour les visuels. Le markdown produit est un artefact versionnable, destine a
etre relu avant vectorisation.
"""

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import frontmatter
from pydantic import BaseModel, Field

from src.ingestion.mistral_ocr import ocr_pdf
from src.ingestion.pdf_audit import DocumentAudit
from src.settings_supabase import SupabaseSettings, load_settings

logger = logging.getLogger(__name__)

ExtractionMethod = Literal["docling", "mistral_ocr"]


class ExtractionResult(BaseModel):
    """Resultat de l'extraction d'un document."""

    filename: str = Field(..., description="Nom du PDF source")
    slug: str = Field(..., description="Nom de base sans extension")
    method: ExtractionMethod = Field(..., description="Voie d'extraction empruntee")
    markdown: str = Field(default="", description="Contenu extrait")
    image_ratio: float = Field(default=0.0, description="References d'images par page")
    error: Optional[str] = Field(default=None, description="Message d'erreur si echec")

    @property
    def succeeded(self) -> bool:
        """Indique si l'extraction a produit du contenu exploitable."""
        return self.error is None and bool(self.markdown.strip())


def extract_with_docling(path: Path) -> str:
    """Extrait le markdown d'un PDF possedant une couche texte.

    L'OCR est explicitement desactive : sur ces documents il fusionne les
    espaces et degrade les accents.

    Args:
        path: Chemin du PDF.

    Returns:
        Markdown exporte par Docling.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    return converter.convert(str(path)).document.export_to_markdown()


async def extract_document(
    audit: DocumentAudit, pdf_dir: Path, settings: SupabaseSettings
) -> ExtractionResult:
    """Extrait un document selon la voie determinee par son audit.

    Args:
        audit: Resultat d'audit du document.
        pdf_dir: Repertoire des PDF sources.
        settings: Configuration applicative.

    Returns:
        Resultat d'extraction. Une erreur est portee dans le champ `error`
        plutot que levee, afin de ne pas interrompre le lot.
    """
    path = pdf_dir / audit.filename
    slug = path.stem
    method: ExtractionMethod = "docling" if audit.kind in ("TEXTE", "MIXTE") else "mistral_ocr"

    try:
        if method == "docling":
            markdown = await asyncio.to_thread(extract_with_docling, path)
            ratio = 0.0
        else:
            result = await ocr_pdf(path, settings)
            markdown, ratio = result.markdown, result.image_ratio

        return ExtractionResult(
            filename=audit.filename, slug=slug, method=method,
            markdown=markdown, image_ratio=ratio,
        )
    except Exception as exc:  # noqa: BLE001 - un echec isole ne stoppe pas le lot
        logger.exception("extraction_echouee fichier=%s", audit.filename)
        return ExtractionResult(
            filename=audit.filename, slug=slug, method=method, error=str(exc),
        )


def write_markdown(result: ExtractionResult, dest_dir: Path) -> Path:
    """Ecrit le markdown avec son front-matter de provenance.

    Args:
        result: Resultat d'extraction reussi.
        dest_dir: Repertoire de destination.

    Returns:
        Chemin du fichier ecrit.

    Raises:
        ValueError: Si l'extraction est en echec ou sans contenu.
    """
    if not result.succeeded:
        raise ValueError(f"extraction en echec pour {result.filename}: {result.error}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        result.markdown,
        source_file=result.filename,
        extraction=result.method,
        image_ratio=round(result.image_ratio, 2),
        extracted_at=date.today().isoformat(),
    )
    dest = dest_dir / f"{result.slug}.md"
    dest.write_text(frontmatter.dumps(post), encoding="utf-8")
    return dest


async def extract_all(
    pdf_dir: Path, audit_path: Path, dest_dir: Path
) -> list[ExtractionResult]:
    """Extrait tous les documents retenus par l'audit.

    Args:
        pdf_dir: Repertoire des PDF sources.
        audit_path: Rapport d'audit JSON produit par pdf_audit.
        dest_dir: Repertoire de sortie des markdown.

    Returns:
        Liste des resultats, succes comme echecs.
    """
    audits = [DocumentAudit(**row) for row in json.loads(audit_path.read_text(encoding="utf-8"))]
    retenus = [a for a in audits if a.is_retained]
    settings = load_settings()

    resultats: list[ExtractionResult] = []
    for audit in retenus:
        result = await extract_document(audit, pdf_dir, settings)
        if result.succeeded:
            write_markdown(result, dest_dir)
        resultats.append(result)

    echecs = [r for r in resultats if not r.succeeded]
    logger.info(
        "extraction_terminee ok=%d echecs=%d",
        len(resultats) - len(echecs), len(echecs),
    )
    return resultats


def main() -> None:
    """Point d'entree CLI : extrait les plaquettes retenues vers markdown."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    resultats = asyncio.run(
        extract_all(
            Path("documents/plaquettes"),
            Path("documents/plaquettes_audit.json"),
            Path("documents/plaquettes_md"),
        )
    )

    print("\nEXTRACTION")
    for r in sorted(resultats, key=lambda x: x.filename):
        etat = "OK  " if r.succeeded else "ECHEC"
        alerte = "  <-- a relire en priorite" if r.image_ratio >= 2.0 else ""
        print(f"  {etat} {r.filename:<45} {r.method:<12} images/page={r.image_ratio:.1f}{alerte}")

    echecs = [r for r in resultats if not r.succeeded]
    print(f"\nTotal : {len(resultats) - len(echecs)} reussites, {len(echecs)} echecs")
    for r in echecs:
        print(f"  ECHEC {r.filename}: {r.error}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_extract_plaquettes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Extraire le corpus réel**

Run: `uv run python -m src.ingestion.extract_plaquettes`
Expected: 22 lignes `OK`, 0 échec. Durée de quelques minutes.

Si `INTEROPERABILITE.pdf` échoue sur une limite de taille de l'API, c'est le seul cas prévu : le découper par pages et relancer. Tous les autres fichiers sont sous 12 Mo, taille validée par appel réel.

- [ ] **Step 6: Point de contrôle humain**

Ouvrir `documents/plaquettes_md/` et relire, en priorisant les fichiers dont la sortie affiche `<-- a relire en priorite` (ratio d'images ≥ 2).

Vérifier sur au moins `PERFECT.md`, `CAGECFI_QUI_SOMMES_NOUS.md` et `GOMISE.md` :
- les noms de produits sont corrects ;
- les listes de fonctionnalités sont complètes et ordonnées ;
- les coordonnées et chiffres sont exacts ;
- aucune section ne se réduit à des références `![img-N.jpeg]` — si c'est le cas, l'information de cette page est perdue et devra être saisie à la main.

Corriger directement les fichiers markdown si nécessaire : ce sont eux qui alimentent la base.

- [ ] **Step 7: Commit**

```bash
git add src/ingestion/extract_plaquettes.py tests/ingestion/test_extract_plaquettes.py documents/plaquettes_md/
git commit -m "feat: extraction routee des plaquettes vers markdown relu"
```

Les markdown sont versionnés volontairement : ils constituent la source de vérité relue de la base de connaissance.

---

### Task 6: Fiches produit structurées

**Files:**
- Create: `src/ingestion/product_sheet.py`
- Test: `tests/ingestion/test_product_sheet.py`

**Interfaces:**
- Consumes: markdown de `documents/plaquettes_md/` (Task 5)
- Produces:
  - `ProductCategory = Literal["core_banking","finance_digitale","cloud","fiscalite","secteur_public","gestion_metier","corporate"]`
  - `ProductSheet` (Pydantic : `product`, `category`, `target_audience: list[str]`, `features: list[str]`, `benefits: list[str]`, `summary`)
  - `SHEET_PROMPT: str`
  - `build_sheet(markdown: str, slug: str, settings: SupabaseSettings) -> ProductSheet | None` (async)
  - `sheet_to_markdown(sheet: ProductSheet) -> str`

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_product_sheet.py` :

```python
"""Tests des fiches produit structurees."""

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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_product_sheet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.product_sheet'`

- [ ] **Step 3: Implémenter `src/ingestion/product_sheet.py`**

```python
"""Generation des fiches produit structurees a partir des plaquettes.

A la question « que fait Perfect-Vision ? », une fiche de synthese repond mieux
qu'un fragment de plaquette isole. Les fiches sont indexees en plus des chunks
bruts, qui restent necessaires aux questions de detail.
"""

import json
import logging
from typing import Literal, Optional

import openai
from pydantic import BaseModel, Field, ValidationError

from src.settings_supabase import SupabaseSettings

logger = logging.getLogger(__name__)

ProductCategory = Literal[
    "core_banking", "finance_digitale", "cloud", "fiscalite",
    "secteur_public", "gestion_metier", "corporate",
]


class ProductSheet(BaseModel):
    """Fiche de synthese d'un produit ou d'une offre CAGECFI."""

    product: str = Field(..., description="Nom du produit ou de l'offre")
    category: ProductCategory = Field(..., description="Categorie de la taxonomie")
    target_audience: list[str] = Field(default_factory=list, description="Cibles visees")
    features: list[str] = Field(default_factory=list, description="Fonctionnalites")
    benefits: list[str] = Field(default_factory=list, description="Benefices annonces")
    summary: str = Field(..., description="Resume en deux ou trois phrases")


SHEET_PROMPT = """Tu analyses une plaquette commerciale de CAGECFI, societe togolaise
d'ingenierie informatique (logiciels pour la microfinance, la finance digitale et
les administrations).

A partir du contenu fourni, produis un objet JSON avec exactement ces cles :
- "product" : le nom du produit ou de l'offre
- "category" : une valeur parmi core_banking, finance_digitale, cloud, fiscalite,
  secteur_public, gestion_metier, corporate
- "target_audience" : liste des cibles explicitement mentionnees
- "features" : liste des fonctionnalites, reprises fidelement
- "benefits" : liste des benefices annonces
- "summary" : resume de deux a trois phrases

Regles imperatives :
- N'invente rien. Si une information est absente, laisse la liste vide.
- Reprends la terminologie exacte de la plaquette.
- Reponds uniquement par le JSON, sans texte autour.

CONTENU :
"""


async def build_sheet(
    markdown: str, slug: str, settings: SupabaseSettings
) -> Optional[ProductSheet]:
    """Construit une fiche produit a partir du markdown d'une plaquette.

    Args:
        markdown: Contenu de la plaquette.
        slug: Identifiant du document, utilise pour la journalisation.
        settings: Configuration portant le LLM.

    Returns:
        La fiche produit, ou None si le modele n'a pas produit un objet valide.
        Un echec ne doit pas interrompre le lot : les chunks bruts restent
        ingeres meme sans fiche.
    """
    client = openai.AsyncOpenAI(
        api_key=settings.llm_api_key, base_url=settings.llm_base_url
    )

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": SHEET_PROMPT + markdown[:12000]}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return ProductSheet(**payload)
    except (json.JSONDecodeError, ValidationError, openai.APIError):
        logger.exception("fiche_produit_echouee slug=%s", slug)
        return None


def sheet_to_markdown(sheet: ProductSheet) -> str:
    """Rend une fiche produit en markdown indexable.

    Args:
        sheet: Fiche a rendre.

    Returns:
        Markdown structure, pret a etre chunke et vectorise.
    """
    lignes = [f"# {sheet.product}", "", f"Categorie : {sheet.category}", "", sheet.summary, ""]

    if sheet.target_audience:
        lignes += ["## Pour qui", ""] + [f"- {c}" for c in sheet.target_audience] + [""]
    if sheet.features:
        lignes += ["## Fonctionnalites", ""] + [f"- {f}" for f in sheet.features] + [""]
    if sheet.benefits:
        lignes += ["## Benefices", ""] + [f"- {b}" for b in sheet.benefits] + [""]

    return "\n".join(lignes).strip() + "\n"
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_product_sheet.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Écrire le test de génération des fiches**

Ajouter à `tests/ingestion/test_product_sheet.py` :

```python
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
```

Ajouter `from pathlib import Path` en tête du fichier de test.

- [ ] **Step 6: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_product_sheet.py::test_write_sheet_marks_doc_type_product_sheet -v`
Expected: FAIL — `ImportError: cannot import name 'write_sheet'`

- [ ] **Step 7: Implémenter l'écriture et le CLI**

Ajouter à la fin de `src/ingestion/product_sheet.py` :

```python
def write_sheet(sheet: ProductSheet, slug: str, dest_dir: Path) -> Path:
    """Ecrit une fiche produit en markdown avec son front-matter.

    Le front-matter porte doc_type=product_sheet : l'ingestion le recopie tel
    quel, ce qui rend la metadonnee discriminante cote recherche.

    Args:
        sheet: Fiche a ecrire.
        slug: Identifiant du document source.
        dest_dir: Repertoire de destination.

    Returns:
        Chemin du fichier ecrit.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        sheet_to_markdown(sheet),
        doc_type="product_sheet",
        product=sheet.product,
        category=sheet.category,
        source_file=f"{slug}.pdf",
        extraction="product_sheet",
    )
    dest = dest_dir / f"{slug}_fiche.md"
    dest.write_text(frontmatter.dumps(post), encoding="utf-8")
    return dest


async def build_all_sheets(md_dir: Path) -> list[Path]:
    """Genere une fiche produit pour chaque plaquette extraite.

    Les fiches deja generees et les fiches elles-memes sont ignorees, afin que
    la commande soit rejouable sans se cannibaliser.

    Args:
        md_dir: Repertoire des markdown de plaquettes.

    Returns:
        Chemins des fiches ecrites.
    """
    settings = load_settings()
    ecrites: list[Path] = []

    for source in sorted(md_dir.glob("*.md")):
        if source.stem.endswith("_fiche"):
            continue
        post = frontmatter.loads(source.read_text(encoding="utf-8"))
        sheet = await build_sheet(post.content, source.stem, settings)
        if sheet is None:
            logger.warning("fiche_ignoree slug=%s", source.stem)
            continue
        ecrites.append(write_sheet(sheet, source.stem, md_dir))

    logger.info("fiches_generees n=%d", len(ecrites))
    return ecrites


def main() -> None:
    """Point d'entree CLI : genere les fiches produit des plaquettes extraites."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    fiches = asyncio.run(build_all_sheets(Path("documents/plaquettes_md")))
    print(f"\n{len(fiches)} fiches produit generees :")
    for chemin in fiches:
        print(f"  {chemin.name}")


if __name__ == "__main__":
    main()
```

Compléter les imports en tête du module :

```python
import asyncio
from pathlib import Path

import frontmatter

from src.settings_supabase import SupabaseSettings, load_settings
```

- [ ] **Step 8: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_product_sheet.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Générer les fiches du corpus réel**

Run: `uv run python -m src.ingestion.product_sheet`
Expected: environ 22 fiches, une par plaquette extraite

Relire deux ou trois fiches (`PERFECT_fiche.md`, `GOMISE_fiche.md`) et vérifier qu'aucune fonctionnalité n'a été inventée : le prompt l'interdit, mais la vérification vaut mieux que la confiance.

- [ ] **Step 10: Commit**

```bash
git add src/ingestion/product_sheet.py tests/ingestion/test_product_sheet.py documents/plaquettes_md/
git commit -m "feat: fiches produit structurees a partir des plaquettes"
```

---

### Task 7: Ingestion enrichie vers Supabase

**Files:**
- Modify: `src/ingestion/ingest_supabase.py:210-278` (`_read_document`), `:362-382` (`_extract_document_metadata`)
- Test: `tests/ingestion/test_ingest_metadata.py`

**Interfaces:**
- Consumes: `documents/plaquettes_md/*.md` avec front-matter (Task 5) ; `ProductSheet`, `sheet_to_markdown` (Task 6)
- Produces: métadonnées enrichies dans `cagecfi_chunks.metadata`

**Contexte :** `_read_document` traite déjà les `.md` via Docling. Il faut intercepter le front-matter avant, sans quoi les clés YAML se retrouveraient dans le texte indexé.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_ingest_metadata.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_ingest_metadata.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_plaquette_markdown'`

- [ ] **Step 3: Ajouter la lecture du front-matter**

Dans `src/ingestion/ingest_supabase.py`, ajouter après les imports (vers la ligne 30, avant `logger`) :

```python
def read_plaquette_markdown(path: Path) -> tuple[str, Dict[str, Any]]:
    """Lit un markdown de plaquette en separant son front-matter.

    Args:
        path: Chemin du fichier markdown.

    Returns:
        Tuple (contenu sans front-matter, metadonnees du front-matter).
        Les metadonnees sont vides si le fichier n'en porte pas.
    """
    import frontmatter

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return post.content, dict(post.metadata)
```

- [ ] **Step 4: Router les markdown vers cette lecture**

Dans `_read_document`, remplacer le début du bloc `if file_ext in docling_formats:` (ligne 235) par un aiguillage préalable. Insérer **juste avant** ce `if` :

```python
        # Les plaquettes extraites portent un front-matter : le laisser passer
        # dans Docling injecterait les cles YAML dans le texte indexe.
        if file_ext in ('.md', '.markdown'):
            content, _ = read_plaquette_markdown(Path(file_path))
            return (content, None)
```

- [ ] **Step 5: Propager la provenance dans les métadonnées**

Remplacer la signature et le corps de `_extract_document_metadata` (lignes 362-382) par :

```python
    def _extract_document_metadata(
        self,
        content: str,
        file_path: str,
        front_matter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Extract metadata from document content.

        Args:
            content: Document content
            file_path: Path to the document file
            front_matter: Metadata read from the markdown front-matter, if any

        Returns:
            Document metadata dictionary
        """
        metadata: Dict[str, Any] = {
            "file_name": os.path.basename(file_path),
            "file_extension": os.path.splitext(file_path)[1],
            "file_size": os.path.getsize(file_path),
            "word_count": len(content.split()),
            "doc_type": "chunk",
        }
        if front_matter:
            for cle in ("source_file", "extraction", "image_ratio", "extracted_at"):
                if cle in front_matter:
                    metadata[cle] = front_matter[cle]
        return metadata
```

- [ ] **Step 6: Passer le front-matter depuis `_ingest_document`**

Dans `_ingest_document`, remplacer les lignes 402-406 :

```python
            # Read document content
            content, docling_doc = self._read_document(file_path)

            # Extract metadata
            title = self._extract_title(content, file_path)
            metadata = self._extract_document_metadata(content, file_path)
```

par :

```python
            # Read document content
            content, docling_doc = self._read_document(file_path)

            # Les plaquettes portent leur provenance dans un front-matter
            front_matter: Dict[str, Any] = {}
            if os.path.splitext(file_path)[1].lower() in ('.md', '.markdown'):
                _, front_matter = read_plaquette_markdown(Path(file_path))

            # Extract metadata
            title = self._extract_title(content, file_path)
            metadata = self._extract_document_metadata(content, file_path, front_matter)
```

- [ ] **Step 7: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_ingest_metadata.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Vérifier que rien n'est cassé**

Run: `uv run pytest tests/ -v`
Expected: PASS pour tous les tests unitaires

- [ ] **Step 9: Commit**

```bash
git add src/ingestion/ingest_supabase.py tests/ingestion/test_ingest_metadata.py
git commit -m "feat: propage la provenance d'extraction dans les metadonnees"
```

---

### Task 8: Ingestion réelle et recette

**Files:**
- Create: `src/ingestion/verify_ingestion.py`
- Test: `tests/ingestion/test_verify_ingestion.py`

**Interfaces:**
- Consumes: tables `cagecfi_documents` et `cagecfi_chunks` peuplées
- Produces:
  - `IngestionCheck` (Pydantic : `title`, `chunks`, `passed`)
  - `check_all_documents_have_chunks(pool: asyncpg.Pool, settings: SupabaseSettings) -> list[IngestionCheck]` (async)

**Critère de recette :** un document à zéro chunk est une **erreur bloquante**. C'est exactement le mode de défaillance silencieuse que tout ce pipeline vise à empêcher.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/ingestion/test_verify_ingestion.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/ingestion/test_verify_ingestion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.verify_ingestion'`

- [ ] **Step 3: Implémenter `src/ingestion/verify_ingestion.py`**

```python
"""Recette post-ingestion de la base de connaissance CAGECFI.

Un document ingere sans aucun chunk est le mode de defaillance que tout ce
pipeline vise a empecher : la base parait remplie alors qu'elle est vide.
Cette verification le transforme en erreur bloquante.
"""

import asyncio
import logging

import asyncpg
from pydantic import BaseModel, Field

from src.settings_supabase import SupabaseSettings, load_settings

logger = logging.getLogger(__name__)


class IngestionCheck(BaseModel):
    """Resultat de verification pour un document."""

    title: str = Field(..., description="Titre du document")
    chunks: int = Field(..., description="Nombre de chunks rattaches")
    passed: bool = Field(..., description="True si le document porte au moins un chunk")


async def check_all_documents_have_chunks(
    pool: asyncpg.Pool, settings: SupabaseSettings
) -> list[IngestionCheck]:
    """Verifie que chaque document ingere possede au moins un chunk.

    Args:
        pool: Pool de connexions PostgreSQL.
        settings: Configuration portant les noms de tables.

    Returns:
        Un resultat de verification par document distinct.
    """
    requete = f"""
        SELECT d.title, COUNT(c.id) AS n
        FROM (SELECT DISTINCT file_id, title FROM {settings.postgres_table_documents}) d
        LEFT JOIN {settings.postgres_table_chunks} c ON c.file_id = d.file_id
        GROUP BY d.title
        ORDER BY d.title
    """
    async with pool.acquire() as conn:
        lignes = await conn.fetch(requete)

    return [
        IngestionCheck(title=row["title"], chunks=row["n"], passed=row["n"] > 0)
        for row in lignes
    ]


def summarize_checks(checks: list[IngestionCheck]) -> tuple[bool, str]:
    """Resume la recette.

    Args:
        checks: Resultats de verification.

    Returns:
        Tuple (recette reussie, message lisible).
    """
    if not checks:
        return False, "Recette echouee : aucun document dans la base."

    echecs = [c for c in checks if not c.passed]
    if echecs:
        noms = ", ".join(c.title for c in echecs)
        return False, f"Recette echouee : {len(echecs)} document(s) sans chunk : {noms}"

    total = sum(c.chunks for c in checks)
    return True, f"Recette reussie : {len(checks)} documents, {total} chunks."


async def _run() -> None:
    """Execute la recette contre la base configuree."""
    settings = load_settings()
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=5, statement_cache_size=0
    )
    try:
        checks = await check_all_documents_have_chunks(pool, settings)
    finally:
        await pool.close()

    ok, message = summarize_checks(checks)
    for check in checks:
        etat = "OK   " if check.passed else "ECHEC"
        print(f"  {etat} {check.title:<50} {check.chunks} chunks")
    print(f"\n{message}")

    if not ok:
        raise SystemExit(1)


def main() -> None:
    """Point d'entree CLI de la recette."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `uv run pytest tests/ingestion/test_verify_ingestion.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Ingérer réellement le corpus**

Cette commande **purge** `cagecfi_documents` et `cagecfi_chunks` avant d'ingérer, conformément à la décision de remplacer la base issue du crawl.

Run: `uv run python -m src.ingestion.ingest_supabase -d documents/plaquettes_md`
Expected: `Total: 44/44 documents` avec un nombre de chunks non nul pour chacun — 22 plaquettes extraites et leurs 22 fiches produit, toutes présentes dans le même répertoire.

- [ ] **Step 6: Passer la recette**

Run: `uv run python -m src.ingestion.verify_ingestion`
Expected: `Recette reussie : 44 documents, N chunks.` et code de sortie 0

Si un document ressort à 0 chunk, ne pas poursuivre : reprendre son markdown dans `documents/plaquettes_md/` — il est probablement vide ou réduit à des références d'images.

- [ ] **Step 7: Vérifier le comportement du chatbot**

Run: `uv run python -m src.cli_supabase`

Poser les questions correspondant aux deux cas d'usage retenus :
- « Qui est CAGECFI ? » — doit citer la création en 2001, le siège à Lomé au Togo
- « Quelles sont les fonctionnalités de PERFECT ? » — doit lister la gestion de la clientèle, du portefeuille-épargne, du portefeuille-crédit, de la tontine
- « Quelles solutions proposez-vous aux administrations ? » — doit mobiliser les plaquettes du secteur public

Vérifier qu'aucune réponse ne contient de passage en anglais.

- [ ] **Step 8: Commit**

```bash
git add src/ingestion/verify_ingestion.py tests/ingestion/test_verify_ingestion.py
git commit -m "feat: recette post-ingestion bloquante sur les documents sans chunk"
```

---

## Auto-revue

**Couverture de la spec**

| Section de la spec | Tâche |
| --- | --- |
| §4.1 Acquisition Drive | Task 2 |
| §4.2 Audit, dédoublonnage, exclusions | Task 3 |
| §4.3 Extraction routée + nettoyage artefacts | Tasks 4, 5 |
| §4.4 Point de contrôle humain | Task 5, Step 6 |
| §4.5 Fiches produit | Task 6 |
| §4.6 Ingestion et métadonnées | Task 7 |
| §5 Taxonomie | Task 6 (`ProductCategory`) |
| §6 Configuration | Task 1 |
| §7 Tests et critère de recette | Toutes, et Task 8 |

**Trou comblé pendant la revue.** La spec §4.6 prévoit d'indexer les fiches avec `doc_type = "product_sheet"`, mais la première version de la Task 6 construisait les fiches sans jamais les écrire : elles n'auraient donc jamais atteint la base. Les steps 5 à 10 de la Task 6 câblent l'écriture (`write_sheet`, `build_all_sheets`, CLI). Le front-matter des fiches porte `doc_type: product_sheet`, que la Task 7 recopie sans modification — la clé devient ainsi réellement discriminante côté recherche, alors que `_extract_document_metadata` pose `doc_type = "chunk"` par défaut.

**Cohérence des types.** `DocumentAudit` (Task 3) est consommé tel quel par `extract_document` (Task 5). `OcrResult.image_ratio` (Task 4) alimente `ExtractionResult.image_ratio` (Task 5), puis la clé `image_ratio` du front-matter (Task 5), relue par `read_plaquette_markdown` (Task 7). `ProductCategory` (Task 6) reprend exactement les sept valeurs de la spec §5. Les noms de tables passent partout par `settings.postgres_table_*`.

**Placeholders.** Aucun `TBD`, `TODO` ni étape sans code. Les deux seules inconnues restantes sont factuelles et documentées : la limite de taille de l'API Mistral (Task 5, Step 5) et la classification des deux PDF précédemment tronqués (Task 3, Step 5).
