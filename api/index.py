"""Point d'entrée Vercel (fonction serverless) pour l'assistant CAGECFI.

Vercel exécute ce module comme une fonction Python et détecte automatiquement
la variable `app` (application ASGI). Tout le trafic est routé ici via le
rewrite catch-all de vercel.json : FastAPI sert à la fois la landing page
(`/`), l'endpoint `/chat` et `/health`.

En production, la configuration ne vient PAS d'un fichier .env mais des
variables d'environnement définies dans le dashboard Vercel
(Project Settings → Environment Variables).
"""

import sys
from pathlib import Path

# Rendre le package `src` importable depuis la racine du dépôt.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api import app  # noqa: E402  (import après ajustement du sys.path)

__all__ = ["app"]
