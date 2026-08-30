import os
import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import cloudscraper
import pandas as pd
from jobspy import scrape_jobs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8,pt;q=0.7",
    "Referer": "https://google.com"
}

# -------------------------------------------------------------------------
# FUNCIONES DE NORMALIZACIÓN Y LIMPIEZA
# -------------------------------------------------------------------------
def normalizar(texto):
    if not texto or pd.isna(texto):
        return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = re.sub(r'[\u0300-\u036f]', '', texto)
    return texto.lower().strip()

def clean_val(val, default=""):
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    return default if s.lower() == "nan" or not s else s

def detectar_modalidad(texto_combinado, is_remote_flag=None):
    """
    Detecta de forma precisa si la oferta es Remoto, Híbrido o Presencial.
    Analiza la bandera de la API, el título, la descripción y etiquetas de LinkedIn/Indeed.
    """
    # 1. Flag explícito devuelto por APIs como JobSpy / LinkedIn / Indeed
    if is_remote_flag is True or str(is_remote_flag).strip().lower() in ['true', '1']:
        return "Remoto"

    texto_lc = normalizar(texto_combinado)

    # 2. Patrones de Híbrido (se evalúan antes para evitar falsos 100% remoto)
    patrones_hibrido = r'\b(hibrid[oa]s?|hybrid|semi[- ]?presencial|semipresencial|trabalho hibrido|modelo hibrido|flexible work|flexiwork|misto|hybrid work|presencial / remoto|remoto / presencial)\b'
    if re.search(patrones_hibrido, texto_lc):
        return "Híbrido"

    # 3. Patrones de Remoto (incluye expresiones frecuentes de LinkedIn en español e inglés)
    patrones_remoto = r'\b(en remoto|remot[oa]s?|remote|teletrabaj[oa]s?|teletrabalh[oa]s?|work from home|wfh|home office|100% remoto|100% remote|full remote|fully remote|a distancia|trabalho a distancia|remotamente)\b'
    if re.search(patrones_remoto, texto_lc):
        return "Remoto"

    # 4. Fallback por defecto
    return "Presencial"

def detectar_tipo_jornada(texto_combinado, job_type_raw=""):
    """
    Detecta la modalidad de contrato/jornada (Jornada Completa, Media Jornada, Prácticas, Freelance).
    """
    texto_lc = normalizar(f"{texto_combinado} {job_type_raw}")

    if re.search(r'\b(practicas|beca|becario|estagio|estagiario|internship|intern|trainee)\b', texto_lc):
        return "Prácticas / Beca"
    if re.search(r'\b(media jornada|part[- ]time|meio tempo|jornada parcial|parcial)\b', texto_lc):
        return "Media Jornada"
    if re.search(r'\b(freelance|autonomo|contractor|por proyecto|project-based|prestacao de servicos)\b', texto_lc):
        return "Proyecto / Freelance"
    if re.search(r'\b(jornada completa|full[- ]time|fulltime|tempo inteiro|completa|tiempo completo|indefinido)\b', texto_lc):
        return "Jornada Completa"

    # Validación adicional sobre el tipo nativo de JobSpy
    jt = normalizar(job_type_raw)
    if "fulltime" in jt or "full_time" in jt:
        return "Jornada Completa"
    elif "parttime" in jt or "part_time" in jt:
        return "Media Jornada"
    elif "internship" in jt:
        return "Prácticas / Beca"
    elif "contract" in jt:
        return "Proyecto / Freelance"

    return "Jornada Completa"


# -------------------------------------------------------------------------
# PALABRAS CLAVE Y FILTROS EXPANDIDOS (CV ALINEADO)
# -------------------------------------------------------------------------

KEYWORDS_DEPORTE = [
    # Operaciones y Gestión de Clubes (Club & Football Operations)
    "football operations", "sports operations", "sporting operations", "club operations",
    "academy operations", "performance operations", "commercial operations", "operations director",
    "football project manager", "club management", "general manager", "managing director",
    
    # Estrategia, Transformación e Innovación Deportiva
    "strategy", "estrategia", "transformation", "transformacion", "innovation", "innovacion",
    "digital transformation", "transformacion digital",
    
    # Negocio Deportivo y Dirección General
    "football business", "sports business", "gestao desportiva", "gestion deportiva",
    "direccion deportiva", "diretor desportivo", "sports director", "deport", "desport", "sport",
    "futbol", "futebol", "soccer", "club", "liga", "federac", "stadium", "control economico",
    
    # Rendimiento, Cantera, Scouting y Análisis Técnico
    "cantera", "academia", "metodologia", "scout", "scouting", "analyst", "analista",
    "tactico", "tactica", "data analyst", "performance", "rendimiento", "football data",
    "coach", "entrenador", "treinador", "cuerpo tecnico", "preparador",
    
    # Comercial, Patrocinio y Clubes Objetivo
    "patrocinio", "sponsorship", "marketing deportivo", "celta", "boavista"
]

KEYWORDS_EMPRESA = [
    # Operaciones, Planta y Dirección Industrial
    "director de operaciones", "director operaciones", "operations manager", 
    "business operations manager", "business operations", "director industrial", 
    "plant manager", "director de planta", "jefe de planta", "gerente de operaciones", 
    "head of operations", "coo", "operaciones", "operations", "technical services", "director, technical",

    # Transformación, Innovación y Estrategia
    "director de transformacion", "transformation manager", "director transformacion",
    "innovation manager", "director de innovacion", "strategy manager", 
    "director de estrategia", "estrategia", "strategy", "innovacion", "innovation",
    "transformacion", "transformation", "digital transformation", "transformacion digital",

    # PMO, Proyectos y Desarrollo de Negocio
    "pmo director", "pmo manager", "pmo", "director de proyectos", 
    "director proyectos", "project director", "project manager", "project management",
    "gestion de proyectos", "business development", "desarrollo de negocio",

    # Excelencia Operativa, Control Económico y Calidad
    "continuous improvement manager", "continuous improvement", "mejora continua",
    "operational excellence", "excelencia operativa", "lean manufacturing", "lean six sigma",
    "control economico", "control de gestion", "controlling", "supply chain", 
    "director de procesos", "quality manager", "director de calidad"
]

LOCATIONS_VIGO = [
    "vigo", "pontevedra", "porrino", "o porrino", "redondela", "nigran",
    "moana", "cangas", "marin", "tui", "baiona", "gondomar",
    "salvaterra", "ponteareas", "arcade", "salceda", "bueu", "vilaboa"
]

LOCATIONS_NORTE_PORTUGAL_GALICIA = [
    "galicia", "vigo", "coruna", "pontevedra", "ourense", "lugo",
    "ferrol", "santiago", "compostela", "vilagarc", "porrino",
    "porto", "oportu", "braga", "viana", "guimaraes", "famalicao",
    "barcelos", "gaia", "maia", "matosinhos", "trofa", "santo tirso", 
    "vila do conde", "povoa", "penafiel", "amarante", "valenca", "moncao",
    "norte de portugal", "alto minho", "cavado", "ave"
]

EXCLUDE_LOCATIONS = [
    "lisboa", "lisbon", "madrid", "coimbra", "setubal", "algarve", "faro",
    "leiria", "evora", "beja", "castelo branco", "guarda", "portalegre",
    "santarem", "badajoz", "barcelona", "valencia", "sevilla"
]

def es_oferta_deportiva(titulo, empresa=""):
    texto = normalizar(f"{titulo} {empresa}")
    return any(kw in texto for kw in KEYWORDS_DEPORTE)

def es_oferta_empresa_relevante(titulo, empresa=""):
    texto = normalizar(f"{titulo} {empresa}")
    return any(kw in texto for kw in KEYWORDS_EMPRESA)

def es_ubicacion_valida(ubicacion_raw, categoria):
    loc = normalizar(ubicacion_raw)

    if any(ex in loc for ex in EXCLUDE_LOCATIONS):
        return False

    if categoria == "EMPRESAS":
        if any(v in loc for v in LOCATIONS_VIGO) or "remot" in loc or "teletrabaj" in loc or "home office" in loc:
            return True
        return False

    elif categoria == "DEPORTE":
        if any(n in loc for n in LOCATIONS_NORTE_PORTUGAL_GALICIA) or "remot" in loc or "internacional" in loc:
            return True
        if "galicia" in loc or "portugal" in loc or "espana" in loc:
            return True
        return False

    return True


# =========================================================================
# 1. SCRAPER FUTBOLJOBS
# =========================================================================
def obtener_ofertas_futboljobs():
    ofertas = []
    print("\n🔍 Scraping FutbolJobs...")

    urls_candidatas = [
        "https://futboljobs.com/ofertas-de-empleo/",
        "https://futboljobs.com/ofertas/",
        "https://futboljobs.com/"
    ]

    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )

        html_content = None
        for url in urls_candidatas:
            try:
                res = scraper.get(url, timeout=15)
                if res.status_code == 200 and len(res.text) > 1000:
                    html_content = res.text
                    print(f"  └─ Conexión exitosa en {url}")
                    break
            except Exception:
                continue

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            tarjetas = soup.find_all("li", class_=re.compile(r"(job_listing|job-card|oferta)", re.I))
            if not tarjetas:
                tarjetas = soup.find_all("div", class_=re.compile(r"(job-item|oferta-item|article)", re.I))
            if not tarjetas:
                tarjetas = [a.parent for a in soup.find_all("a", href=re.compile(r"/oferta/|/job/|/empleo/", re.I))]

            vistos = set()
            for elem in tarjetas:
                enlace_tag = elem if elem.name == "a" else elem.find("a", href=True)
                if not enlace_tag or not enlace_tag.has_attr("href"):
                    continue

                href = urljoin("https://futboljobs.com", enlace_tag["href"])
                titulo = enlace_tag.get_text(strip=True)
                
                if not titulo or len(titulo) < 5:
                    title_elem = elem.find(["h2", "h3", "h4", "strong"])
                    if title_elem:
                        titulo = title_elem.get_text(strip=True)

                if not titulo or "ver oferta" in titulo.lower() or len(titulo) < 6:
                    continue

                company_elem = elem.find(class_=re.compile(r"(company|empresa|club)", re.I))
                company = company_elem.get_text(strip=True) if company_elem else "Club / Entidad Deportiva"

                loc_elem = elem.find(class_=re.compile(r"(location|ubicacion|ciudad)", re.I))
                loc = loc_elem.get_text(strip=True) if loc_elem else "Galicia / Norte Portugal / Internacional"

                if href not in vistos:
                    vistos.add(href)
                    if es_ubicacion_valida(loc, "DEPORTE"):
                        mod = detectar_modalidad(f"{titulo} {loc}")
                        jornada = detectar_tipo_jornada(f"{titulo} {loc}")
                        ofertas.append({
                            "title": titulo[:100],
                            "company": company,
                            "location": loc,
                            "modalidad": mod,
                            "tipo_jornada": jornada,
                            "tipo_contrato": jornada,
                            "site": "FutbolJobs",
                            "job_url": href,
                            "categoria": "DEPORTE",
                            "estado": "Pendiente"
                        })
            print(f"  └─ FutbolJobs: {len(ofertas)} ofertas.")
        else:
            print("  └─ Sin respuesta válida en FutbolJobs.")

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
        {"kw": "diretor desportivo", "cat": "DEPORTE"},
        {"kw": "futebol", "cat": "DEPORTE"},
        {"kw": "diretor geral", "cat": "EMPRESAS"},
        {"kw": "director de operacoes", "cat": "EMPRESAS"},
        {"kw": "project manager", "cat": "EMPRESAS"}
    ]

    distritos_norte = ["Porto", "Braga", "Viana do Castelo", "Vila Real", "Bragança"]

    for b in busquedas:
        url = f"https://www.net-empregos.com/pesquisa-empregos.asp?chaves={b['kw']}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                items = soup.select('.oferta-link, .job-item, .panel-body, a[href*="oferta-de-emprego"]')
                
                vistos = set()
                for item in items:
                    href_raw = item.get('href', '') if item.name == 'a' else (item.find('a', href=True)['href'] if item.find('a', href=True) else '')
                    if not href_raw:
                        continue
                        
                    href = urljoin("https://www.net-empregos.com/", href_raw)
                    texto_card = item.get_text(separator=' ', strip=True)
                    titulo = item.get_text(strip=True) if item.name == 'a' else (item.find(['h2','h3','a']).get_text(strip=True) if item.find(['h2','h3','a']) else "")
                    
                    loc_detectada = "Portugal"
                    for dist in distritos_norte:
                        if dist.lower() in texto_card.lower():
                            loc_detectada = f"{dist}, Portugal"
                            break
                    
                    if href not in vistos and len(titulo) > 6:
                        vistos.add(href)
                        if b["cat"] == "DEPORTE" and not es_oferta_deportiva(titulo):
                            continue
                        if b["cat"] == "EMPRESAS" and not es_oferta_empresa_relevante(titulo):
                            continue
                        if not es_ubicacion_valida(loc_detectada, b["cat"]):
                            continue

                        texto_completo = f"{titulo} {texto_card} {loc_detectada}"
                        mod = detectar_modalidad(texto_completo)
                        jornada = detectar_tipo_jornada(texto_completo)
                        ofertas.append({
                            "title": titulo[:100],
                            "company": "Empresa / Club Portugal",
                            "location": loc_detectada,
                            "modalidad": mod,
                            "tipo_jornada": jornada,
                            "tipo_contrato": jornada,
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
# 3. SCRAPER INFOJOBS (Pontevedra / Vigo)
# =========================================================================
def obtener_ofertas_infojobs():
    ofertas = []
    print("\n🔍 Scraping InfoJobs (Pontevedra/Vigo)...")
    
    terminos = [
        {"kw": "director operaciones", "cat": "EMPRESAS"},
        {"kw": "plant manager", "cat": "EMPRESAS"},
        {"kw": "pmo", "cat": "EMPRESAS"},
        {"kw": "project manager", "cat": "EMPRESAS"},
        {"kw": "mejora continua", "cat": "EMPRESAS"},
        {"kw": "director transformacion", "cat": "EMPRESAS"},
        {"kw": "director deportivo", "cat": "DEPORTE"},
        {"kw": "analista tactico", "cat": "DEPORTE"},
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
                    href = urljoin("https://www.infojobs.net", a.get('href', ''))
                    titulo = a.get_text(strip=True)
                    loc = "Vigo / Pontevedra, España"
                    
                    if href not in vistos and len(titulo) > 8:
                        vistos.add(href)
                        if t["cat"] == "DEPORTE" and not es_oferta_deportiva(titulo):
                            continue
                        if t["cat"] == "EMPRESAS" and not es_oferta_empresa_relevante(titulo):
                            continue
                        if not es_ubicacion_valida(loc, t["cat"]):
                            continue

                        mod = detectar_modalidad(f"{titulo} {loc}")
                        jornada = detectar_tipo_jornada(f"{titulo} {loc}")
                        ofertas.append({
                            "title": titulo[:100],
                            "company": "Empresa InfoJobs",
                            "location": loc,
                            "modalidad": mod,
                            "tipo_jornada": jornada,
                            "tipo_contrato": jornada,
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
        # --- EJE EMPRESA / OPERACIONES / PMO / TRANSFORMACIÓN (Área Vigo) ---
        {"term": "Director de Operaciones", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Operations Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Senior Director Technical Services", "location": "Pontevedra", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Director Industrial", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Plant Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Business Operations Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Director de Transformacion", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Transformation Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Innovation Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Continuous Improvement Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Operational Excellence", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "PMO Director", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "PMO Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Strategy Manager", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Business Development", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},
        {"term": "Director de Proyectos", "location": "Vigo", "distance": 35, "category": "EMPRESAS", "country": "spain"},

        # --- EJE DEPORTE / OPERACIONES / CLUBES / DIRECCIÓN TÉCNICA (Galicia + Norte Portugal) ---
        {"term": "Football Operations", "location": "Galicia", "distance": 100, "category": "DEPORTE", "country": "spain"},
        {"term": "Sports Operations", "location": "Galicia", "distance": 100, "category": "DEPORTE", "country": "spain"},
        {"term": "Club Management", "location": "Galicia", "distance": 100, "category": "DEPORTE", "country": "spain"},
        {"term": "Football Project Manager", "location": "Galicia", "distance": 100, "category": "DEPORTE", "country": "spain"},
        {"term": "General Manager Sports", "location": "Galicia", "distance": 100, "category": "DEPORTE", "country": "spain"},
        {"term": "Sports Business", "location": "Porto", "distance": 80, "category": "DEPORTE", "country": "portugal"},
        {"term": "Diretor Desportivo", "location": "Porto", "distance": 80, "category": "DEPORTE", "country": "portugal"},
        {"term": "Gestao Desportiva", "location": "Porto", "distance": 80, "category": "DEPORTE", "country": "portugal"},
        {"term": "Director Deportivo", "location": "Galicia", "distance": 50, "category": "DEPORTE", "country": "spain"},
        {"term": "RC Celta", "location": "Vigo", "distance": 30, "category": "DEPORTE", "country": "spain"}
    ]

    for c in consultas:
        print(f"\n🔍 Buscando '{c['term']}' en {c['location']} vía JobSpy...")
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

            if jobs is not None and not jobs.empty:
                count_aceptadas = 0
                for _, row in jobs.iterrows():
                    titulo = clean_val(row.get('title'))
                    empresa = clean_val(row.get('company'), "Empresa Desconocida")
                    loc_raw = clean_val(row.get('location'), c['location'])
                    job_url = clean_val(row.get('job_url'), "#")
                    site = clean_val(row.get('site'), "JobSpy")
                    is_remote_flag = row.get('is_remote') if 'is_remote' in row else None
                    description = clean_val(row.get('description'))
                    job_type_raw = clean_val(row.get('job_type'))
                    cat_original = c["category"]

                    if not titulo or job_url == "#":
                        continue

                    # Validación estricta de afinidad
                    if cat_original == "DEPORTE" and not es_oferta_deportiva(titulo, empresa):
                        continue
                    if cat_original == "EMPRESAS" and not es_oferta_empresa_relevante(titulo, empresa):
                        continue
                    if not es_ubicacion_valida(loc_raw, cat_original):
                        continue

                    # Detección enriquecida con descripción y tipo de trabajo nativo
                    texto_eval = f"{titulo} {loc_raw} {job_type_raw} {description[:1500]} {site}"
                    mod = detectar_modalidad(texto_eval, is_remote_flag=is_remote_flag)
                    jornada = detectar_tipo_jornada(texto_eval, job_type_raw=job_type_raw)

                    ofertas.append({
                        "title": titulo,
                        "company": empresa,
                        "location": loc_raw,
                        "modalidad": mod,
                        "tipo_jornada": jornada,
                        "tipo_contrato": jornada,
                        "site": site,
                        "job_url": job_url,
                        "categoria": cat_original,
                        "estado": "Pendiente"
                    })
                    count_aceptadas += 1
                print(f"  └─ Coincidencias válidas: {count_aceptadas}")
        except Exception as e:
            print(f"  └─ Error JobSpy '{c['term']}': {e}")

    return ofertas


# =========================================================================
# CONTROLADOR PRINCIPAL Y MERGE HISTÓRICO
# =========================================================================
def obtener_ofertas():
    ahora = datetime.now()
    fecha_hoy = ahora.strftime("%d/%m/%Y")
    fecha_hora_actualizacion = ahora.strftime("%d/%m/%Y %H:%M")

    # 1. Cargar historial existente para no perder estados previos ni fechas
    db_existente = {}
    if os.path.exists("ofertas.json"):
        try:
            with open("ofertas.json", "r", encoding="utf-8") as f:
                datos_cargados = json.load(f)
                existentes = datos_cargados.get("ofertas", []) if isinstance(datos_cargados, dict) else datos_cargados
                for item in existentes:
                    if "job_url" in item:
                        db_existente[item["job_url"]] = item
        except Exception as e:
            print(f"⚠️ Error al leer ofertas.json previo: {e}")

    # 2. Recopilar vacantes de todas las fuentes
    ofertas_js = obtener_ofertas_jobspy()
    ofertas_fj = obtener_ofertas_futboljobs()
    ofertas_ne = obtener_ofertas_netempregos()
    ofertas_ij = obtener_ofertas_infojobs()
    
    nuevas_ofertas = ofertas_js + ofertas_fj + ofertas_ne + ofertas_ij

    # 3. Fusionar datos actualizando modalidad/contrato y conservando estados previos
    n_nuevas = 0
    for item in nuevas_ofertas:
        url = item["job_url"]
        if url in db_existente:
            item["estado"] = db_existente[url].get("estado", "Pendiente")
            item["fecha"] = db_existente[url].get("fecha", fecha_hoy)
            db_existente[url].update(item)
        else:
            item["fecha"] = fecha_hoy
            db_existente[url] = item
            n_nuevas += 1

    lista_final = list(db_existente.values())

    # 4. Guardar resultado final consolidado
    estructura_final = {
        "ultima_actualizacion": fecha_hora_actualizacion,
        "total_ofertas": len(lista_final),
        "ofertas": lista_final
    }

    with open("ofertas.json", "w", encoding="utf-8") as f:
        json.dump(estructura_final, f, ensure_ascii=False, indent=4)

    print(f"\n✅ PROCESO FINALIZADO EXITOSAMENTE:")
    print(f"    - Total vacantes en la base de datos: {len(lista_final)}")
    print(f"    - Nuevas ofertas incorporadas hoy: {n_nuevas}")
    print(f"    - Archivo ofertas.json actualizado a las {fecha_hora_actualizacion}.")

if __name__ == "__main__":
    obtener_ofertas()
