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
            except (httpx.HTTPError, ValueError, OSError) as exc:
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
