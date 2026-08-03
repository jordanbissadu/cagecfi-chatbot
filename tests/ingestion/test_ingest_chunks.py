"""Tests du filtrage des chunks trop courts avant embedding."""

import pytest

from src.ingestion.chunker import DocumentChunk
from src.ingestion.ingest_supabase import MIN_CHUNK_LENGTH, filter_short_chunks


def _chunk(content: str, index: int) -> DocumentChunk:
    """Construit un DocumentChunk minimal pour les tests de filtrage."""
    return DocumentChunk(
        content=content,
        index=index,
        start_char=0,
        end_char=len(content),
        metadata={},
    )


@pytest.mark.unit
def test_filter_short_chunks_keeps_only_long_chunks() -> None:
    """Seuls les chunks atteignant la longueur minimale sont conserves.

    Reproduit le cas mesure sur CAGECFI : un fragment de titre isole
    ("CAGECFI\\nINFORMATIQUE & MANAGEMENT", 33 caracteres) est ecarte, tandis
    que le paragraphe pertinent ("QUI SOMMES-NOUS ? ... creee en 2001 ...
    Lome") est conserve.
    """
    court_1 = _chunk("img-0.jpeg", 0)
    court_2 = _chunk("CAGECFI\nINFORMATIQUE & MANAGEMENT", 1)
    long_1 = _chunk(
        "QUI SOMMES-NOUS ? CAGECFI est une societe de services creee en "
        "2001 a Lome, specialisee dans l'edition de logiciels financiers.",
        2,
    )
    long_2 = _chunk(
        "A PROPOS DE NOS SOLUTIONS. Nous accompagnons les institutions de "
        "microfinance dans leur transformation digitale depuis vingt ans.",
        3,
    )
    chunks = [court_1, court_2, long_1, long_2]

    conserves = filter_short_chunks(chunks)

    assert conserves == [long_1, long_2]
    assert len(chunks) - len(conserves) == 2
    assert all(len(c.content) >= MIN_CHUNK_LENGTH for c in conserves)


@pytest.mark.unit
def test_filter_short_chunks_boundary_is_inclusive() -> None:
    """Un chunk exactement a la longueur minimale est conserve."""
    pile_au_seuil = _chunk("x" * MIN_CHUNK_LENGTH, 0)
    juste_sous_le_seuil = _chunk("x" * (MIN_CHUNK_LENGTH - 1), 1)

    conserves = filter_short_chunks([pile_au_seuil, juste_sous_le_seuil])

    assert conserves == [pile_au_seuil]


@pytest.mark.unit
def test_filter_short_chunks_empty_list() -> None:
    """Une liste vide ne provoque pas d'erreur et renvoie une liste vide."""
    assert filter_short_chunks([]) == []
