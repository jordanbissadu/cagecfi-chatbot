"""API web FastAPI pour le chatbot CAGECFI.

Sert la landing page (frontend/index.html) et expose l'endpoint /chat qui
exécute l'agent Pydantic AI. Même origine que la page → pas de problème CORS
en local ; CORS est tout de même activé pour permettre l'embarquement futur
sur cagecfi.com.

Lancement:
    uv run uvicorn src.api:app --reload --port 8000
Puis ouvrir http://localhost:8000
"""

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from src import rag_chat

logger = logging.getLogger(__name__)

app = FastAPI(title="Assistant CAGECFI", version="1.0.0")

# CORS : ouvert en local ; restreindre aux domaines CAGECFI en production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.on_event("startup")
async def _warmup() -> None:
    """Précharge le modèle LLM en arrière-plan pour éviter la lenteur du 1er appel.

    Désactivé par défaut en environnement serverless (Vercel) : chaque cold start
    relancerait un appel LLM facturé et potentiellement interrompu. Activer avec
    ENABLE_WARMUP=1 uniquement sur un serveur persistant.
    """
    if os.getenv("ENABLE_WARMUP", "0") != "1":
        return

    async def _run() -> None:
        try:
            await rag_chat.warmup()
            logger.info("warmup_done: modèle LLM préchargé")
        except Exception as exc:  # noqa: BLE001
            logger.warning("warmup_failed: %s", exc)

    asyncio.create_task(_run())


class ChatMessage(BaseModel):
    """Un tour de conversation envoyé par le widget."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Charge utile de POST /chat."""

    message: str = Field(..., description="Message de l'utilisateur")
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Réponse renvoyée au widget."""

    response: str


@app.get("/health")
async def health() -> dict[str, str]:
    """Vérification de disponibilité."""
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest) -> PlainTextResponse:
    """Exécute la recherche forcée + rédaction et renvoie la réponse complète.

    Réponse NON-streaming (un seul bloc de texte) : c'est le mode robuste pour
    Vercel, dont le runtime Python peut bufferiser un flux. Le widget de chat lit
    le corps via un reader et affiche le texte d'un coup — aucun changement
    frontend nécessaire.
    """
    try:
        answer = await rag_chat.answer(req.message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat_failed: %s", exc)
        answer = (
            "Désolé, une erreur technique est survenue. Réessayez ou "
            "contactez-nous à cagecfi@cagecfi.com (+228 22 26 84 61)."
        )
    return PlainTextResponse(answer, media_type="text/plain; charset=utf-8")


@app.get("/")
async def index() -> FileResponse:
    """Sert la landing page CAGECFI."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": "frontend/index.html introuvable"},
        )
    return FileResponse(index_file)
