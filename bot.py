import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.parse
import base64
import re

# ⚙️ CONFIGURACIÓN DEL BOT
# MODO_TURBO: True para procesar muchas noticias a la vez, False para pocas (para no exceder límites).
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 10 if MODO_TURBO else 1
RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Tu API Key de Groq cargada desde las variables de entorno de GitHub
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}

# Imagen de fallback para cuando la original no cargue
FALLBACK_IMAGE_URL = "https://images.unsplash.com/photo-1504711434269-d0385429813a?q=80&w=800&auto=format&fit=crop"

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def decode_google_news_url(google_url):
    """
    Decodifica una URL de redirección de Google News para encontrar la URL final del artículo.
    """
    try:
        prefix_to_remove = "https://news.google.com/rss/articles/"
        if google_url.startswith(prefix_to_remove):
            base64_part = google_url[len(prefix_to_remove):].split('')[0]
            # Añadir padding para decodificación base64
            base64_part += '=' * (-len(base64_part) % 4)
            # Decodificar de base64url a bytes
            url_bytes = base64.urlsafe_b64decode(base64_part)
            
            # Decodificar bytes a utf-8. Algunos caracteres pueden no decodificarse bien, los ignoramos.
            decoded_text = url_bytes.decode('utf-8', errors='ignore')

            # Buscar la URL que empieza por http o https dentro del texto decodificado
            url_match = re.search(r'(https?://[^\s]+)', decoded_text)
            if url_match:
                return url_match.group(1)
                
    except Exception as e:
        print(f"⚠️ Error decodificando URL: {e}")
        
    return google_url

def obtener_url_e_imagen_real_v3(google_url):
    """
    Sigue el rastro de la URL de Google News para encontrar la web real del periódico y su imagen og:image.
    """
    url_real = decode_google_news_url(google_url)
    
    # Si por alguna razón la decodificación matemática falló, intentamos seguir redirecciones normales como plan B
    if "news.google.com" in url_real:
        try:
            # Hacemos una petición limpia para seguir las redirecciones automáticas de Google
            res_redirect = requests.get(google_url, headers=HEADERS, timeout=10, allow_redirects=True)
            url_real = res_redirect.url # Esta es la URL final a la que llegamos
        except Exception as e:
            print(f"⚠️ Error siguiendo redirección normal: {e}")
            
    print(f"🔗 Fuente Real Encontrada: {url_real[:60]}...")
    
    # 3. Ahora que tenemos la URL real, entramos a buscar la imagen oficial
    try:
        # Petición a la web del periódico
        res_articulo = requests.get(url_real, headers=HEADERS, timeout=12)
        if res_articulo.status_code == 200:
            soup = BeautifulSoup(res_articulo.content, 'html.parser')
            
            # Buscar primero og:image, luego twitter:image
            img_tag = soup.find("meta", property="og:image") or soup.find("meta", name="twitter:image")
            
            if img_tag and img_tag.get("content"):
                imagen_real = img_tag["content"]
                
                # Manejar enlaces relativos (ej: /img/foto.jpg -> https://sitio.com/img/foto.jpg)
                if imagen_real.startswith("/"):
                    imagen_real = urllib.parse.urljoin(url_real, imagen_real)
                
                print(f"✅ Imagen real encontrada: {imagen_real[:60]}...")
                return url_real, imagen_real
                
    except Exception as e:
        print(f"⚠️ Error al extraer imagen de la web del periódico: {e}")
        
    return url_real, FALLBACK_IMAGE_URL

def reescribir_con_ia(titulo_orig):
    if not GROQ_API_KEY:
        return titulo_orig, "Noticia importante de México.", "Revisa el enlace original para más detalles."

        prompt = f"""Eres un periodista profesional mexicano. Escribe una noticia basada en este titular: {titulo_orig}.

    Responde ÚNICAMENTE con un JSON con estas claves exactas: "titulo", "resumen", "contenido". 

    El "contenido" debe tener al menos 300 palabras separados por saltos de línea."""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                          headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                          json=payload, timeout=45)
        res = r.json()
        
        if 'choices' in res:
            data = json.loads(res['choices'][0]['message']['content'])
            return data.get("titulo", titulo_orig), data.get("resumen", "Noticia importante."), data.get("contenido", "Detalles en el enlace.")
        else:
            print(f"⚠️ Error IA: No 'choices' en respuesta. Usando datos originales.")
            return titulo_orig, "Noticia disponible en el enlace.", "Revisa el enlace original."

    except Exception as e:
        print(f"⚠️ Error IA: {e}")
        return titulo_orig, "Noticia disponible en el enlace.", "Revisa el enlace original."

def ejecutar():
    try:
        # Scrape del RSS de Google News
        res = requests.get(RSS_URL, timeout=10)
        root = ET.fromstring(res.content)
    except Exception as e:
        print(f"❌ Error RSS: {e}")
        return

    noticias_guardadas = cargar_noticias()
    nuevos = 0

    # Iterar sobre las noticias del RSS
    for item in root.findall(".//item")[:NOTICIAS_POR_CARRERA]:
        t_orig = item.find("title").text
        
        # El RSS da la URL de redirección de Google
        google_url = item.find("link").text if item.find("link") is not None else "#"

        # Evitar duplicados
        if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
            continue

        print(f"🔄 Procesando: {t_orig[:60]}...")
        
        # Reescribir con IA (esto ya te funcionaba)
        t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)
        
        # --- AQUÍ ESTÁ LA MAGIA PARA LA IMAGEN REAL ---
        # Pasamos la URL de Google para obtener la real y su og:image
        url_real, img_url = obtener_url_e_imagen_real_v3(google_url)

        # Crear el objeto de noticia con los datos limpios
        nuevo_id = max([n["id"] for n in noticias_guardadas], default=0) + 1
        noticias_guardadas.append({
            "id": nuevo_id,
            "titulo_original": t_orig,
            "titulo": t_ia,
            "resumen": r_ia,
            "contenido": c_ia,
            "imagen": img_url, # URL real de la imagen directa del periódico
            "fecha": datetime.today().strftime('%Y-%m-%d'),
            "url_origen": url_real # URL directa al periódico
        })
        nuevos += 1
        print(f"✅ Noticia guardada con éxito.")

    if nuevos > 0:
        # Guardar las noticias actualizadas, limitando a 100
        guardar_noticias(noticias_guardadas[-100:])
        print(f"💾 Guardadas {nuevos} noticias nuevas.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
