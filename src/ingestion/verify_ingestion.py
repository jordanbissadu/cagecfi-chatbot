"""Recette post-ingestion de la base de connaissance CAGECFI.

Un document ingere sans aucun chunk est le mode de defaillance que tout ce
pipeline vise a empecher : la base parait remplie alors qu'elle est vide.
Cette verification le transforme en erreur bloquante.

Un second mode de defaillance, plus insidieux, echappe a la seule
verification "chaque document a des chunks" : si l'extraction perd des
documents en silence (ex. une plaquette qui echoue et ne produit ni markdown
ni fiche), la base parait saine car tout ce qu'elle contient est bien
chunke — elle est juste incomplete. La reconciliation avec le rapport
d'audit (`documents/plaquettes_audit.json`) detecte ce cas.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import asyncpg
from pydantic import BaseModel, Field

from src.ingestion.pdf_audit import DocumentAudit
from src.settings_supabase import SupabaseSettings, load_settings

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_PATH = Path("documents/plaquettes_audit.json")


class IngestionCheck(BaseModel):
    """Resultat de verification pour un document.

    Un document est identifie sans ambiguite par son ``file_id`` en base.
    Le ``title`` n'est qu'une etiquette d'affichage : plusieurs documents
    distincts (une plaquette et sa fiche produit, par exemple) peuvent
    partager le meme titre. ``source`` permet de les distinguer a l'ecran.
    """

    title: str = Field(..., description="Titre du document (non unique)")
    source: str = Field(
        ..., description="Chemin ou reference source du document, pour distinguer deux homonymes"
    )
    chunks: int = Field(..., description="Nombre de chunks rattaches")
    passed: bool = Field(..., description="True si le document porte au moins un chunk")


async def check_all_documents_have_chunks(
    pool: asyncpg.Pool, settings: SupabaseSettings
) -> list[IngestionCheck]:
    """Verifie que chaque document ingere possede au moins un chunk.

    Le regroupement se fait par ``file_id``, la cle reelle d'un document,
    et non par ``title`` : plusieurs documents distincts (une plaquette et
    sa fiche produit) peuvent partager le meme titre, et regrouper par titre
    masquerait un document sans chunk derriere le compte de son homonyme.

    Args:
        pool: Pool de connexions PostgreSQL.
        settings: Configuration portant les noms de tables.

    Returns:
        Un resultat de verification par document distinct (par file_id).
    """
    requete = f"""
        SELECT d.file_id, d.title, d.source, COUNT(c.id) AS n
        FROM (
            SELECT DISTINCT file_id, title, source
            FROM {settings.postgres_table_documents}
        ) d
        LEFT JOIN {settings.postgres_table_chunks} c ON c.file_id = d.file_id
        GROUP BY d.file_id, d.title, d.source
        ORDER BY d.title, d.source
    """
    async with pool.acquire() as conn:
        lignes = await conn.fetch(requete)

    return [
        IngestionCheck(
            title=row["title"],
            source=row["source"],
            chunks=row["n"],
            passed=row["n"] > 0,
        )
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
        noms = ", ".join(f"{c.title} ({c.source})" for c in echecs)
        return False, f"Recette echouee : {len(echecs)} document(s) sans chunk : {noms}"

    total = sum(c.chunks for c in checks)
    return True, f"Recette reussie : {len(checks)} documents, {total} chunks."


def load_expected_document_count(audit_path: Path) -> Optional[int]:
    """Lit dans l'audit d'extractibilite le nombre de documents attendus en base.

    Chaque plaquette retenue par l'audit (`pdf_audit.py`) produit exactement
    deux documents ingeres : son markdown extrait et sa fiche produit de
    synthese. Le nombre attendu est donc le double du nombre de plaquettes
    retenues.

    Args:
        audit_path: Chemin du rapport JSON produit par `pdf_audit.py`.

    Returns:
        Le nombre de documents attendus, ou None si le rapport d'audit est
        absent : la reconciliation est alors impossible plutot qu'en echec.
    """
    if not audit_path.exists():
        logger.warning("audit_absent fichier=%s : reconciliation impossible", audit_path)
        return None

    lignes = json.loads(audit_path.read_text(encoding="utf-8"))
    audits = [DocumentAudit(**ligne) for ligne in lignes]
    retenus = sum(1 for audit in audits if audit.is_retained)
    return 2 * retenus


def reconcile_document_count(actual: int, expected: Optional[int]) -> tuple[bool, str]:
    """Compare le nombre de documents trouves en base au nombre attendu par l'audit.

    Args:
        actual: Nombre de documents distincts trouves en base (``len(checks)``).
        expected: Nombre de documents attendus (2 x plaquettes retenues), ou
            None si le rapport d'audit est indisponible.

    Returns:
        Tuple (reconciliation reussie, message lisible indiquant attendu et
        obtenu). Si `expected` est None, la reconciliation est signalee comme
        impossible mais ne fait pas echouer la recette.
    """
    if expected is None:
        return True, "Reconciliation ignoree : rapport d'audit introuvable."
    if actual != expected:
        return (
            False,
            f"Reconciliation echouee : {expected} documents attendus, {actual} trouves en base.",
        )
    return True, f"Reconciliation reussie : {actual} documents (attendu {expected})."


async def _run(audit_path: Path = DEFAULT_AUDIT_PATH) -> None:
    """Execute la recette contre la base configuree.

    Args:
        audit_path: Chemin du rapport d'audit JSON utilise pour reconcilier
            le nombre de documents attendus et obtenus.
    """
    settings = load_settings()
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=5, statement_cache_size=0
    )
    try:
        checks = await check_all_documents_have_chunks(pool, settings)
    finally:
        await pool.close()

    ok, message = summarize_checks(checks)
    expected = load_expected_document_count(audit_path)
    reconciliation_ok, reconciliation_message = reconcile_document_count(len(checks), expected)

    for check in checks:
        etat = "OK   " if check.passed else "ECHEC"
        print(f"  {etat} {check.title:<40} {check.source:<45} {check.chunks} chunks")
    print(f"\n{message}")
    print(reconciliation_message)

    if not ok or not reconciliation_ok:
        raise SystemExit(1)


def main() -> None:
    """Point d'entree CLI de la recette."""
    import argparse

    parser = argparse.ArgumentParser(description="Recette post-ingestion CAGECFI.")
    parser.add_argument(
        "--audit-path",
        type=Path,
        default=DEFAULT_AUDIT_PATH,
        help="Chemin du rapport d'audit JSON pour la reconciliation des documents.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    asyncio.run(_run(args.audit_path))


if __name__ == "__main__":
    main()
