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
