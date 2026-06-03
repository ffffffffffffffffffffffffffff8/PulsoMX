import os
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import urllib.parse
import base64
import re
from datetime import datetime

# ⚙️ CONFIGURACIÓN
JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"

# 🔥 CABECERAS Y COOKIES NINJA
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-MX,es;q=0.9',
    'Referer': 'https://www.google.com/',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
COOKIES_GOOGLE = {'CONSENT': 'YES+cb.20210720-07-p0.es+FX+410'}

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

def obtener_url_real_definitiva(google_url):
    try:
        res = requests.get(google_url, headers=HEADERS, cookies=COOKIES_GOOGLE, timeout=10)
        match = re.search(r'window\.location\.replace\("([^"]+)"\)', res.text)
        if match: return match.group(1)
            
        links = BeautifulSoup(res.text, 'html.parser').find_all('a')
        for link in links:
            url = link.get('href', '')
            if url.startswith('http') and 'news.google.com' not in url and 'google.com' not in url:
                return url
    except:
        pass
    return google_url

def obtener_imagen_periodico(url_real):
    try:
        res = requests.get(url_real, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        meta_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if meta_img and meta_img.get("content"):
            return meta_img["content"]
        imgs = soup.find_all("img")
        for img in imgs:
            src = img.get("src", "")
            if src.startswith("http") and len(src) > 50:
                return src
    except:
        pass
    return FALLBACK_IMAGE_URL

def reescribir_con_ia(titulo_orig):
    if not GROQ_API_KEY:
        return titulo_orig, "Noticia importante.", "Revisa el enlace."
    prompt = f"""Eres un periodista mexicano. Titular: {titulo_orig}. Responde ÚNICAMENTE en JSON con claves "titulo", "resumen" y "contenido" (min 300 palabras)."""
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 2000
    }
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=45)
        data = json.loads(r.json()['choices'][0]['message']['content'])
        return data.get("titulo", titulo_orig), data.get("resumen", ""), data.get("contenido", "")
    except:
        return titulo_orig, "Noticia importante.", "Ver enlace."

def ejecutar():
    try:
        res = requests.get(RSS_URL, timeout=10)
        root = ET.fromstring(res.content)
    except: return

    noticias = cargar_noticias()
    for item in root.findall(".//item")[:10]:
        t_orig = item.find("title").text
        if any(n.get('titulo_original') == t_orig for n in noticias): continue
        
        g_url = item.find("link").text
        u_real = obtener_url_real_definitiva(g_url)
        img = obtener_imagen_periodico(u_real)
        t, r, c = reescribir_con_ia(t_orig)
        
        noticias.append({
            "id": max([n.get("id", 0) for n in noticias], default=0) + 1,
            "titulo_original": t_orig,
            "titulo": t, "resumen": r, "contenido": c,
            "imagen": img, "fecha": datetime.today().strftime('%Y-%m-%d'),
            "url_origen": u_real
        })
    guardar_noticias(noticias[-100:])

if __name__ == "__main__":
    ejecutar()
