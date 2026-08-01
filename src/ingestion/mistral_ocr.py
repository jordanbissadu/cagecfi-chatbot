"""Client Mistral OCR pour les plaquettes sans couche texte.

Mesures relevees le 2026-07-31 sur le corpus reel : 1 a 5 secondes par page,
un envoi de 11,1 Mo accepte, et une qualite francaise nettement superieure a
l'OCR local (73 accents corrects contre 54 sur PERFECT.pdf).

Au-dela de MISTRAL_SIZE_THRESHOLD_BYTES, l'API renvoie 503 sur l'envoi du PDF
entier (constate sur un document de 89,3 Mo). Le repli mesure le meme jour :
rendre chaque page en JPEG via pypdfium2 (echelle 2, qualite 85) la fait
tomber a 0,3-0,4 Mo, acceptee en 200 en 3-4 secondes par page.
"""

import base64
import io
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from src.settings_supabase import SupabaseSettings

logger = logging.getLogger(__name__)

OCR_ENDPOINT = "https://api.mistral.ai/v1/ocr"

# Au-dela de ce seuil, l'API rejette l'envoi du PDF entier (503 constate a
# 89,3 Mo) : on bascule sur un envoi page par page en image.
MISTRAL_SIZE_THRESHOLD_BYTES = 20 * 1024 * 1024

# Parametres de rendu du repli image, valides par appel reel le 2026-07-31.
_PDFIUM_RENDER_SCALE = 2
_PDFIUM_JPEG_QUALITY = 85

# Puces graphiques rendues en LaTeX par l'OCR : \(\odot\), \(\mathbb{O}\), etc.
_ARTEFACTS_LATEX = re.compile(r"\\\(\s*\\[A-Za-z]+(?:\{[^}]*\})?\s*\\\)\s*")
_LIGNES_VIDES = re.compile(r"\n{3,}")
_REF_IMAGE = re.compile(r"!\[img-\d+\.\w+\]")

# Corps JSON renvoye par l'API : structure externe non typee par Mistral.
JsonDict = dict[str, Any]  # justification : payload JSON tiers, forme non contractuelle


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


def render_pages_to_jpeg(path: Path) -> list[bytes]:
    """Rend chaque page d'un PDF en image JPEG via pypdfium2.

    Repli utilise quand le PDF entier depasse MISTRAL_SIZE_THRESHOLD_BYTES :
    une page rendue individuellement tient largement sous la limite de taille
    par requete de l'API OCR.

    Args:
        path: Chemin du PDF source.

    Returns:
        Images JPEG encodees, une par page, dans l'ordre du document.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        images: list[bytes] = []
        for page in document:
            bitmap = page.render(scale=_PDFIUM_RENDER_SCALE)
            buffer = io.BytesIO()
            bitmap.to_pil().convert("RGB").save(
                buffer, format="JPEG", quality=_PDFIUM_JPEG_QUALITY
            )
            images.append(buffer.getvalue())
        return images
    finally:
        document.close()


async def _send_ocr_request(
    client: httpx.AsyncClient, settings: SupabaseSettings, payload: JsonDict
) -> JsonDict:
    """Envoie une requete a l'API Mistral OCR et renvoie le corps JSON.

    Isolee dans sa propre fonction pour etre substituable dans les tests
    unitaires sans appel reseau reel.

    Args:
        client: Client HTTP partage pour la duree de la transcription.
        settings: Configuration portant la cle API.
        payload: Corps de la requete (document entier ou image de page).

    Returns:
        Corps JSON de la reponse.

    Raises:
        httpx.HTTPStatusError: Si l'API repond une erreur.
    """
    response = await client.post(
        OCR_ENDPOINT,
        headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
        json=payload,
    )
    response.raise_for_status()
    result: JsonDict = response.json()
    return result


def _pages_from_response(data: JsonDict, index_offset: int = 0) -> list[OcrPage]:
    """Convertit le corps JSON d'une reponse OCR en pages nettoyees.

    Args:
        data: Corps JSON renvoye par l'API pour un document ou une image.
        index_offset: Decalage applique aux index de page. Necessaire pour le
            repli image par image, ou chaque reponse redemarre a l'index 0.

    Returns:
        Pages nettoyees, indexees dans le referentiel global du document.
    """
    pages: list[OcrPage] = []
    for local_index, page in enumerate(data.get("pages", [])):
        brut = page.get("markdown", "")
        pages.append(
            OcrPage(
                index=index_offset + local_index,
                markdown=clean_artifacts(brut),
                image_refs=len(_REF_IMAGE.findall(brut)),
            )
        )
    return pages


def _document_payload(pdf_bytes: bytes, settings: SupabaseSettings) -> JsonDict:
    """Construit le payload d'envoi du PDF entier.

    Args:
        pdf_bytes: Contenu binaire du PDF.
        settings: Configuration portant le modele OCR.

    Returns:
        Payload pret a etre envoye a l'API.
    """
    encoded = base64.b64encode(pdf_bytes).decode()
    return {
        "model": settings.mistral_ocr_model,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{encoded}",
        },
        "include_image_base64": False,
    }


def _image_payload(jpeg_bytes: bytes, settings: SupabaseSettings) -> JsonDict:
    """Construit le payload d'envoi d'une page rendue en image.

    Args:
        jpeg_bytes: Contenu binaire de l'image JPEG.
        settings: Configuration portant le modele OCR.

    Returns:
        Payload pret a etre envoye a l'API.
    """
    encoded = base64.b64encode(jpeg_bytes).decode()
    return {
        "model": settings.mistral_ocr_model,
        "document": {
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{encoded}",
        },
        "include_image_base64": False,
    }


async def ocr_pdf(path: Path, settings: SupabaseSettings) -> OcrResult:
    """Transcrit un PDF via l'API Mistral OCR.

    En dessous de MISTRAL_SIZE_THRESHOLD_BYTES, le PDF entier est envoye en
    une requete. Au-dela, chaque page est rendue en image JPEG et envoyee
    individuellement : l'API rejette les PDF volumineux (503 constate a
    89,3 Mo) mais accepte chaque page rendue, largement plus legere.

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

    pdf_bytes = path.read_bytes()
    pages: list[OcrPage] = []

    async with httpx.AsyncClient(timeout=600.0) as client:
        if len(pdf_bytes) <= MISTRAL_SIZE_THRESHOLD_BYTES:
            data = await _send_ocr_request(client, settings, _document_payload(pdf_bytes, settings))
            pages = _pages_from_response(data)
        else:
            logger.info(
                "ocr_repli_images fichier=%s taille=%d", path.name, len(pdf_bytes)
            )
            for index, jpeg_bytes in enumerate(render_pages_to_jpeg(path)):
                data = await _send_ocr_request(client, settings, _image_payload(jpeg_bytes, settings))
                pages.extend(_pages_from_response(data, index_offset=index))

    result = OcrResult(
        pages=pages,
        markdown="\n\n".join(p.markdown for p in pages).strip(),
    )
    logger.info(
        "ocr_termine fichier=%s pages=%d ratio_images=%.2f",
        path.name, len(pages), result.image_ratio,
    )
    return result
