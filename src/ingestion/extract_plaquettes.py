"""Extraction routee des plaquettes vers du markdown relisible.

Le routage est dicte par l'audit : Docling sans OCR pour les seuls documents
classes TEXTE (couche texte suffisante), Mistral OCR pour MIXTE et IMAGE. En
dessous de 400 caracteres/page, la couche texte est trop pauvre pour que
Docling en tire quoi que ce soit d'exploitable : mesure sur l'unique document
MIXTE du corpus, CAGECFI_Presentation_Insertion.pdf (82 caracteres/page) —
Docling y extrait 15 mots reels et du texte mutile ("PERFECT- VI SI O N"),
noye dans des `<!-- image -->`, quand Mistral OCR en tire 177 mots propres.
Le markdown produit est un artefact versionnable, destine a etre relu avant
vectorisation.
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
from src.ingestion.pdf_audit import DocumentAudit, DocumentKind
from src.settings_supabase import SupabaseSettings, load_settings

logger = logging.getLogger(__name__)

ExtractionMethod = Literal["docling", "mistral_ocr"]


def route_extraction_method(kind: DocumentKind) -> ExtractionMethod:
    """Determine la voie d'extraction a partir de la classification d'audit.

    Seuls les documents TEXTE empruntent Docling. En dessous de 400
    caracteres/page (seuil de classification MIXTE/IMAGE, voir
    `pdf_audit.classify`), la couche texte est trop pauvre pour que Docling
    en tire quoi que ce soit d'exploitable : mesure sur l'unique document
    MIXTE du corpus, qui donne 15 mots reels et du texte mutile par Docling
    contre 177 mots propres par Mistral OCR.

    Args:
        kind: Classification d'audit du document.

    Returns:
        La voie d'extraction a emprunter.
    """
    return "docling" if kind == "TEXTE" else "mistral_ocr"


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
    method: ExtractionMethod = route_extraction_method(audit.kind)

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
        Liste des resultats, succes comme echecs. Une erreur d'ecriture disque
        sur un document est capturee et marque ce document en echec plutot
        que d'interrompre le traitement des documents suivants.
    """
    audits = [DocumentAudit(**row) for row in json.loads(audit_path.read_text(encoding="utf-8"))]
    retenus = [a for a in audits if a.is_retained]
    settings = load_settings()

    resultats: list[ExtractionResult] = []
    for audit in retenus:
        result = await extract_document(audit, pdf_dir, settings)
        if result.succeeded:
            try:
                write_markdown(result, dest_dir)
            except OSError as exc:
                logger.exception("ecriture_echouee fichier=%s", result.filename)
                result.error = str(exc)
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
