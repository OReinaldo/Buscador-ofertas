import os
import json
import re
import unicodedata
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import cloudscraper
from jobspy import scrape_jobs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8,pt;q=0.7",
    "Referer": "https://google.com"
}

# -------------------------------------------------------------------------
# FILTROS Y NORMALIZACIÓN
# -------------------------------------------------------------------------
def normalizar(texto):
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = re.sub(r'[\u0300-\u036f]', '', texto)
    return texto.lower().strip()

def detectar_modalidad(texto):
    texto_lc = normalizar(texto)
    if any(k in texto_lc for k in ["remoto", "teletrabajo", "remote", "100% remoto"]):
        return "Remoto"
    elif any(k in texto_lc for k in ["hibrido", "hybrid", "semi-presencial"]):
        return "Híbrido"
    return "Presencial"

KEYWORDS_DEPORTE = [
    "deport", "desport", "sport", "futbol", "futebol", "soccer", 
    "club", "atlet", "liga", "federac", "stadium", "scout", 
    "coach", "entrenador", "gym", "fitness", "padel", "tenis",
    "celta", "patrocinio", "comercial", "cuentas", "marketing deportivo"
]

LOCATIONS_VIGO = [
    "vigo", "pontevedra", "porriño", "porrino", "redondela", "nigran", "nigrán",
    "moaña", "moana", "cangas", "marin", "marín", "tui", "baiona", "gondomar",
    "salvaterra", "ponteareas", "arcade", "salceda", "bueu", "vilaboa"
]

LOCATIONS_NORTE_PORTUGAL_GALICIA = [
    "galicia", "vigo", "coruña", "coruna", "pontevedra", "ourense", "lugo",
    "ferrol", "santiago", "compostela", "vilagarcia", "vilagarcía", "porriño",
    "porto", "oportu", "braga", "viana", "guimaraes", "guimarães", "famalicao", "famalicão",
    "barcelos", "gaia", "maia", "matosinhos", "trofa", "santo tirso", "vila do conde",
    "povoa", "póvoa", "penafiel", "amarante", "valenca", "valença", "moncao", "monção",
    "norte de portugal", "alto minho", "cávado", "cavado", "ave"
]

EXCLUDE_LOCATIONS = [
    "lisboa", "lisbon", "madrid", "coimbra", "setubal", "setúbal", "algarve", "faro",
    "leiria", "evora", "évora", "beja", "castelo branco", "guarda", "portalegre",
    "santarem", "santarém", "badajoz", "barcelona", "valencia", "sevilla"
]

def es_oferta_deportiva(titulo, empresa=""):
    texto = f"{titulo} {empresa}"
    return any(kw in normalizar(texto) for kw in KEYWORDS_DEPORTE)

def es_ubicacion_valida(ubicacion_raw, categoria):
    loc = normalizar(ubicacion_raw)

    if any(ex in loc for ex in EXCLUDE_LOCATIONS):
        return False

    if categoria == "EMPRESAS":
        if any(v in loc for v in LOCATIONS_VIGO) or "remot" in loc or "teletrabaj" in loc:
            return True
        return False

    elif categoria == "DEPORTE":
        if any(n in loc for n in LOCATIONS_NORTE_PORTUGAL_GALICIA) or "remot" in loc or "internacional" in loc:
            return True
        if "galicia" in loc or "portugal" in loc or "españa" in loc or "espana" in loc:
            return True
        return False

    return True


# =========================================================================
# 1. SCRAPER FUTBOLJOBS (Con Bypass Cloudflare & Rotación URLs)
# =========================================================================
def obtener_ofertas_futboljobs():
    ofertas = []
    print("\n🔍 Scraping FutbolJobs con Cloudscraper...")

    urls_candidatas = [
        "https://futboljobs.com/",
        "https://futboljobs.com/ofertas-de-empleo/",
        "https://futboljobs.com/ofertas/",
        "https://futboljobs.com/empleo/"
    ]

    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

        html_content = None
        for url in urls_candidatas:
            try:
                res = scraper.get(url, timeout=15)
                if res.status_code == 200:
                    html_content = res.text
                    print(f"  └─ Conexión exitosa en {url}")
                    break
            except Exception:
                continue

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Buscar tarjetas de empleo o enlaces con rutas de ofertas
            tarjetas = soup.find_all("li", class_=re.compile(r"(job_listing|job-card|oferta)", re.I))
            if not tarjetas:
                tarjetas = soup.find_all("div", class_=re.compile(r"(job-item|oferta-item|article)", re.I))
            if not tarjetas:
                tarjetas = [a.parent for a in soup.find_all("a", href=re.compile(r"/oferta/|/job/|/empleo/", re.I))]

            vistos = set()
            for elem in tarjetas:
                enlace_tag = elem.find("a", href=True) if elem.name != "a" else elem
                if not enlace_tag or not enlace_tag.has_attr("href"):
                    continue

                href = enlace_tag["href"]
                if not href.startswith("http"):
                    href = "https://futboljobs.com" + href

                titulo = enlace_tag.get_text(strip=True)
                if not titulo or len(titulo) < 5:
                    title_elem = elem.find(["h2", "h3", "h4", "strong"])
                    if title_elem:
                        titulo = title_elem.get_text(strip=True)

                if not titulo or "ver oferta" in titulo.lower() or len(titulo) < 6:
                    continue

                company = "Club / Entidad Deportiva"
                company_elem = elem.find(class_=re.compile(r"(company|empresa|club)", re.I))
                if company_elem:
                    company = company_elem.get_text(strip=True)

                loc = "Galicia / Norte Portugal / Internacional"
                loc_elem = elem.find(class_=re.compile(r"(location|ubicacion|ciudad)", re.I))
                if loc_elem:
                    loc = loc_elem.get_text(strip=True)

                if href not in vistos:
                    vistos.add(href)
                    if es_ubicacion_valida(loc, "DEPORTE"):
                        ofertas.append({
                            "title": titulo[:80],
                            "company": company,
                            "location": loc,
                            "modalidad": detectar_modalidad(f"{titulo} {loc}"),
                            "site": "FutbolJobs",
                            "job_url": href,
                            "categoria": "DEPORTE",
                            "estado": "Pendiente"
                        })
                        
            print(f"  └─ FutbolJobs: {len(ofertas)} ofertas.")
        else:
            print("  └─ No se pudo obtener respuesta HTTP 200 de ninguna URL de FutbolJobs.")

    except Exception as e:
        print(f"  └─ Error en FutbolJobs: {e}")

    return ofertas


# =========================================================================
# 2. SCRAPER NET-EMPREGOS (Portugal)
# =========================================================================
def obtener_ofertas_netempregos():
    ofertas = []
    print("\n🔍 Scraping Net-Empregos (Portugal)...")
    
    busquedas = [
        {"kw": "gestao desportiva", "cat": "DEPORTE"},
        {"kw": "diretor geral", "cat": "EMPRESAS"},
        {"kw": "project manager", "cat": "EMPRESAS"},
        {"kw": "futebol", "cat": "DEPORTE"}
    ]

    distritos_portugal = ["Porto", "Braga", "Viana do Castelo", "Lisboa", "Coimbra", "Leiria", "Aveiro", "Viseu", "Vila Real"]

    for b in busquedas:
        url = f"https://www.net-empregos.com/pesquisa-empregos.asp?chaves={b['kw']}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                items = soup.select('.oferta-link, .job-item, .panel-body, a[href*="oferta-de-emprego"]')
                
                vistos = set()
                for item in items:
                    href = item.get('href', '') if item.name == 'a' else (item.find('a', href=True)['href'] if item.find('a', href=True) else '')
                    if not href:
                        continue
                        
                    if not href.startswith('http'):
                        href = "https://www.net-empregos.com/" + href.lstrip('/')
                    
                    texto_card = item.get_text(separator=' ', strip=True)
                    titulo = item.get_text(strip=True) if item.name == 'a' else (item.find(['h2','h3','a']).get_text(strip=True) if item.find(['h2','h3','a']) else "")
                    
                    loc_detectada = "Portugal"
                    for dist in distritos_portugal:
                        if dist.lower() in texto_card.lower():
                            loc_detectada = f"{dist}, Portugal"
                            break
                    
                    if href not in vistos and len(titulo) > 6:
                        vistos.add(href)
                        
                        if b["cat"] == "DEPORTE" and not es_oferta_deportiva(titulo):
                            continue

                        if not es_ubicacion_valida(loc_detectada, b["cat"]):
                            continue

                        ofertas.append({
                            "title": titulo[:80],
                            "company": "Empresa / Club Portugal",
                            "location": loc_detectada,
                            "modalidad": detectar_modalidad(f"{titulo} {loc_detectada}"),
                            "site": "Net-Empregos",
                            "job_url": href,
                            "categoria": b["cat"],
                            "estado": "Pendiente"
                        })
        except Exception as e:
            print(f"  └─ Error Net-Empregos ({b['kw']}): {e}")

    print(f"  └─ Net-Empregos: {len(ofertas)} ofertas.")
    return ofertas


# =========================================================================
# 3. SCRAPER INFOJOBS (España)
# =========================================================================
def obtener_ofertas_infojobs():
    ofertas = []
    print("\n🔍 Scraping InfoJobs (Vigo / Pontevedra)...")
    
    terminos = [
        {"kw": "director operaciones", "cat": "EMPRESAS"},
        {"kw": "project manager", "cat": "EMPRESAS"},
        {"kw": "ejecutivo de cuentas", "cat": "EMPRESAS"},
        {"kw": "director deportivo", "cat": "DEPORTE"},
        {"kw": "celta", "cat": "DEPORTE"}
    ]

    for t in terminos:
        url = f"https://www.infojobs.net/ofertas-trabajo/pontevedra?q={t['kw'].replace(' ', '+')}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                links = soup.select('a[href*="/of-i"]')
                
                vistos = set()
                for a in links:
                    href = a.get('href', '')
                    if not href.startswith('http'):
                        href = "https:" + href if href.startswith('//') else "https://www.infojobs.net" + href
                    
                    titulo = a.get_text(strip=True)
                    loc = "Vigo / Pontevedra, España"
                    
                    if href not in vistos and len(titulo) > 8:
                        vistos.add(href)
                        
                        if t["cat"] == "DEPORTE" and not es_oferta_deportiva(titulo):
                            continue

                        if not es_ubicacion_valida(loc, t["cat"]):
                            continue

                        ofertas.append({
                            "title": titulo[:80],
                            "company": "Empresa InfoJobs",
                            "location": loc,
                            "modalidad": detectar_modalidad(f"{titulo} {loc}"),
                            "site": "InfoJobs",
                            "job_url": href,
                            "categoria": t["cat"],
                            "estado": "Pendiente"
                        })
        except Exception as e:
            print(f"  └─ Error InfoJobs ({t['kw']}): {e}")

    print(f"  └─ InfoJobs: {len(ofertas)} ofertas.")
    return ofertas


# =========================================================================
# 4. JOBSPY (LinkedIn, Indeed, Google Jobs)
# =========================================================================
def obtener_ofertas_jobspy():
    ofertas = []
    
    consultas = [
        # --- EMPRESAS (Vigo y radio) ---
        {"term": "Director de Operaciones", "location": "Vigo", "distance": 30, "category": "EMPRESAS", "country": "spain"},
        {"term": "Project Manager", "location": "Vigo", "distance": 30, "category": "EMPRESAS", "country": "spain"},
        {"term": "Director Industrial", "location": "Vigo", "distance": 30, "category": "EMPRESAS", "country": "spain"},
        {"term": "Ejecutivo de Cuentas", "location": "Vigo", "distance": 30, "category": "EMPRESAS", "country": "spain"},
        {"term": "PMO", "location": "Vigo", "distance": 30, "category": "EMPRESAS", "country": "spain"},

        # --- DEPORTE (Galicia + Norte de Portugal) ---
        {"term": "RC Celta", "location": "Vigo", "distance": 30, "category": "DEPORTE", "country": "spain"},
        {"term": "Celta", "location": "Vigo", "distance": 30, "category": "DEPORTE", "country": "spain"},
        {"term": "Director Deportivo", "location": "Galicia", "distance": 50, "category": "DEPORTE", "country": "spain"},
        {"term": "Marketing Deportivo", "location": "Galicia", "distance": 50, "category": "DEPORTE", "country": "spain"},
        {"term": "Gestao Desportiva", "location": "Porto", "distance": 50, "category": "DEPORTE", "country": "portugal"},
        {"term": "Futebol", "location": "Porto", "distance": 50, "category": "DEPORTE", "country": "portugal"},
        {"term": "Sports Management", "location": "Porto", "distance": 50, "category": "DEPORTE", "country": "portugal"}
    ]

    for c in consultas:
        print(f"\n🔍 Buscando '{c['term']}' en {c['location']} (LinkedIn, Indeed, Google)...")
        try:
            jobs = scrape_jobs(
                site_name=["linkedin", "indeed", "google"],
                search_term=c["term"],
                location=c["location"],
                distance=c["distance"],
                results_wanted=15,
                hours_old=168,
                country_indeed=c["country"]
            )

            if not jobs.empty:
                count_aceptadas = 0
                for _, row in jobs.iterrows():
                    titulo = str(row.get('title', ''))
                    empresa = str(row.get('company', ''))
                    loc_raw = str(row.get('location', ''))
                    cat_original = c["category"]

                    if cat_original == "DEPORTE" and not es_oferta_deportiva(titulo, empresa):
                        continue

                    if not es_ubicacion_valida(loc_raw, cat_original):
                        continue

                    ofertas.append({
                        "title": titulo,
                        "company": empresa,
                        "location": loc_raw,
                        "modalidad": detectar_modalidad(f"{titulo} {loc_raw}"),
                        "site": str(row.get('site', '')),
                        "job_url": str(row.get('job_url', '#')),
                        "categoria": cat_original,
                        "estado": "Pendiente"
                    })
                    count_aceptadas += 1
                print(f"  └─ Coincidencias válidas: {count_aceptadas}")
        except Exception as e:
            print(f"  └─ Error JobSpy '{c['term']}': {e}")

    return ofertas


# =========================================================================
# CONTROLADOR PRINCIPAL
# =========================================================================
def obtener_ofertas():
    ahora = datetime.now()
    fecha_hoy = ahora.strftime("%d/%m/%Y")
    fecha_hora_actualizacion = ahora.strftime("%d/%m/%Y %H:%M")

    # 1. Recopilar vacantes de todos los scrapers
    ofertas_js = obtener_ofertas_jobspy()
    ofertas_fj = obtener_ofertas_futboljobs()
    ofertas_ne = obtener_ofertas_netempregos()
    ofertas_ij = obtener_ofertas_infojobs()
    
    todas = ofertas_js + ofertas_fj + ofertas_ne + ofertas_ij

    # 2. Desduplicar por URL
    uniques = {}
    for item in todas:
        url = item.get("job_url", "#")
        if url != "#" and url not in uniques:
            uniques[url] = item

    ofertas_filtradas = list(uniques.values())

    # 3. Cargar historial anterior para mantener estados y fecha de primera detección
    estados_previos = {}
    fechas_previas = {}

    if os.path.exists("ofertas.json"):
        try:
            with open("ofertas.json", "r", encoding="utf-8") as f:
                datos_cargados = json.load(f)
                
                # Soportar si el JSON anterior era un array simple o el nuevo objeto estructurado
                if isinstance(datos_cargados, dict):
                    existentes = datos_cargados.get("ofertas", [])
                else:
                    existentes = datos_cargados

                for i in existentes:
                    if "job_url" in i:
                        estados_previos[i["job_url"]] = i.get("estado", "Pendiente")
                        if "fecha" in i:
                            fechas_previas[i["job_url"]] = i["fecha"]
        except Exception as e:
            print(f"⚠️ No se cargaron datos previos: {e}")

    # 4. Asignar estado y fecha fija de primera extracción a cada oferta
    for item in ofertas_filtradas:
        url = item["job_url"]
        
        # Mantener o asignar estado
        if url in estados_previos:
            item["estado"] = estados_previos[url]

        # Mantener fecha previa si existía; si es nueva oferta, asignar la fecha de hoy
        if url in fechas_previas and fechas_previas[url]:
            item["fecha"] = fechas_previas[url]
        else:
            item["fecha"] = fecha_hoy

    # 5. Guardar la estructura completa en ofertas.json
    estructura_final = {
        "ultima_actualizacion": fecha_hora_actualizacion,
        "total_ofertas": len(ofertas_filtradas),
        "ofertas": ofertas_filtradas
    }

    with open("ofertas.json", "w", encoding="utf-8") as f:
        json.dump(estructura_final, f, ensure_ascii=False, indent=4)

    print(f"\n✅ PROCESO FINALIZADO: {len(ofertas_filtradas)} vacantes guardadas en ofertas.json a las {fecha_hora_actualizacion}.")

if __name__ == "__main__":
    obtener_ofertas()
