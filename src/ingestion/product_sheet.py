"""Generation des fiches produit structurees a partir des plaquettes.

A la question « que fait Perfect-Vision ? », une fiche de synthese repond mieux
qu'un fragment de plaquette isole. Les fiches sont indexees en plus des chunks
bruts, qui restent necessaires aux questions de detail.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Literal, Optional

import frontmatter
import openai
import yaml
from pydantic import BaseModel, Field, ValidationError

from src.settings_supabase import SupabaseSettings, load_settings

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

MAX_MARKDOWN_CHARS = 60000
"""Longueur maximale de markdown envoyee au LLM.

gpt-4o-mini offre 128k tokens de contexte ; 60000 caracteres (~17000 tokens)
laisse largement passer les plus grosses plaquettes du corpus (24502 et 21828
caracteres) sans jamais tronquer leur contenu.
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

    if len(markdown) > MAX_MARKDOWN_CHARS:
        logger.warning(
            "plaquette_tronquee slug=%s caracteres=%d limite=%d",
            slug, len(markdown), MAX_MARKDOWN_CHARS,
        )

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "user", "content": SHEET_PROMPT + markdown[:MAX_MARKDOWN_CHARS]}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return ProductSheet(**payload)
    except (json.JSONDecodeError, ValidationError, openai.APIError, TypeError):
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
        Chemins des fiches ecrites. Une erreur de lecture, de parsing du
        front-matter ou d'ecriture sur un document est capturee et journalisee
        plutot que d'interrompre le traitement des documents suivants.
    """
    settings = load_settings()
    ecrites: list[Path] = []

    for source in sorted(md_dir.glob("*.md")):
        if source.stem.endswith("_fiche"):
            continue

        try:
            post = frontmatter.loads(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            logger.exception("plaquette_illisible slug=%s", source.stem)
            continue

        sheet = await build_sheet(post.content, source.stem, settings)
        if sheet is None:
            logger.warning("fiche_ignoree slug=%s", source.stem)
            continue

        try:
            ecrites.append(write_sheet(sheet, source.stem, md_dir))
        except OSError:
            logger.exception("ecriture_fiche_echouee slug=%s", source.stem)

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
