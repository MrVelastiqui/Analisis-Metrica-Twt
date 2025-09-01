import asyncio
import pandas as pd
from pathlib import Path
import shutil
from playwright.async_api import async_playwright, Response
from datetime import datetime, timezone
from openai import OpenAI
from tqdm.asyncio import tqdm_asyncio
import os

# === CONFIGURACIÓN ===
TXT_LINKS = "Acción-Twitter.txt"
SALIDA_XLSX = "Metricas-Acción.xlsx"
ORIGINAL_PROFILE = Path("/Users/facundovelastiqui/Library/Application Support/Google/Chrome/Default")
COPIA_PERFIL = Path("./chrome_sesion_automatizada")
API_KEY = "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"
MAX_RETRIES = 5

# === OPENAI CLIENT ===
client = OpenAI(api_key=API_KEY)

# === COPIAR PERFIL CHROME SI NO EXISTE ===
if not COPIA_PERFIL.exists():
    shutil.copytree(ORIGINAL_PROFILE, COPIA_PERFIL)

# === FUNCIONES ===
def resumen_conceptual(texto):
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Tu tarea es analizar tweets y generar una única etiqueta temática breve, de hasta 4 palabras, que resuma conceptualmente de qué trata el tweet. No repitas frases literales. No uses puntuación. El objetivo es agrupar tweets similares bajo esta etiqueta. Usá un estilo conciso y homogéneo. Ejemplos: 'gestión municipal Soledad Martínez', 'negociación interna PRO', 'acuerdo electoral Vicente López'"},
                {"role": "user", "content": texto}
            ],
            max_tokens=30,
            temperature=0.4
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Error resumen IA: {e}")
        return ""

async def obtener_metricas(pagina, url):
    metricas = {}

    async def manejar_respuesta(respuesta: Response):
        if "TweetDetail" in respuesta.url and respuesta.status == 200:
            try:
                datos_json = await respuesta.json()
                instrucciones = datos_json['data']['threaded_conversation_with_injections_v2']['instructions']
                for instruccion in instrucciones:
                    for entrada in instruccion.get('entries', []):
                        contenido = entrada.get('content', {})
                        if 'itemContent' in contenido:
                            tweet = contenido['itemContent']['tweet_results']['result']
                            if 'legacy' in tweet:
                                legacy = tweet['legacy']
                                vistas = tweet.get('views', {}).get('count', 'N/A')
                                texto = legacy.get('full_text', '')
                                metricas['url'] = url
                                metricas['usuario'] = url.split('/')[3]
                                metricas['texto'] = texto
                                metricas['likes'] = legacy.get('favorite_count', 0)
                                metricas['retweets'] = legacy.get('retweet_count', 0)
                                metricas['citas'] = legacy.get('quote_count', 0)
                                metricas['comentarios'] = legacy.get('reply_count', 0)
                                metricas['vistas'] = vistas
                                return
            except Exception as e:
                print(f"❌ Error parseando JSON de {url}: {e}")

    pagina.on("response", manejar_respuesta)

    for _ in range(MAX_RETRIES):
        try:
            await pagina.goto(url.replace("x.com", "twitter.com"), wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            if metricas:
                break
        except Exception as e:
            print(f"⚠️ Error cargando {url}: {e}")

    pagina.remove_listener("response", manejar_respuesta)
    return metricas if metricas else None

# === FUNCIÓN PRINCIPAL ===
from tqdm import tqdm  # Asegurate que este import esté

async def principal():
    with open(TXT_LINKS, 'r') as f:
        links = [l.strip() for l in f if l.strip()]

    metricas_finales = []
    fallidos = []

    async with async_playwright() as p:
        contexto = await p.chromium.launch_persistent_context(
            user_data_dir=str(COPIA_PERFIL),
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        pagina = await contexto.new_page()

        for link in tqdm(links, desc="Procesando tweets"):
            print(f"Procesando: {link}")
            try:
                datos = await obtener_metricas(pagina, link)
                if datos:
                    datos["analisis_ia"] = resumen_conceptual(datos.get("texto", ""))
                    metricas_finales.append(datos)
                else:
                    fallidos.append(link)
            except Exception as e:
                print(f"❌ Error procesando {link}: {e}")
                fallidos.append(link)

        await contexto.close()

    if metricas_finales:
        df = pd.DataFrame(metricas_finales)
        df.to_excel(SALIDA_XLSX, index=False)
        print(f"\n✅ Archivo generado: {SALIDA_XLSX}")
    else:
        print("⚠️ No se obtuvieron métricas.")

    if fallidos:
        print("\n❌ Tweets que fallaron:")
        for f in fallidos:
            print(f"- {f}")
        with open("fallidos.txt", "w") as archivo:
            archivo.write("\n".join(fallidos))


# === EJECUTAR ===
if __name__ == "__main__":
    asyncio.run(principal())