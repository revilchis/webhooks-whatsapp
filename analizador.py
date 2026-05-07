"""
analizador.py — Parseo y análisis de payloads entrantes de WhatsApp Business API (Meta Cloud API).

Convierte el JSON crudo del webhook en estructuras limpias y loggea cada evento.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("wa_tester.analizador")


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------

@dataclass
class MensajeTexto:
    wa_id: str          # número del remitente (e164 sin +)
    nombre: str
    message_id: str
    texto: str
    timestamp: str
    phone_number_id: str


@dataclass
class MensajeInteractivo:
    wa_id: str
    nombre: str
    message_id: str
    tipo_interactivo: str   # "button_reply" | "list_reply"
    id_respuesta: str
    titulo_respuesta: str
    timestamp: str
    phone_number_id: str


@dataclass
class ActualizacionEstado:
    message_id: str
    wa_id: str
    estado: str             # "sent" | "delivered" | "read" | "failed"
    timestamp: str
    phone_number_id: str
    error: dict | None = None


@dataclass
class EventoDesconocido:
    tipo: str
    payload_raw: dict = field(default_factory=dict)


TipoEvento = MensajeTexto | MensajeInteractivo | ActualizacionEstado | EventoDesconocido


# ---------------------------------------------------------------------------
# Validación de firma HMAC-SHA256
# ---------------------------------------------------------------------------

def validar_firma(body_bytes: bytes, header_signature: str, app_secret: str) -> bool:
    """
    Verifica X-Hub-Signature-256: sha256=<hex>

    Meta firma el body raw con el App Secret. Siempre validar antes de procesar.
    Retorna False si falta la firma o no coincide.
    """
    if not header_signature or not header_signature.startswith("sha256="):
        logger.warning("Firma ausente o con formato incorrecto: %s", header_signature)
        return False

    expected = "sha256=" + hmac.new(
        app_secret.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    # Comparación en tiempo constante para evitar timing attacks
    return hmac.compare_digest(expected, header_signature)


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def parsear_payload(payload: dict[str, Any]) -> list[TipoEvento]:
    """
    Extrae todos los eventos de un payload del webhook de Meta.

    Un solo POST puede contener múltiples entries y múltiples changes.
    Retorna lista de eventos tipados.
    """
    eventos: list[TipoEvento] = []

    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            if change.get("field") != "messages":
                logger.debug("Campo ignorado: %s", change.get("field"))
                continue

            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")

            # Contactos — enriquece mensajes con nombre
            contactos: dict[str, str] = {}
            for c in value.get("contacts", []):
                wa_id = c.get("wa_id", "")
                nombre = c.get("profile", {}).get("name", wa_id)
                contactos[wa_id] = nombre

            # ── Mensajes entrantes ──────────────────────────────────────────
            for msg in value.get("messages", []):
                wa_id = msg.get("from", "")
                nombre = contactos.get(wa_id, wa_id)
                message_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                tipo = msg.get("type", "")

                if tipo == "text":
                    texto = msg.get("text", {}).get("body", "")
                    eventos.append(MensajeTexto(
                        wa_id=wa_id,
                        nombre=nombre,
                        message_id=message_id,
                        texto=texto,
                        timestamp=timestamp,
                        phone_number_id=phone_number_id,
                    ))

                elif tipo == "interactive":
                    interactivo = msg.get("interactive", {})
                    tipo_int = interactivo.get("type", "")
                    respuesta = interactivo.get(tipo_int, {})
                    eventos.append(MensajeInteractivo(
                        wa_id=wa_id,
                        nombre=nombre,
                        message_id=message_id,
                        tipo_interactivo=tipo_int,
                        id_respuesta=respuesta.get("id", ""),
                        titulo_respuesta=respuesta.get("title", ""),
                        timestamp=timestamp,
                        phone_number_id=phone_number_id,
                    ))

                else:
                    # audio, image, document, location, sticker, etc.
                    eventos.append(EventoDesconocido(
                        tipo=f"mensaje/{tipo}",
                        payload_raw=msg,
                    ))

            # ── Actualizaciones de estado (sent / delivered / read / failed) ─
            for status in value.get("statuses", []):
                error = status.get("errors", [None])[0] if status.get("errors") else None
                eventos.append(ActualizacionEstado(
                    message_id=status.get("id", ""),
                    wa_id=status.get("recipient_id", ""),
                    estado=status.get("status", ""),
                    timestamp=status.get("timestamp", ""),
                    phone_number_id=phone_number_id,
                    error=error,
                ))

    return eventos


# ---------------------------------------------------------------------------
# Logger de eventos
# ---------------------------------------------------------------------------

def loggear_evento(evento: TipoEvento) -> None:
    """Imprime en consola un resumen legible de cada evento."""
    if isinstance(evento, MensajeTexto):
        logger.info(
            "📨 TEXTO  | de=%s (%s) | id=%s | '%s'",
            evento.nombre, evento.wa_id, evento.message_id[:20], evento.texto[:120],
        )

    elif isinstance(evento, MensajeInteractivo):
        logger.info(
            "🔘 INTERACTIVO | de=%s (%s) | tipo=%s | respuesta=[%s] %s",
            evento.nombre, evento.wa_id, evento.tipo_interactivo,
            evento.id_respuesta, evento.titulo_respuesta,
        )

    elif isinstance(evento, ActualizacionEstado):
        if evento.error:
            logger.warning(
                "⚠️  STATUS  | msg=%s | wa=%s | estado=%s | error=%s",
                evento.message_id[:20], evento.wa_id, evento.estado, evento.error,
            )
        else:
            logger.debug(
                "✓  STATUS  | msg=%s | wa=%s | estado=%s",
                evento.message_id[:20], evento.wa_id, evento.estado,
            )

    elif isinstance(evento, EventoDesconocido):
        logger.info("❓ DESCONOCIDO | tipo=%s", evento.tipo)
