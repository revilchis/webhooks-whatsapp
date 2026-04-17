import os
import httpx
import logging
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Response

# 1. CONFIGURACIÓN DE LOGS (Vital para ver errores en Render)
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("GeommaAI.CloudGateway")

# 2. CARGA DE CREDENCIALES
# Prioriza variables de Render; si no existen, busca el archivo local
def cargar_entorno():
    ruta_actual = Path(__file__).resolve()
    for padre in ruta_actual.parents:
        posible_ruta = padre / "shared" / "credentials" / ".env.global"
        if posible_ruta.exists():
            load_dotenv(posible_ruta)
            logger.info(f"📁 Modo Local: Cargando desde {posible_ruta}")
            return
    logger.info("☁️  Modo Cloud: Usando variables de entorno de Render.")

cargar_entorno()

# 3. CLASE GATEWAY (La "Boca" - Envía mensajes)
class WhatsAppGateway:
    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN")
        self.phone_id = os.getenv("WHATSAPP_PHONE_ID")
        self.verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.version = "v21.0"
        self.base_url = f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages"

        if not self.token or not self.phone_id:
            logger.critical("🚨 ERROR: Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_ID en Render.")

    async def enviar_texto(self, numero: str, texto: str):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text",
            "text": {"body": texto}
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                res_data = response.json()
                # LOG CRÍTICO: Aquí verás por qué Meta te rechaza el mensaje
                logger.info(f"🔍 RESPUESTA DE META: {res_data}")
                return res_data
            except Exception as e:
                logger.error(f"❌ Fallo al conectar con Meta: {e}")
                return None

# 4. LÓGICA DE PROCESAMIENTO
async def procesar_con_ia(texto_usuario: str) -> str:
    """Aquí es donde vive el Agente 10 de Genomma Lab"""
    return f"🤖 *GeommaAI (Agente 10)*\n\nRecibí tu mensaje: _{texto_usuario}_\n\n✅ Procesado correctamente."

# 5. API WEBHOOK (El "Oído" - Recibe mensajes)
app = FastAPI(title="GeommaAI Unificado")
gw = WhatsAppGateway()

@app.get("/")
async def root():
    return {"status": "online", "servicio": "GeommaAI Unificado"}

@app.get("/webhook")
async def verificar_webhook(request: Request):
    """Verificación para el panel de Meta"""
    params = request.query_params
    if (params.get("hub.mode") == "subscribe" and 
        params.get("hub.verify_token") == gw.verify_token):
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(status_code=403)

@app.post("/webhook")
async def recibir_mensaje(request: Request):
    """Recibe el mensaje de WhatsApp y responde usando el Gateway"""
    data = await request.json()
    try:
        # Extraemos la información del JSON de Meta
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "messages" in value:
            mensaje_obj = value["messages"][0]
            numero_usuario = mensaje_obj["from"]
            
            if mensaje_obj.get("type") == "text":
                texto_usuario = mensaje_obj["text"]["body"]
                logger.info(f"📩 Mensaje de {numero_usuario}: {texto_usuario}")

                # 1. Obtenemos respuesta de la IA
                respuesta = await procesar_con_ia(texto_usuario)

                # 2. Usamos el GATEWAY para enviar la respuesta
                await gw.enviar_texto(numero_usuario, respuesta)
                logger.info(f"📤 Respuesta enviada a {numero_usuario}")

        return {"status": "success"}
    except Exception as e:
        logger.error(f"🔥 Error en Webhook: {e}")
        return {"status": "error"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)