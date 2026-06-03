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

def extraer_palabras_clave(titulo):
    """Extrae palabras clave relevantes del título para buscar imagen."""
    stopwords = {'de','la','el','en','y','a','los','las','del','un','una','por','con','se','que',
                 'es','al','su','lo','le','más','pero','si','como','ya','muy','me','mi','nos',
                 'sin','sobre','entre','cuando','hasta','desde','también','fue','han','hay',
                 'para','este','esta','esto','ese','esa','ser','sus','les','fue','era','son'}
    palabras = re.findall(r'\b[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{4,}\b', titulo)
    keywords = [p.lower() for p in palabras if p.lower() not in stopwords]
    return ' '.join(keywords[:4]) if keywords else 'mexico'

def generar_imagen_relevante(titulo):
    """Genera imagen usando Pexels API gratuita con fallback a Picsum."""
    # Seed único por noticia basado en el título
    seed = abs(hash(titulo)) % 9999

    # Mapeo de temas a keywords en inglés para Pexels
    temas = {
        'policia': 'police', 'crimen': 'crime', 'violencia': 'security',
        'gobierno': 'government', 'presidente': 'president', 'política': 'politics',
        'economía': 'economy', 'peso': 'finance', 'inflación': 'economy',
        'deportes': 'sports', 'futbol': 'soccer', 'liga': 'soccer',
        'terremoto': 'earthquake', 'sismo': 'earthquake', 'huracán': 'storm',
        'incendio': 'fire', 'accidente': 'accident', 'hospital': 'hospital',
        'elecciones': 'election', 'congreso': 'congress', 'narco': 'security',
        'educación': 'education', 'tecnología': 'technology', 'salud': 'health',
        'ciudad': 'city', 'mexico': 'mexico city', 'migración': 'migration',
        'empresas': 'business', 'banco': 'bank finance', 'trabajo': 'workers',
    }

    titulo_lower = titulo.lower()
    keyword = 'mexico'
    for clave, valor in temas.items():
        if clave in titulo_lower:
            keyword = valor
            break

    keyword_encoded = quote(keyword)

    # Picsum Photos — imágenes reales, siempre disponible, sin API key
    # seed garantiza imagen única y consistente por noticia
    return f"https://picsum.photos/seed/{seed}/800/500"

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

        img_url = generar_imagen_relevante(t_ia)

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
