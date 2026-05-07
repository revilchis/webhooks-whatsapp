"""
main.py — Webhook de validación para WhatsApp Business API (Meta Cloud API).

Propósito: verificar la conexión con Meta y observar payloads reales antes
           de implementar el webhook de producción.

Endpoints:
  GET  /webhook  — verificación del webhook (hub.challenge)
  POST /webhook  — recepción de mensajes y eventos

Uso local:
  pip install -r requirements.txt
  cp .env.example .env   # completar variables
  uvicorn main:app --reload --port 8080

Para exponer localmente (requiere cuenta gratuita en ngrok):
  ngrok http 8080
  # Copiar la URL https://xxxx.ngrok.io al panel de Meta Developers
  # App > WhatsApp > Configuration > Webhook URL: https://xxxx.ngrok.io/webhook
  # Verify Token: el valor de WHATSAPP_VERIFY_TOKEN en tu .env
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from analizador import (
    ActualizacionEstado,
    EventoDesconocido,
    MensajeInteractivo,
    MensajeTexto,
    loggear_evento,
    parsear_payload,
    validar_firma,
)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "mi_token_secreto")
APP_SECRET: str = os.getenv("WHATSAPP_APP_SECRET", "")
VALIDAR_FIRMA: bool = os.getenv("VALIDAR_FIRMA_HMAC", "true").lower() == "true"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wa_tester.main")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="WhatsApp Webhook Tester", version="1.0.0")

# Deduplicación en memoria — evita procesar el mismo message_id dos veces
# Meta puede reenviar el mismo evento si no respondemos 200 a tiempo
_mensajes_vistos: deque[str] = deque(maxlen=500)

# Registro de todos los eventos recibidos (en RAM, solo para validación)
_historial: list[dict] = []


# ---------------------------------------------------------------------------
# GET /webhook — Verificación de Meta
# ---------------------------------------------------------------------------

@app.get("/webhook", response_class=PlainTextResponse)
async def verificar_webhook(request: Request) -> str:
    """
    Meta llama a este endpoint cuando configuras el webhook en el panel de
    Meta Developers. Debes responder con hub.challenge si hub.verify_token coincide.

    Parámetros que envía Meta (query string):
      hub.mode         = "subscribe"
      hub.verify_token = el token que configuraste en el panel
      hub.challenge    = string aleatorio que debes devolver tal cual
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logger.info("GET /webhook — mode=%s token=%s challenge=%s", mode, token, challenge)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ Webhook verificado correctamente")
        return challenge or ""

    logger.warning("❌ Verificación fallida — token recibido: '%s', esperado: '%s'", token, VERIFY_TOKEN)
    raise HTTPException(status_code=403, detail="Verify token no coincide")


# ---------------------------------------------------------------------------
# POST /webhook — Recepción de mensajes
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def recibir_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Meta envía aquí todos los eventos: mensajes entrantes, estados de entrega,
    reacciones, etc.

    IMPORTANTE: Meta requiere respuesta HTTP 200 en menos de 20 segundos.
    Si no la recibe, reintentará el envío varias veces.
    Por eso procesamos en BackgroundTask y respondemos 200 inmediatamente.
    """
    body_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Validar firma HMAC si APP_SECRET está configurado
    if VALIDAR_FIRMA and APP_SECRET:
        if not validar_firma(body_bytes, signature, APP_SECRET):
            logger.warning("❌ Firma HMAC inválida — posible payload no-Meta")
            raise HTTPException(status_code=401, detail="Firma inválida")
    elif VALIDAR_FIRMA and not APP_SECRET:
        logger.warning("⚠️  VALIDAR_FIRMA=true pero WHATSAPP_APP_SECRET no está configurado — saltando validación")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        logger.error("❌ Payload no es JSON válido")
        raise HTTPException(status_code=400, detail="JSON inválido")

    # Responder 200 inmediatamente y procesar en background
    background_tasks.add_task(_procesar_payload, payload)
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Procesamiento en background
# ---------------------------------------------------------------------------

def _procesar_payload(payload: dict) -> None:
    """Parsea y loggea todos los eventos del payload."""
    logger.debug("Payload completo:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    eventos = parsear_payload(payload)

    if not eventos:
        logger.info("Payload sin eventos reconocibles (¿notificación de sistema?)")
        return

    for evento in eventos:
        # Deduplicar mensajes y eventos de estado por message_id
        mid = _extraer_message_id(evento)
        if mid and mid in _mensajes_vistos:
            logger.debug("Duplicado ignorado — message_id=%s", mid[:20])
            continue
        if mid:
            _mensajes_vistos.append(mid)

        loggear_evento(evento)
        _historial.append({
            "ts": datetime.utcnow().isoformat(),
            "tipo": type(evento).__name__,
            "evento": _evento_a_dict(evento),
        })


def _extraer_message_id(evento) -> str | None:
    if isinstance(evento, (MensajeTexto, MensajeInteractivo)):
        return evento.message_id
    if isinstance(evento, ActualizacionEstado):
        return f"status:{evento.message_id}:{evento.estado}"
    return None


def _evento_a_dict(evento) -> dict:
    if isinstance(evento, EventoDesconocido):
        return {"tipo": evento.tipo, "raw": evento.payload_raw}
    return evento.__dict__


# ---------------------------------------------------------------------------
# GET /historial — Consultar eventos recibidos (solo para debugging)
# ---------------------------------------------------------------------------

@app.get("/historial")
async def ver_historial(limit: int = 20) -> dict:
    """
    Devuelve los últimos N eventos recibidos.
    Solo para validación — no exponer en producción.
    """
    return {
        "total": len(_historial),
        "ultimos": _historial[-limit:],
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "mensajes_procesados": len(_historial)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
