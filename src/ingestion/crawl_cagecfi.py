"""Crawler du site cagecfi.com.

Parcourt le sitemap WordPress, télécharge chaque page et l'exporte en Markdown
(via Docling) dans documents/cagecfi/. Le pipeline d'ingestion prend ensuite
ces fichiers en charge.

Usage:
    uv run python -m src.ingestion.crawl_cagecfi
    uv run python -m src.ingestion.crawl_cagecfi --base https://www.cagecfi.com --out documents/cagecfi
"""

import argparse
import logging
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Sous-sitemaps à ignorer (templates d'en-tête/pied, archives bruitées)
SKIP_SITEMAPS = ("elementor-hf-sitemap", "author-sitemap", "category-sitemap")


def _local(tag: str) -> str:
    """Nom de balise sans namespace."""
    return tag.split("}")[-1]


def collect_urls(client: httpx.Client, sitemap_url: str, seen: set[str]) -> list[str]:
    """Collecte récursivement les URLs de pages depuis un sitemap (index ou urlset)."""
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    if any(s in sitemap_url for s in SKIP_SITEMAPS):
        return []

    try:
        resp = client.get(sitemap_url)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sitemap illisible %s: %s", sitemap_url, exc)
        return []

    locs = [e.text.strip() for e in root.iter() if _local(e.tag) == "loc" and e.text]

    if _local(root.tag) == "sitemapindex":
        urls: list[str] = []
        for sub in locs:
            urls.extend(collect_urls(client, sub, seen))
        return urls

    # urlset : ce sont des pages réelles
    return [u for u in locs if not u.lower().endswith((".jpg", ".png", ".webp", ".pdf"))]


def slugify(url: str) -> str:
    """Construit un nom de fichier à partir de l'URL."""
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", path) or "accueil"
    return slug[:80]


def page_to_markdown(converter: DocumentConverter, url: str, html: bytes) -> str:
    """Convertit le HTML d'une page en Markdown via Docling."""
    source = DocumentStream(name=f"{slugify(url)}.html", stream=BytesIO(html))
    result = converter.convert(source)
    return result.document.export_to_markdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawler cagecfi.com -> Markdown")
    parser.add_argument("--base", default="https://www.cagecfi.com")
    parser.add_argument("--out", default="documents/cagecfi")
    parser.add_argument("--sitemap", default="/wp-sitemap.xml")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    converter = DocumentConverter()

    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "cagecfi-rag-crawler"}) as client:
        urls = collect_urls(client, args.base + args.sitemap, set())
        # Déduplique en conservant l'ordre
        urls = list(dict.fromkeys(urls))
        logger.info("Pages découvertes: %d", len(urls))

        written = 0
        for url in urls:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype:
                    logger.info("Ignoré (non-HTML: %s): %s", ctype, url)
                    continue

                markdown = page_to_markdown(converter, url, resp.content)
                title_line = f"# {url}\n\n_Source: {url}_\n\n"
                dest = out_dir / f"{slugify(url)}.md"
                dest.write_text(title_line + markdown, encoding="utf-8")
                written += 1
                logger.info("OK (%d/%d): %s -> %s", written, len(urls), url, dest.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Échec %s: %s", url, exc)

        logger.info("Terminé: %d pages écrites dans %s", written, out_dir)


if __name__ == "__main__":
    main()
