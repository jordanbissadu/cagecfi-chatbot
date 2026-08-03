"""Tests de la recette post-ingestion."""

from typing import Any

import pytest

from src.ingestion.verify_ingestion import (
    IngestionCheck,
    check_all_documents_have_chunks,
    summarize_checks,
)
from src.settings_supabase import SupabaseSettings


@pytest.mark.unit
def test_summarize_flags_document_without_chunks() -> None:
    """Un document sans chunk fait echouer la recette."""
    checks = [
        IngestionCheck(title="PERFECT", source="perfect_fiche.md", chunks=12, passed=True),
        IngestionCheck(title="GOMISE", source="gomise.md", chunks=0, passed=False),
    ]

    ok, message = summarize_checks(checks)

    assert ok is False
    assert "GOMISE" in message


@pytest.mark.unit
def test_summarize_passes_when_all_documents_have_chunks() -> None:
    """La recette passe quand chaque document porte au moins un chunk."""
    checks = [
        IngestionCheck(title="PERFECT", source="perfect_fiche.md", chunks=12, passed=True),
        IngestionCheck(title="GOMISE", source="gomise_fiche.md", chunks=7, passed=True),
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


@pytest.mark.unit
def test_summarize_distinguishes_homonyms_with_different_sources() -> None:
    """Deux documents de meme titre en echec doivent rester distinguables."""
    checks = [
        IngestionCheck(title="PERFECT", source="PERFECT.md", chunks=0, passed=False),
        IngestionCheck(title="PERFECT", source="PERFECT_fiche.md", chunks=0, passed=False),
    ]

    ok, message = summarize_checks(checks)

    assert ok is False
    assert "PERFECT.md" in message
    assert "PERFECT_fiche.md" in message


class _FakeConnection:
    """Simule ``asyncpg.Connection.fetch`` sans se connecter a une base.

    Reproduit fidelement, a partir de la clause ``GROUP BY`` presente dans
    la requete SQL recue, le comportement d'un vrai moteur PostgreSQL. Cela
    permet au test de rester sensible a une regression du regroupement
    (par ``title`` au lieu de ``file_id``) sans jamais ouvrir de connexion
    reseau.
    """

    def __init__(self, documents: list[dict[str, str]], chunks: list[dict[str, str]]) -> None:
        self._documents = documents
        self._chunks = chunks

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        """Execute en memoire l'equivalent de la requete de verification."""
        distinct_docs = {
            (doc["file_id"], doc["title"], doc["source"]) for doc in self._documents
        }
        comptes: dict[str, int] = {}
        for chunk in self._chunks:
            comptes[chunk["file_id"]] = comptes.get(chunk["file_id"], 0) + 1

        joined = [
            {"file_id": file_id, "title": title, "source": source, "n": comptes.get(file_id, 0)}
            for file_id, title, source in distinct_docs
        ]

        clause_group_by = query.split("GROUP BY", 1)[1].split("ORDER BY", 1)[0]
        regroupe_par_file_id = "file_id" in clause_group_by

        if regroupe_par_file_id:
            return sorted(joined, key=lambda r: (str(r["title"]), str(r["source"])))

        # Reproduit le bug historique : regroupement par titre seul, qui
        # fusionne deux documents homonymes et masque celui sans chunk.
        regroupe: dict[str, dict[str, Any]] = {}
        for row in joined:
            titre = str(row["title"])
            if titre not in regroupe:
                regroupe[titre] = {"title": titre, "source": row["source"], "n": 0}
            regroupe[titre]["n"] += row["n"]
        return sorted(regroupe.values(), key=lambda r: str(r["title"]))


class _FakeAcquireContext:
    """Context manager async minimal imitant ``Pool.acquire()``."""

    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FakePool:
    """Substitut de ``asyncpg.Pool`` pour tester sans base reelle."""

    def __init__(self, documents: list[dict[str, str]], chunks: list[dict[str, str]]) -> None:
        self._connection = _FakeConnection(documents, chunks)

    def acquire(self) -> _FakeAcquireContext:
        """Retourne un context manager async donnant acces a la connexion factice."""
        return _FakeAcquireContext(self._connection)


@pytest.mark.unit
async def test_check_all_documents_have_chunks_treats_homonyms_as_distinct() -> None:
    """Deux documents de meme titre doivent produire deux verifications.

    Sans le correctif (regroupement par ``title``), la plaquette sans chunk
    et sa fiche produit homonyme sont fusionnees en une seule ligne creditee
    des 12 chunks de la fiche : la recette passerait a tort. Avec le
    correctif (regroupement par ``file_id``), les deux documents restent
    distincts et l'un des deux echoue.
    """
    documents = [
        {"file_id": "doc-plaquette", "title": "PERFECT", "source": "documents/plaquettes_md/PERFECT.md"},
        {
            "file_id": "doc-fiche",
            "title": "PERFECT",
            "source": "documents/plaquettes_md/PERFECT_fiche.md",
        },
    ]
    chunks = [{"file_id": "doc-fiche"} for _ in range(12)]  # la plaquette n'a aucun chunk

    pool = _FakePool(documents, chunks)
    settings = SupabaseSettings(
        supabase_url="https://example.invalid",
        supabase_anon_key="anon-test",
        supabase_service_role_key="service-role-test",
        database_url="postgresql://user:pass@localhost/test",
    )

    checks = await check_all_documents_have_chunks(pool, settings)  # type: ignore[arg-type]

    assert len(checks) == 2

    echecs = [c for c in checks if not c.passed]
    reussites = [c for c in checks if c.passed]
    assert len(echecs) == 1
    assert len(reussites) == 1
    assert echecs[0].chunks == 0
    assert echecs[0].source == "documents/plaquettes_md/PERFECT.md"
    assert reussites[0].chunks == 12
    assert reussites[0].source == "documents/plaquettes_md/PERFECT_fiche.md"
