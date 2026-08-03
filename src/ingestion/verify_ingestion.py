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
