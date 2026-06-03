import os
import json
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime
from urllib.parse import quote

# ⚙️ CONFIGURACIÓN
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 10 if MODO_TURBO else 1
RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def extraer_imagen_noticia(url):
    """Extrae la imagen og:image de la noticia original."""
    if not url or url == '#':
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None

        # Buscar og:image
        og_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\'](https?://[^"\']+)["\']', r.text)
        if og_match:
            return og_match.group(1)

        # Buscar twitter:image como fallback
        tw_match = re.search(r'<meta[^>]*name=["\']twitter:image["\'][^>]*content=["\'](https?://[^"\']+)["\']', r.text)
        if tw_match:
            return tw_match.group(1)

        # Buscar cualquier img grande como último recurso
        img_match = re.search(r'<img[^>]*src=["\'](https?://[^"\']+\.(jpg|jpeg|png|webp))["\']', r.text)
        if img_match:
            return img_match.group(1)

    except Exception as e:
        print(f"⚠️ No se pudo extraer imagen de {url[:50]}: {e}")
    return None

def generar_imagen_fallback(titulo):
    """Imagen de respaldo si no se puede extraer la original."""
    seed = abs(hash(titulo)) % 9999
    return f"https://picsum.photos/seed/{seed}/800/500"

def generar_imagen_relevante(titulo, url_origen=None):
    """Intenta extraer imagen real de la noticia, con fallback a Picsum."""
    if url_origen and url_origen != '#':
        img = extraer_imagen_noticia(url_origen)
        if img:
            print(f"🖼️ Imagen extraída: {img[:60]}...")
            return img
    print(f"🖼️ Usando imagen de respaldo para: {titulo[:40]}")
    return generar_imagen_fallback(titulo)

def reescribir_con_ia(titulo_orig):
    if not GROQ_API_KEY:
        return titulo_orig, "Noticia reciente.", "Detalles en el enlace original."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Eres un periodista profesional mexicano. A partir del siguiente titular de noticia, genera un artículo periodístico completo en español.

TITULAR: {titulo_orig}

Instrucciones OBLIGATORIAS:
- El "titulo" debe ser atractivo, claro y en español, máximo 90 caracteres.
- El "resumen" debe ser un párrafo de 3-4 oraciones que explique el contexto general de la noticia, quiénes son los involucrados y por qué es importante. Mínimo 80 palabras.
- El "contenido" debe ser un artículo periodístico completo de MÍNIMO 500 palabras con:
  * Párrafo de introducción que responda: ¿qué pasó?, ¿quién?, ¿cuándo?, ¿dónde?
  * Al menos 4 párrafos de desarrollo con contexto, antecedentes, detalles relevantes e impacto
  * Citas o declaraciones probables de los involucrados (puedes inferirlas de forma periodística)
  * Párrafo de cierre con perspectivas o lo que se espera a futuro
  * Usa párrafos separados por saltos de línea (\n\n)
  * Escribe en tono periodístico formal pero accesible para el público mexicano general

Responde ÚNICAMENTE con un JSON válido con estas tres claves exactas: "titulo", "resumen", "contenido". Sin texto extra, sin markdown, sin explicaciones."""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=45)
        res = r.json()
        contenido_crudo = res['choices'][0]['message']['content']
        data = json.loads(contenido_crudo)

        titulo = data.get("titulo", titulo_orig)[:120]
        resumen = data.get("resumen", "Noticia importante de México.")
        contenido = data.get("contenido", "Revisa el enlace original para más detalles.")

        # Verificar que el contenido tenga suficiente texto
        if len(contenido.split()) < 200:
            contenido += "\n\n" + resumen

        return titulo, resumen, contenido

    except Exception as e:
        print(f"⚠️ Error IA: {e}")
        return titulo_orig, "Noticia importante de México.", "Revisa el enlace original para más detalles."

def ejecutar():
    try:
        res = requests.get(RSS_URL, timeout=10)
        root = ET.fromstring(res.content)
    except Exception as e:
        print(f"❌ Error RSS: {e}")
        return

    noticias_guardadas = cargar_noticias()
    nuevos = 0

    for item in root.findall(".//item")[:NOTICIAS_POR_CARRERA]:
        t_orig = item.find("title").text
        link = item.find("link").text if item.find("link") is not None else "#"

        if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
            continue

        print(f"🔄 Procesando: {t_orig[:60]}...")
        t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)

        img_url = generar_imagen_relevante(t_ia, url_origen=link)

        nuevo_id = max([n["id"] for n in noticias_guardadas], default=0) + 1
        noticias_guardadas.append({
            "id": nuevo_id,
            "titulo_original": t_orig,
            "titulo": t_ia,
            "resumen": r_ia,
            "contenido": c_ia,
            "imagen": img_url,
            "fecha": datetime.today().strftime('%Y-%m-%d'),
            "url_origen": link
        })
        nuevos += 1
        print(f"✅ Guardada: {t_ia[:50]} ({len(c_ia.split())} palabras)")

    if nuevos > 0:
        # Mantener solo las últimas 100 noticias para no crecer infinito
        if len(noticias_guardadas) > 100:
            noticias_guardadas = noticias_guardadas[-100:]
        guardar_noticias(noticias_guardadas)
        print(f"💾 Guardadas {nuevos} noticias nuevas.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
