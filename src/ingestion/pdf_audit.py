"""Audit d'extractibilite du corpus de plaquettes.

Determine, pour chaque PDF, s'il possede une couche texte exploitable. Ce
routage n'est pas une optimisation : 94% des pages du corpus sont des visuels
sans aucun caractere extractible, et une ingestion naive les indexerait vides
sans lever d'erreur.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pypdf import PdfReader

logger = logging.getLogger(__name__)

DocumentKind = Literal["TEXTE", "MIXTE", "IMAGE"]

SEUIL_TEXTE = 400
SEUIL_MIXTE = 50

# Glyphes non mappes : polices vectorisees sans table Unicode. pypdf les
# restitue sous forme de references litterales ("/gid00010", "(cid:42)") dont
# les lettres alphabetiques ("g", "i", "d") fausseraient le comptage de texte
# exploitable si elles n'etaient pas retirees avant classification.
_GLYPHES_NON_MAPPES = re.compile(r"/gid\d+|\(cid:\d+\)")

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


def strip_unmapped_glyphs(text: str) -> str:
    """Retire les references de glyphes non mappes d'un texte extrait par pypdf.

    Args:
        text: Texte brut renvoye par `page.extract_text()`.

    Returns:
        Texte debarrasse des motifs `/gidNNNNN` et `(cid:NN)`.
    """
    return _GLYPHES_NON_MAPPES.sub("", text)


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
                texte = strip_unmapped_glyphs(page.extract_text() or "")
                alpha += sum(c.isalpha() for c in texte)
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
    silencieusement du pipeline. Les doublons d'un document exclu sont aussi
    exclus (motif: doublon), pour garantir la coherence du pipeline d'ingestion.

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
            premier_par_hash[copie.md5] = copie.filename  # Enregistrer même les documents exclus
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
