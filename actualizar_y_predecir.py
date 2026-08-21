"""
PIPELINE DE ACTUALIZACION AUTOMATICA
1. Descarga resultados recientes y proximos partidos de football-data.org
2. Actualiza el historico con partidos ya jugados
3. Genera picks para los proximos partidos con el modelo (Poisson + Dixon-Coles)
4. Guarda los picks en un archivo para usarlos en la app

Este script esta pensado para correr AUTOMATICAMENTE todos los dias
(se configura con el Programador de Tareas de Windows).
"""
import requests
import re
import pandas as pd
import numpy as np
import json
from scipy.stats import poisson, skellam
from datetime import datetime, timedelta
import os

API_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "TU_TOKEN_AQUI")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_TOKEN}
TEMPORADA_ACTUAL = 2026
MAX_GOLES = 6

# ---------- Configuracion de cada liga soportada ----------
# Para agregar una liga nueva, solo hay que agregar una entrada aqui --
# el resto del pipeline ya esta preparado para trabajar con cualquiera.
LIGAS = {
    "premier_league": {
        "nombre_mostrar": "Premier League",
        "codigo_api": "PL",              # codigo de football-data.org
        "codigo_footballdata": "E0",      # codigo de football-data.co.uk
        "archivo_historico": "premier_league_combinado.csv",
        "equipos_sin_historial": ["Coventry", "Hull"],
        "mapeo_nombres": {
            "AFC Bournemouth": "Bournemouth",
            "Arsenal FC": "Arsenal",
            "Aston Villa FC": "Aston Villa",
            "Brentford FC": "Brentford",
            "Brighton & Hove Albion FC": "Brighton",
            "Chelsea FC": "Chelsea",
            "Coventry City FC": "Coventry",
            "Crystal Palace FC": "Crystal Palace",
            "Everton FC": "Everton",
            "Fulham FC": "Fulham",
            "Hull City AFC": "Hull",
            "Ipswich Town FC": "Ipswich",
            "Leeds United FC": "Leeds",
            "Liverpool FC": "Liverpool",
            "Manchester City FC": "Man City",
            "Manchester United FC": "Man United",
            "Newcastle United FC": "Newcastle",
            "Nottingham Forest FC": "Nott'm Forest",
            "Sunderland AFC": "Sunderland",
            "Tottenham Hotspur FC": "Tottenham",
        },
    },
    "la_liga": {
        "nombre_mostrar": "LaLiga",
        "codigo_api": "PD",               # Primera Division
        "codigo_footballdata": "SP1",
        "archivo_historico": "la_liga_combinado.csv",
        # Equipos recien ascendidos a Primera 2025/26, sin historial reciente
        "equipos_sin_historial": ["Oviedo", "Levante", "Elche"],
        "mapeo_nombres": {
            "Real Madrid CF": "Real Madrid",
            "FC Barcelona": "Barcelona",
            "Club Atlético de Madrid": "Ath Madrid",
            "Athletic Club": "Ath Bilbao",
            "Villarreal CF": "Villarreal",
            "Real Betis Balompié": "Betis",
            "Real Sociedad de Fútbol": "Sociedad",
            "RC Celta de Vigo": "Celta",
            "Rayo Vallecano de Madrid": "Vallecano",
            "Getafe CF": "Getafe",
            "CA Osasuna": "Osasuna",
            "Sevilla FC": "Sevilla",
            "Valencia CF": "Valencia",
            "Girona FC": "Girona",
            "RCD Mallorca": "Mallorca",
            "Real Oviedo": "Oviedo",
            "RCD Espanyol de Barcelona": "Espanyol",
            "Levante UD": "Levante",
            "Elche CF": "Elche",
            "Deportivo Alavés": "Alaves",
        },
    },
}

LIGAS_ACTIVAS = ["premier_league", "la_liga"]  # cuales corren en cada ejecucion

# Estas variables se reasignan al inicio de cada liga (ver correr_pipeline_liga
# al final del archivo) -- el resto de las funciones las usan sin saber que
# cambian entre una liga y otra. Los valores de aqui son solo el default
# inicial (Premier League), para que el archivo siga siendo valido si algo
# se importa antes de que corra el bucle principal.
LIGA_ACTUAL = "premier_league"
ARCHIVO_HISTORICO = LIGAS["premier_league"]["archivo_historico"]
MAPEO_NOMBRES = LIGAS["premier_league"]["mapeo_nombres"]
EQUIPOS_SIN_HISTORIAL = LIGAS["premier_league"]["equipos_sin_historial"]
ARCHIVO_PICKS = "picks_del_dia.csv"
ARCHIVO_COMBINADAS = "combinadas_del_dia.json"



# ---------- Paso 1: traer datos de football-data.org ----------

def obtener_partidos_temporada(codigo_api="PL"):
    # No mandamos el parametro 'season': la API usa la temporada actual por
    # defecto, y el plan gratuito de todas formas solo da acceso a esa.
    # Mandar season=YYYY explicito puede causar error 400 si el sistema
    # todavia no tiene esa temporada completamente registrada.
    resp = requests.get(
        f"{BASE_URL}/competitions/{codigo_api}/matches",
        headers=HEADERS
    )
    resp.raise_for_status()
    return resp.json().get("matches", [])

# ---------- Paso 2: actualizar historico con partidos ya jugados ----------

def actualizar_historico(partidos):
    if not os.path.exists(ARCHIVO_HISTORICO):
        print(f"No se encontro {ARCHIVO_HISTORICO}. Ejecuta primero el paso de datos historicos.")
        return

    historico = pd.read_csv(ARCHIVO_HISTORICO)
    historico["Date"] = pd.to_datetime(historico["Date"], dayfirst=True)

    finalizados = [p for p in partidos if p["status"] == "FINISHED"]
    nuevos = []

    for p in finalizados:
        local = MAPEO_NOMBRES.get(p["homeTeam"]["name"], p["homeTeam"]["name"])
        visitante = MAPEO_NOMBRES.get(p["awayTeam"]["name"], p["awayTeam"]["name"])
        fecha = pd.to_datetime(p["utcDate"]).tz_localize(None)

        ya_existe = ((historico["Date"] == fecha) &
                     (historico["HomeTeam"] == local) &
                     (historico["AwayTeam"] == visitante)).any()
        if ya_existe:
            continue

        gh = p["score"]["fullTime"]["home"]
        ga = p["score"]["fullTime"]["away"]
        ftr = "H" if gh > ga else ("A" if ga > gh else "D")

        nuevos.append({"Date": fecha, "HomeTeam": local, "AwayTeam": visitante,
                        "FTHG": gh, "FTAG": ga, "FTR": ftr})

    if nuevos:
        df_nuevos = pd.DataFrame(nuevos)
        historico = pd.concat([historico, df_nuevos], ignore_index=True)
        # Guardamos la fecha SIEMPRE en el mismo formato (dd/mm/aaaa) para
        # que la proxima lectura del archivo no tenga formatos mezclados
        historico_a_guardar = historico.copy()
        historico_a_guardar["Date"] = pd.to_datetime(historico_a_guardar["Date"]).dt.strftime("%d/%m/%Y")
        historico_a_guardar.to_csv(ARCHIVO_HISTORICO, index=False)
        print(f"Se agregaron {len(nuevos)} partidos nuevos al historico.")
    else:
        print("No hay partidos nuevos que agregar (nadie ha jugado desde la ultima actualizacion).")

    return historico

TEMPORADA_CODIGO_FDCOUK = "2627"  # temporada 2026/27 en el formato de football-data.co.uk

def actualizar_estadisticas_extra(historico, codigo_footballdata="E0"):
    """
    football-data.org (usado arriba) NO incluye corners/tarjetas en el plan
    gratuito. Para mantener esos datos frescos durante la temporada, volvemos
    a descargar el archivo de la temporada actual desde football-data.co.uk
    (se actualiza dos veces por semana) y completamos corners/tarjetas/arbitro
    para los partidos que ya tenemos, cuando esten disponibles.
    """
    url = f"https://www.football-data.co.uk/mmz4281/{TEMPORADA_CODIGO_FDCOUK}/{codigo_footballdata}.csv"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Aviso: no se pudo descargar estadisticas extra de football-data.co.uk todavia ({e}). "
              f"Es normal si la temporada aun no ha empezado.")
        return historico

    import io
    columnas_extra = ["HC", "AC", "HY", "AY", "Referee"]
    try:
        actual = pd.read_csv(io.StringIO(resp.text))
    except Exception as e:
        print(f"Aviso: el archivo de football-data.co.uk no se pudo leer todavia ({e}).")
        return historico

    columnas_disponibles = [c for c in columnas_extra if c in actual.columns]
    if not columnas_disponibles:
        print("Aviso: el archivo de la temporada actual todavia no trae corners/tarjetas.")
        return historico

    actual["Date"] = pd.to_datetime(actual["Date"], dayfirst=True)

    # Nos aseguramos de que las columnas extra existan en el historico
    for col in columnas_disponibles:
        if col not in historico.columns:
            historico[col] = pd.NA

    actualizados = 0
    for _, fila in actual.iterrows():
        mask = ((historico["Date"] == fila["Date"]) &
                 (historico["HomeTeam"] == fila["HomeTeam"]) &
                 (historico["AwayTeam"] == fila["AwayTeam"]))
        if mask.any():
            for col in columnas_disponibles:
                if pd.notna(fila.get(col)):
                    historico.loc[mask, col] = fila[col]
            actualizados += 1

    if actualizados:
        historico_a_guardar = historico.copy()
        historico_a_guardar["Date"] = pd.to_datetime(historico_a_guardar["Date"]).dt.strftime("%d/%m/%Y")
        historico_a_guardar.to_csv(ARCHIVO_HISTORICO, index=False)
        print(f"Estadisticas extra (corners/tarjetas) actualizadas para {actualizados} partidos.")
    else:
        print("Sin cambios en corners/tarjetas esta vez.")

    return historico

# ---------- Paso 3: modelo (fuerzas + Dixon-Coles) ----------

def calcular_fuerzas(df):
    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df = df.copy()
    df["peso"] = peso

    prom_local = (df["FTHG"] * df["peso"]).sum() / df["peso"].sum()
    prom_visit = (df["FTAG"] * df["peso"]).sum() / df["peso"].sum()

    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df[df["HomeTeam"] == equipo]
        pv = df[df["AwayTeam"] == equipo]
        if pl["peso"].sum() == 0 or pv["peso"].sum() == 0:
            continue
        fuerzas[equipo] = {
            "ataque_local": (pl["FTHG"]*pl["peso"]).sum()/pl["peso"].sum() / prom_local,
            "defensa_local": (pl["FTAG"]*pl["peso"]).sum()/pl["peso"].sum() / prom_visit,
            "ataque_visitante": (pv["FTAG"]*pv["peso"]).sum()/pv["peso"].sum() / prom_visit,
            "defensa_visitante": (pv["FTHG"]*pv["peso"]).sum()/pv["peso"].sum() / prom_local,
        }

    # Equipos recien ascendidos sin historial: usamos el promedio de los
    # equipos mas debiles del historico como punto de partida conservador
    if fuerzas:
        ataques_local = sorted(f["ataque_local"] for f in fuerzas.values())
        defensas_local = sorted(f["defensa_local"] for f in fuerzas.values())
        n_debiles = max(1, len(fuerzas)//4)  # el 25% mas debil
        default_ataque = np.mean(ataques_local[:n_debiles])
        default_defensa = np.mean(defensas_local[-n_debiles:])
    else:
        default_ataque, default_defensa = 0.85, 1.15

    for equipo in EQUIPOS_SIN_HISTORIAL:
        if equipo not in fuerzas:
            fuerzas[equipo] = {
                "ataque_local": default_ataque, "defensa_local": default_defensa,
                "ataque_visitante": default_ataque, "defensa_visitante": default_defensa,
            }
            print(f"Aviso: {equipo} no tiene historial, usando fuerza conservadora por defecto.")

    return fuerzas, prom_local, prom_visit

def tau_dixon_coles(x, y, lam, mu, rho):
    if x == 0 and y == 0: return 1 - lam*mu*rho
    elif x == 0 and y == 1: return 1 + lam*rho
    elif x == 1 and y == 0: return 1 + mu*rho
    elif x == 1 and y == 1: return 1 - rho
    else: return 1

def goles_esperados(local, visitante, fuerzas, prom_local, prom_visit):
    if local not in fuerzas or visitante not in fuerzas:
        return None
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam_l = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    lam_v = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    return lam_l, lam_v

def matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho):
    resultado = goles_esperados(local, visitante, fuerzas, prom_l, prom_v)
    if resultado is None:
        return None, None, None
    lam, mu = resultado
    matriz = np.zeros((MAX_GOLES+1, MAX_GOLES+1))
    for i in range(MAX_GOLES+1):
        for j in range(MAX_GOLES+1):
            tau = tau_dixon_coles(min(i,1), min(j,1), lam, mu, rho)
            matriz[i][j] = max(tau, 0) * poisson.pmf(i, lam) * poisson.pmf(j, mu)
    matriz = matriz / matriz.sum()
    return matriz, lam, mu

def calcular_mercados(matriz):
    n = matriz.shape[0]
    p_local = sum(matriz[i][j] for i in range(n) for j in range(n) if i > j)
    p_empate = sum(matriz[i][j] for i in range(n) for j in range(n) if i == j)
    p_visit = sum(matriz[i][j] for i in range(n) for j in range(n) if i < j)
    p_btts_si = sum(matriz[i][j] for i in range(1, n) for j in range(1, n))
    p_over_25 = sum(matriz[i][j] for i in range(n) for j in range(n) if i+j > 2)
    p_handicap_local = p_local / (p_local + p_visit)
    return {
        "prob_local": p_local, "prob_empate": p_empate, "prob_visitante": p_visit,
        "doble_op_1X": p_local+p_empate, "doble_op_X2": p_visit+p_empate,
        "btts_si": p_btts_si, "btts_no": 1-p_btts_si,
        "over_25": p_over_25, "under_25": 1-p_over_25,
        "handicap_local_-0.5": p_handicap_local, "handicap_visitante_+0.5": 1-p_handicap_local,
    }

def ajustar_rho(df, fuerzas, prom_l, prom_v):
    mejor_rho, mejor_verosim = 0, -np.inf
    for rho in np.arange(-0.30, 0.11, 0.02):  # paso mas grande = mas rapido
        log_verosim = 0
        for _, partido in df.iterrows():
            resultado = goles_esperados(partido["HomeTeam"], partido["AwayTeam"], fuerzas, prom_l, prom_v)
            if resultado is None:
                continue
            lam, mu = resultado
            x, y = int(partido["FTHG"]), int(partido["FTAG"])
            tau = tau_dixon_coles(min(x,1), min(y,1), lam, mu, rho)
            if tau <= 0:
                continue
            prob = tau * poisson.pmf(x, lam) * poisson.pmf(y, mu)
            if prob > 0:
                log_verosim += np.log(prob)
        if log_verosim > mejor_verosim:
            mejor_verosim = log_verosim
            mejor_rho = rho
    return mejor_rho


# ---------- Motor de decision: mejor mercado individual O combo de 2 ----------

CONDICIONES = {
    "Local gana": lambda i, j: i > j,
    "Empate": lambda i, j: i == j,
    "Visitante gana": lambda i, j: i < j,
    "Doble oportunidad 1X": lambda i, j: i >= j,
    "Doble oportunidad X2": lambda i, j: i <= j,
    "Over 1.5 goles": lambda i, j: (i + j) > 1.5,
    "Over 2.5 goles": lambda i, j: (i + j) > 2.5,
    "Under 2.5 goles": lambda i, j: (i + j) < 2.5,
    "Ambos anotan - Si": lambda i, j: i >= 1 and j >= 1,
    "Ambos anotan - No": lambda i, j: not (i >= 1 and j >= 1),
}

# Solo se combinan mercados de categorias DISTINTAS (evita combos contradictorios
# o redundantes, como "Local gana" + "Doble oportunidad 1X" que ya se implican entre si)
CATEGORIAS = {
    "Local gana": "resultado", "Empate": "resultado", "Visitante gana": "resultado",
    "Doble oportunidad 1X": "resultado", "Doble oportunidad X2": "resultado",
    "Over 1.5 goles": "goles", "Over 2.5 goles": "goles", "Under 2.5 goles": "goles",
    "Ambos anotan - Si": "btts", "Ambos anotan - No": "btts",
}

def calcular_combo(matriz, lista_condiciones):
    n = matriz.shape[0]
    return sum(
        matriz[i][j] for i in range(n) for j in range(n)
        if all(CONDICIONES[c](i, j) for c in lista_condiciones)
    )

ARCHIVO_HISTORIAL_COMBINADAS = "historial_combinadas.csv"
ARCHIVO_CONTADOR_FECHAS = "contador_fechas.json"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def obtener_numero_fecha(fecha_partido):
    """
    Asigna un numero de 'Fecha' (jornada) secuencial segun la semana del
    calendario en la que cae el partido. La primera semana que se ve se
    numera como Fecha 1, la siguiente semana nueva como Fecha 2, etc.
    Se guarda en un archivo para que el conteo sea consistente entre corridas.
    """
    semana = fecha_partido.strftime("%G-W%V")  # ej. "2026-W34"

    if os.path.exists(ARCHIVO_CONTADOR_FECHAS):
        with open(ARCHIVO_CONTADOR_FECHAS, "r", encoding="utf-8") as f:
            mapa = json.load(f)
    else:
        mapa = {}

    if semana not in mapa:
        mapa[semana] = max(mapa.values(), default=0) + 1
        with open(ARCHIVO_CONTADOR_FECHAS, "w", encoding="utf-8") as f:
            json.dump(mapa, f, ensure_ascii=False, indent=2)

    return mapa[semana]

def cargar_historial_combinadas():
    if os.path.exists(ARCHIVO_HISTORIAL_COMBINADAS):
        h = pd.read_csv(ARCHIVO_HISTORIAL_COMBINADAS)
        h["resultado"] = h["resultado"].astype(object)
        return h
    return pd.DataFrame(columns=["id_combinada", "numero_fecha", "fecha_generado", "es_gratis",
                                   "partidos_json", "cuota_combinada", "resultado"])

def registrar_combinadas_historial(combinadas, picks_df, historial_combinadas):
    """Guarda cada combinada nueva (identificada por su conjunto exacto de
    partidos) para que quede registrada permanentemente, aunque el dia
    siguiente se recalculen combinadas distintas."""
    nuevas = []
    for c in combinadas:
        partidos_ids = sorted(f"{p['local']}|{p['visitante']}" for p in c["partidos"])
        id_combinada = "+".join(partidos_ids)

        if (historial_combinadas["id_combinada"] == id_combinada).any():
            continue  # ya estaba registrada

        # Buscamos la fecha del primer partido de la combinada para asignar el numero de fecha
        primer_partido = c["partidos"][0]
        fila_pick = picks_df[(picks_df["local"] == primer_partido["local"]) &
                               (picks_df["visitante"] == primer_partido["visitante"])]
        fecha_ref = fila_pick.iloc[0]["fecha"] if not fila_pick.empty else datetime.utcnow()
        numero_fecha = obtener_numero_fecha(pd.Timestamp(fecha_ref))

        nuevas.append({
            "id_combinada": id_combinada,
            "numero_fecha": numero_fecha,
            "fecha_generado": datetime.utcnow().strftime("%Y-%m-%d"),
            "es_gratis": c["es_gratis"],
            "partidos_json": json.dumps(c["partidos"], ensure_ascii=False, default=str),
            "cuota_combinada": c["cuota_combinada"],
            "resultado": None,
        })

    if nuevas:
        historial_combinadas = pd.concat([historial_combinadas, pd.DataFrame(nuevas)], ignore_index=True)
        print(f"Se registraron {len(nuevas)} combinadas nuevas en el historial.")
    return historial_combinadas

def verificar_combinadas_resueltas(historial_combinadas, historico_partidos):
    """Una combinada se marca 'Cumplida' solo si TODOS sus partidos ganaron
    su pick; 'Fallada' si al menos uno perdio. Si algun partido de la
    combinada todavia no se juega, se queda 'Pendiente'."""
    pendientes = historial_combinadas[historial_combinadas["resultado"].isna()]
    resueltas_ahora = 0

    for idx, combinada in pendientes.iterrows():
        partidos = json.loads(combinada["partidos_json"])
        resultados_legs = []
        completa = True

        for p in partidos:
            fecha_partido = pd.Timestamp(p["fecha"])
            match = historico_partidos[
                (historico_partidos["Date"] == fecha_partido) &
                (historico_partidos["HomeTeam"] == p["local"]) &
                (historico_partidos["AwayTeam"] == p["visitante"])
            ]
            if match.empty or pd.isna(match.iloc[0].get("FTHG")):
                completa = False
                break
            resultado_leg = verificar_pick_individual(p["pick_recomendado"], match.iloc[0])
            if resultado_leg is None:
                completa = False
                break
            resultados_legs.append(resultado_leg)

        if not completa:
            continue  # todavia falta algun partido de esta combinada

        historial_combinadas.at[idx, "resultado"] = "Cumplida" if all(resultados_legs) else "Fallada"
        resueltas_ahora += 1

    if resueltas_ahora:
        print(f"Se verificaron {resueltas_ahora} combinadas que ya se completaron.")
    return historial_combinadas

def calibrar_probabilidad(prob):
    """
    Corrige la probabilidad "cruda" que calcula el modelo para que refleje
    el acierto real observado historicamente (Platt Scaling), en vez del
    numero optimista que sale directo de Poisson/Dixon-Coles.

    Entrenado con un backtest de 4 temporadas (12,943 observaciones de
    mercados individuales, umbral relevante >=60%). Sin esto, el modelo
    tiende a sobreestimar su propia confianza por 4-9 puntos porcentuales,
    especialmente en combinadas (donde el error se multiplica).
    """
    PENDIENTE = 4.8797
    INTERCEPTO = -2.6940
    z = INTERCEPTO + PENDIENTE * prob
    return 1 / (1 + np.exp(-z))

def elegir_mejor_pick(matriz, umbral_minimo=0.65, mercados_extra=None, mercados_extra_combinables=None):
    """
    Evalua mercados de goles/resultado (individuales + combos de 2 validos).
    mercados_extra: TODOS los mercados adicionales (corners, tarjetas, etc.)
    se agregan como candidatos individuales.
    mercados_extra_combinables: SOLO el subconjunto de esos que ya se valido
    con datos reales como razonablemente independiente de los goles -- esos
    tambien se prueban en combo de 1 mercado de goles + 1 de este subconjunto.
    """
    candidatos = []

    for nombre, cond in CONDICIONES.items():
        prob = calcular_combo(matriz, [nombre])
        candidatos.append(([nombre], prob))

    nombres = list(CONDICIONES.keys())
    for i in range(len(nombres)):
        for j in range(i+1, len(nombres)):
            n1, n2 = nombres[i], nombres[j]
            if CATEGORIAS[n1] == CATEGORIAS[n2]:
                continue
            prob = calcular_combo(matriz, [n1, n2])
            candidatos.append(([n1, n2], prob))

    if mercados_extra:
        for nombre, prob in mercados_extra.items():
            candidatos.append(([nombre], prob))

    if mercados_extra_combinables:
        for nombre_goles in CONDICIONES:
            prob_goles = calcular_combo(matriz, [nombre_goles])
            for nombre_extra, prob_extra in mercados_extra_combinables.items():
                candidatos.append(([nombre_goles, nombre_extra], prob_goles * prob_extra))

    # Calibramos TODOS los candidatos antes de decidir -- asi el umbral de
    # seguridad se aplica sobre el acierto real esperado, no sobre el
    # numero optimista que sale directo del modelo estadistico
    candidatos = [(nombres, calibrar_probabilidad(prob)) for nombres, prob in candidatos]

    seguros = [c for c in candidatos if c[1] >= umbral_minimo]

    if seguros:
        mejor = min(seguros, key=lambda c: c[1])
        cumple_umbral = True
    else:
        mejor = max(candidatos, key=lambda c: c[1])
        cumple_umbral = False

    nombres_pick, prob = mejor
    # Restamos un pequeño margen (0.10) a la cuota que mostramos: la cuota
    # "justa" que calculamos es teorica, y las casas de apuestas reales
    # siempre pagan un poco menos por su propio margen de ganancia. Esto
    # hace que el numero que mostramos sea una estimacion mas realista de
    # lo que el usuario va a encontrar de verdad al ir a apostar.
    cuota = max(1 / prob - 0.10, 1.01) if prob > 0 else None
    return nombres_pick, prob, cuota, cumple_umbral

ARCHIVO_HISTORIAL_PICKS = "historial_picks.csv"

# ---------- Track record: registrar y verificar picks ----------

def cargar_historial_picks():
    if os.path.exists(ARCHIVO_HISTORIAL_PICKS):
        h = pd.read_csv(ARCHIVO_HISTORIAL_PICKS)
        h["fecha_partido"] = pd.to_datetime(h["fecha_partido"])
        # Forzamos estas columnas a tipo "objeto" (texto) para evitar errores
        # cuando pandas las infiere como numericas por estar vacias (NaN)
        h["resultado_real"] = h["resultado_real"].astype(object)
        h["acierto"] = h["acierto"].astype(object)
        return h
    return pd.DataFrame(columns=[
        "fecha_partido", "local", "visitante", "pick_recomendado", "es_combo",
        "pick_probabilidad", "pick_cuota_aprox", "fecha_generado",
        "resultado_real", "acierto"
    ])

def registrar_picks_nuevos(picks_actuales, historial):
    """Agrega a historial los partidos que todavia no estaban registrados
    (asi el pick queda 'congelado' la primera vez que se genero, sin
    sobreescribirse cada dia con nueva informacion)."""
    nuevos = []
    for _, pick in picks_actuales.iterrows():
        ya_existe = ((historial["fecha_partido"] == pick["fecha"]) &
                     (historial["local"] == pick["local"]) &
                     (historial["visitante"] == pick["visitante"])).any()
        if ya_existe:
            continue
        nuevos.append({
            "fecha_partido": pick["fecha"], "local": pick["local"], "visitante": pick["visitante"],
            "pick_recomendado": pick["pick_recomendado"], "es_combo": pick["es_combo"],
            "pick_probabilidad": pick["pick_probabilidad"], "pick_cuota_aprox": pick["pick_cuota_aprox"],
            "fecha_generado": datetime.utcnow().strftime("%Y-%m-%d"),
            "resultado_real": None, "acierto": None,
        })
    if nuevos:
        historial = pd.concat([historial, pd.DataFrame(nuevos)], ignore_index=True)
        print(f"Se registraron {len(nuevos)} picks nuevos en el historial.")
    return historial

def verificar_pick_individual(nombre, fila_resultado):
    """
    Verifica si UN mercado especifico se cumplio, usando el resultado real
    del partido. Entiende mercados de goles (via CONDICIONES), y tambien
    los mercados dinamicos de corners/tarjetas/tiros a puerta (Over/Under
    y "Mas X: Equipo"). Devuelve True/False, o None si no se pudo verificar
    (ej. falta el dato de esa metrica para ese partido).
    """
    gh, ga = fila_resultado.get("FTHG"), fila_resultado.get("FTAG")

    if nombre in CONDICIONES:
        if pd.isna(gh) or pd.isna(ga):
            return None
        return CONDICIONES[nombre](int(gh), int(ga))

    columnas_por_tipo = {
        "corners": ("HC", "AC"),
        "tarjetas": ("HY", "AY"),
        "tiros a puerta": ("HST", "AST"),
    }

    m = re.match(r"(Over|Under) ([\d.]+) (corners|tarjetas|tiros a puerta)", nombre)
    if m:
        direccion, linea, tipo = m.group(1), float(m.group(2)), m.group(3)
        col_l, col_v = columnas_por_tipo[tipo]
        val_l, val_v = fila_resultado.get(col_l), fila_resultado.get(col_v)
        if pd.isna(val_l) or pd.isna(val_v):
            return None
        total = val_l + val_v
        return (total > linea) if direccion == "Over" else (total < linea)

    m2 = re.match(r"Más (corners|tarjetas|tiros a puerta): (.+)", nombre)
    if m2:
        tipo, equipo = m2.group(1), m2.group(2)
        col_l, col_v = columnas_por_tipo[tipo]
        val_l, val_v = fila_resultado.get(col_l), fila_resultado.get(col_v)
        if pd.isna(val_l) or pd.isna(val_v):
            return None
        if equipo == fila_resultado.get("HomeTeam"):
            return val_l > val_v
        elif equipo == fila_resultado.get("AwayTeam"):
            return val_v > val_l

    return None  # nombre de mercado no reconocido

def verificar_picks_resueltos(historial, historico_partidos):
    """Revisa los picks pendientes (sin resultado) y, si el partido ya se jugo
    (aparece en el historico con resultado), calcula si el pick acerto o no.
    Ahora entiende TODOS los tipos de mercado (goles, corners, tarjetas, tiros)."""
    pendientes = historial[historial["acierto"].isna()]
    resueltos_ahora = 0

    for idx, pick in pendientes.iterrows():
        match = historico_partidos[
            (historico_partidos["Date"] == pick["fecha_partido"]) &
            (historico_partidos["HomeTeam"] == pick["local"]) &
            (historico_partidos["AwayTeam"] == pick["visitante"])
        ]
        if match.empty:
            continue  # el partido todavia no se ha jugado

        fila = match.iloc[0]
        gh, ga = fila.get("FTHG"), fila.get("FTAG")
        if pd.isna(gh) or pd.isna(ga):
            continue  # resultado de goles incompleto, esperamos

        condiciones_pick = pick["pick_recomendado"].split(" + ")
        resultados_leg = [verificar_pick_individual(c, fila) for c in condiciones_pick]

        if any(r is None for r in resultados_leg):
            continue  # falta algun dato (ej. corners no disponibles ese partido), esperamos

        acierto = all(resultados_leg)

        historial.at[idx, "resultado_real"] = f"{gh}-{ga}"
        historial.at[idx, "acierto"] = acierto
        resueltos_ahora += 1

    if resueltos_ahora:
        print(f"Se verificaron {resueltos_ahora} picks que ya se jugaron.")
    return historial

def verificar_calibracion_continua(historial, umbral_alerta=8.0, minimo_muestras=30):
    """
    Revisa, usando los picks individuales YA RESUELTOS (historial_picks),
    si la calibracion sigue siendo honesta: compara la probabilidad que
    el modelo declaro contra el acierto real observado hasta ahora en esta
    temporada. Si la brecha supera 'umbral_alerta' puntos porcentuales,
    imprime una advertencia clara y la guarda en Supabase para que quede
    registrada -- asi no dependes de acordarte de revisarlo tu mismo.
    """
    resueltos = historial.dropna(subset=["acierto"])
    resueltos = resueltos[resueltos["pick_probabilidad"] >= 70]  # rango relevante

    n = len(resueltos)
    if n < minimo_muestras:
        print(f"\n[Calibracion] Todavia hay pocos picks resueltos esta temporada ({n}/{minimo_muestras}) "
              f"para revisar la calibracion de forma confiable. Se revisara automaticamente "
              f"en cuanto haya suficientes.")
        return

    prob_declarada = resueltos["pick_probabilidad"].mean()
    acierto_real = resueltos["acierto"].astype(float).mean() * 100
    diferencia = acierto_real - prob_declarada
    necesita_recalibrar = abs(diferencia) > umbral_alerta

    if necesita_recalibrar:
        mensaje = (f"ALERTA: la calibracion parece haberse desviado. Con {n} picks resueltos, "
                   f"el modelo declara en promedio {prob_declarada:.1f}% pero el acierto real es "
                   f"{acierto_real:.1f}% (diferencia de {diferencia:+.1f} puntos). "
                   f"Se recomienda repetir el backtest de calibracion pronto.")
        print(f"\n{'='*70}\n[Calibracion] {mensaje}\n{'='*70}")
    else:
        mensaje = (f"La calibracion sigue siendo confiable. Con {n} picks resueltos, "
                   f"declarado {prob_declarada:.1f}% vs real {acierto_real:.1f}% "
                   f"(diferencia de {diferencia:+.1f} puntos, dentro de lo esperado).")
        print(f"\n[Calibracion] {mensaje}")

    if supabase_configurado():
        registro = {
            "n_muestras": int(n),
            "prob_declarada_promedio": round(float(prob_declarada), 2),
            "acierto_real_promedio": round(float(acierto_real), 2),
            "diferencia": round(float(diferencia), 2),
            "necesita_recalibrar": bool(necesita_recalibrar),
            "mensaje": mensaje,
        }
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/alertas_calibracion", headers=supabase_headers(), json=registro)
        if resp.status_code not in (200, 201):
            print(f"Aviso: no se pudo guardar la alerta de calibracion en Supabase ({resp.status_code})")


def resumen_track_record(historial):
    resueltos = historial[historial["acierto"].notna()]
    if len(resueltos) == 0:
        print("Todavia no hay picks resueltos (ningun partido registrado se ha jugado aun).")
        return
    aciertos = resueltos["acierto"].astype(bool).sum()
    total = len(resueltos)
    print(f"\n=== TRACK RECORD ===")
    print(f"Picks resueltos: {total}")
    print(f"Aciertos: {aciertos} ({aciertos/total*100:.1f}%)")

def calcular_combinadas_multiples(picks_df, cuota_objetivo=1.70, cuota_minima=1.60, max_combinadas=3, max_partidos_por_combinada=5):
    """
    Genera varias combinadas SIN repetir partidos entre ellas. Apunta a
    cuota_objetivo (1.70 por defecto); si un dia no hay suficientes picks
    seguros para llegar ahi, acepta hasta cuota_minima (1.60) antes de
    avisar que ese dia el mercado esta mas parejo de lo normal.
    """
    seguros = picks_df[picks_df["pick_es_seguro"] == True].copy()
    seguros = seguros.sort_values("pick_probabilidad", ascending=False).reset_index(drop=True)

    disponibles = seguros.copy()
    combinadas = []

    for n in range(max_combinadas):
        if len(disponibles) < 2:
            break

        prob_acumulada = 1.0
        elegidos = []
        indices_usados = []

        for idx, partido in disponibles.iterrows():
            prob_acumulada *= partido["pick_probabilidad"] / 100
            elegidos.append(partido)
            indices_usados.append(idx)
            cuota_actual = 1 / prob_acumulada
            # Solo permitimos detenernos por cuota objetivo si YA hay al menos
            # 2 partidos -- una combinada de 1 solo partido no es una combinada
            if (len(elegidos) >= 2 and cuota_actual >= cuota_objetivo) or len(elegidos) >= max_partidos_por_combinada:
                break

        if len(elegidos) < 2:
            break  # no hay suficientes partidos disponibles para armar una combinada completa

        elegidos_df = pd.DataFrame(elegidos)
        combinadas.append({
            "nombre": f"Combinada #{n+1}",
            "es_gratis": False,  # se decide despues, cuando ya tenemos todas generadas
            "partidos": elegidos_df[["fecha", "local", "visitante", "pick_recomendado", "pick_probabilidad"]].to_dict("records"),
            "probabilidad_combinada": round(prob_acumulada*100, 1),
            "cuota_combinada": round(max(1/prob_acumulada - 0.10, 1.01), 2),
        })

        # Quitamos esos partidos del pool para que la siguiente combinada use otros
        disponibles = disponibles.drop(indices_usados)

    # Todas las combinadas ya cumplen el mismo estandar de seguridad (el
    # mismo umbral_seguro), asi que no hay razon para regalar la menos
    # atractiva -- marcamos como gratis la de MEJOR cuota, para enganchar
    # mejor a los usuarios nuevos sin sacrificar nada de seguridad real.
    if combinadas:
        indice_mejor_cuota = max(range(len(combinadas)), key=lambda i: combinadas[i]["cuota_combinada"])
        combinadas[indice_mejor_cuota]["es_gratis"] = True

        # Reordenamos para que la gratis siempre aparezca primero, y
        # renombramos "Combinada #1, #2, #3..." segun ese nuevo orden --
        # asi la gratis SIEMPRE se llama "Combinada #1" para el usuario,
        # sin importar cual fue la mejor cuota ese dia.
        combinadas.insert(0, combinadas.pop(indice_mejor_cuota))
        for i, c in enumerate(combinadas):
            c["nombre"] = f"Combinada #{i+1}"

    print(f"\n=== {len(combinadas)} COMBINADAS GENERADAS ===")
    for c in combinadas:
        nombres = ", ".join(f"{p['local']} vs {p['visitante']}" for p in c["partidos"])
        etiqueta = "GRATIS" if c["es_gratis"] else "VIP"
        aviso = "" if c["cuota_combinada"] >= cuota_minima else "  <-- POR DEBAJO DEL PISO MINIMO"
        print(f"{c['nombre']} [{etiqueta}]: {nombres} -> cuota {c['cuota_combinada']}{aviso}")

    return combinadas

def calcular_umbral_dinamico(historial, umbral_base=0.75, umbral_alto=0.80, ventana=10):
    """
    Revisa los ultimos picks resueltos (aprox. 1 fecha completa, ~10 partidos).
    Si la tasa de acierto reciente esta por debajo del 50%, sube el umbral
    de seguridad a umbral_alto como medida de precaucion real para la
    siguiente fecha. Esto NO es "esforzarse mas" ni reaccionar por panico --
    es simplemente exigir mayor probabilidad individual antes de recomendar
    un pick, que es la unica palanca honesta que existe.
    """
    resueltos = historial[historial["acierto"].notna()].sort_values("fecha_partido")
    if len(resueltos) < ventana:
        print(f"Historial insuficiente para evaluar racha reciente (se necesitan {ventana} picks resueltos). Usando umbral base {umbral_base*100:.0f}%.")
        return umbral_base

    ultimos = resueltos.tail(ventana)
    tasa_acierto = ultimos["acierto"].astype(bool).mean()

    if tasa_acierto < 0.5:
        print(f"Aviso: tasa de acierto de los ultimos {ventana} picks fue {tasa_acierto*100:.1f}% "
              f"(por debajo del 50%). Subiendo umbral de seguridad a {umbral_alto*100:.0f}% como precaucion.")
        return umbral_alto

    print(f"Tasa de acierto de los ultimos {ventana} picks: {tasa_acierto*100:.1f}%. Umbral se mantiene en {umbral_base*100:.0f}%.")
    return umbral_base

# ---------- Mercado de corners (mismo patron que goles, columna distinta) ----------

def calcular_fuerzas_corners(df):
    if "HC" not in df.columns or "AC" not in df.columns:
        return {}, None, None
    df = df.dropna(subset=["HC", "AC"])
    if len(df) < 20:  # muy pocos datos con corners todavia, no vale la pena
        return {}, None, None

    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df = df.copy()
    df["peso"] = peso

    prom_local = (df["HC"] * df["peso"]).sum() / df["peso"].sum()
    prom_visit = (df["AC"] * df["peso"]).sum() / df["peso"].sum()

    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df[df["HomeTeam"] == equipo]
        pv = df[df["AwayTeam"] == equipo]
        if pl["peso"].sum() == 0 or pv["peso"].sum() == 0:
            continue
        fuerzas[equipo] = {
            "ataque_local": (pl["HC"]*pl["peso"]).sum()/pl["peso"].sum() / prom_local,
            "defensa_local": (pl["AC"]*pl["peso"]).sum()/pl["peso"].sum() / prom_visit,
            "ataque_visitante": (pv["AC"]*pv["peso"]).sum()/pv["peso"].sum() / prom_visit,
            "defensa_visitante": (pv["HC"]*pv["peso"]).sum()/pv["peso"].sum() / prom_local,
        }
    return fuerzas, prom_local, prom_visit

def calcular_mercados_corners(local, visitante, fuerzas, prom_local, prom_visit, lineas=(5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5)):
    if not fuerzas or local not in fuerzas or visitante not in fuerzas:
        return {}
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    mu = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    total = lam + mu

    mercados = {}
    for linea in lineas:
        p_over = 1 - poisson.cdf(linea, total)
        mercados[f"Over {linea} corners"] = p_over
        mercados[f"Under {linea} corners"] = 1 - p_over

    mercados[f"Más corners: {local}"] = 1 - skellam.cdf(0, lam, mu)
    mercados[f"Más corners: {visitante}"] = skellam.cdf(-1, lam, mu)

    return mercados

# ---------- Mercado de tarjetas amarillas (con factor de arbitro) ----------

def calcular_fuerzas_tarjetas(df):
    """
    Similar al modelo de corners, pero ademas calcula un factor por arbitro:
    algunos arbitros pitan sistematicamente mas/menos tarjetas que el promedio.
    """
    if "HY" not in df.columns or "AY" not in df.columns:
        return {}, {}, None, None
    df = df.dropna(subset=["HY", "AY"])
    if len(df) < 20:
        return {}, {}, None, None

    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df = df.copy()
    df["peso"] = peso

    prom_local = (df["HY"] * df["peso"]).sum() / df["peso"].sum()
    prom_visit = (df["AY"] * df["peso"]).sum() / df["peso"].sum()
    prom_total = prom_local + prom_visit

    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df[df["HomeTeam"] == equipo]
        pv = df[df["AwayTeam"] == equipo]
        if pl["peso"].sum() == 0 or pv["peso"].sum() == 0:
            continue
        fuerzas[equipo] = {
            "ataque_local": (pl["HY"]*pl["peso"]).sum()/pl["peso"].sum() / prom_local,
            "defensa_local": (pl["AY"]*pl["peso"]).sum()/pl["peso"].sum() / prom_visit,
            "ataque_visitante": (pv["AY"]*pv["peso"]).sum()/pv["peso"].sum() / prom_visit,
            "defensa_visitante": (pv["HY"]*pv["peso"]).sum()/pv["peso"].sum() / prom_local,
        }

    # Factor por arbitro: cuanto mas/menos pita respecto al promedio de la liga
    factores_arbitro = {}
    if "Referee" in df.columns:
        for arbitro in df["Referee"].dropna().unique():
            partidos_arbitro = df[df["Referee"] == arbitro]
            if partidos_arbitro["peso"].sum() < 3:  # muy pocos partidos, no confiable
                continue
            total_arbitro = ((partidos_arbitro["HY"] + partidos_arbitro["AY"]) * partidos_arbitro["peso"]).sum() / partidos_arbitro["peso"].sum()
            factores_arbitro[arbitro] = total_arbitro / prom_total

    return fuerzas, factores_arbitro, prom_local, prom_visit

def calcular_mercados_tarjetas(local, visitante, fuerzas, factores_arbitro, prom_local, prom_visit,
                                 arbitro=None, lineas=(3.5, 4.5, 5.5)):
    if not fuerzas or local not in fuerzas or visitante not in fuerzas:
        return {}
    fl, fv = fuerzas[local], fuerzas[visitante]

    factor_ref = 1.0  # neutral por defecto: no sabemos el arbitro o no tenemos su historial
    if arbitro and arbitro in factores_arbitro:
        factor_ref = factores_arbitro[arbitro]

    lam = prom_local * fl["ataque_local"] * fv["defensa_visitante"] * factor_ref
    mu = prom_visit * fv["ataque_visitante"] * fl["defensa_local"] * factor_ref
    total = lam + mu

    mercados = {}
    for linea in lineas:
        p_over = 1 - poisson.cdf(linea, total)
        mercados[f"Over {linea} tarjetas"] = p_over
        mercados[f"Under {linea} tarjetas"] = 1 - p_over

    return mercados

# ---------- Mercado de tiros a puerta (mismo patron que corners) ----------

def calcular_fuerzas_tiros(df):
    if "HST" not in df.columns or "AST" not in df.columns:
        return {}, None, None
    df = df.dropna(subset=["HST", "AST"])
    if len(df) < 20:
        return {}, None, None

    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df = df.copy()
    df["peso"] = peso

    prom_local = (df["HST"] * df["peso"]).sum() / df["peso"].sum()
    prom_visit = (df["AST"] * df["peso"]).sum() / df["peso"].sum()

    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df[df["HomeTeam"] == equipo]
        pv = df[df["AwayTeam"] == equipo]
        if pl["peso"].sum() == 0 or pv["peso"].sum() == 0:
            continue
        fuerzas[equipo] = {
            "ataque_local": (pl["HST"]*pl["peso"]).sum()/pl["peso"].sum() / prom_local,
            "defensa_local": (pl["AST"]*pl["peso"]).sum()/pl["peso"].sum() / prom_visit,
            "ataque_visitante": (pv["AST"]*pv["peso"]).sum()/pv["peso"].sum() / prom_visit,
            "defensa_visitante": (pv["HST"]*pv["peso"]).sum()/pv["peso"].sum() / prom_local,
        }
    return fuerzas, prom_local, prom_visit

def calcular_mercados_tiros(local, visitante, fuerzas, prom_local, prom_visit, lineas=None):
    if not fuerzas or local not in fuerzas or visitante not in fuerzas:
        return {}
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    mu = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    total = lam + mu

    # Las casas de apuestas reales no ofrecen un rango fijo amplio -- ponen
    # su linea principal cerca del promedio esperado de ESE partido y solo
    # agregan 1-2 alternativas cercanas (ej. si el promedio es ~8, ofrecen
    # 7.5/8.5/9.5, nunca algo como "Under 11.5"). Generamos las lineas de la
    # misma forma, centradas en el total esperado, para que el pick
    # recomendado siempre corresponda a algo que existe de verdad.
    if lineas is None:
        centro = round(total - 0.5) + 0.5  # la linea .5 mas cercana al promedio
        lineas = [centro - 1.5, centro - 0.5, centro + 0.5, centro + 1.5]
        lineas = [l for l in lineas if l >= 1.5]  # nunca lineas absurdamente bajas

    mercados = {}
    for linea in lineas:
        p_over = 1 - poisson.cdf(linea, total)
        mercados[f"Over {linea} tiros a puerta"] = p_over
        mercados[f"Under {linea} tiros a puerta"] = 1 - p_over

    mercados[f"Más tiros a puerta: {local}"] = 1 - skellam.cdf(0, lam, mu)
    mercados[f"Más tiros a puerta: {visitante}"] = skellam.cdf(-1, lam, mu)

    return mercados

def obtener_arbitro_partido(p):
    """
    Intenta extraer el nombre del arbitro desde la respuesta de football-data.org.
    Devuelve None si no esta disponible (partidos lejanos casi nunca lo tienen
    asignado todavia) -- en ese caso el modelo de tarjetas usa un arbitro
    "promedio" en vez de inventar un dato que no existe.
    """
    for oficial in p.get("referees", []) or []:
        if oficial.get("role") == "REFEREE" and oficial.get("name"):
            return oficial["name"]
    return None

# ---------- Subida de datos a Supabase (reemplaza los archivos publicos) ----------

def supabase_headers(upsert=False):
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates"
    return headers

def supabase_configurado():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

def limpiar_tabla_supabase(tabla, liga):
    """Borra las filas de una liga especifica en una tabla (usamos esto para
    picks/combinadas, que se regeneran completas cada vez que corre el
    pipeline PARA ESA LIGA -- nunca tocamos las filas de otras ligas)."""
    resp = requests.delete(f"{SUPABASE_URL}/rest/v1/{tabla}?liga=eq.{liga}", headers=supabase_headers())
    if resp.status_code not in (200, 204):
        print(f"Aviso: no se pudo limpiar la tabla '{tabla}' en Supabase ({resp.status_code}): {resp.text[:200]}")

def subir_picks_supabase(picks_df, liga, n_gratis=3):
    """Sube los picks individuales a Supabase, marcando los N mas seguros
    del dia como gratis (el resto queda VIP automaticamente)."""
    if not supabase_configurado():
        print("Supabase no configurado (faltan credenciales) -- se omite la subida.")
        return
    if len(picks_df) == 0:
        return

    df = picks_df.copy()
    df["es_gratis"] = False
    top_indices = df.sort_values("pick_probabilidad", ascending=False).head(n_gratis).index
    df.loc[top_indices, "es_gratis"] = True

    columnas_base = {"fecha", "local", "visitante", "pick_recomendado", "es_combo",
                      "pick_probabilidad", "pick_cuota_aprox", "pick_es_seguro", "es_gratis"}

    registros = []
    for _, fila in df.iterrows():
        mercados = {k: v for k, v in fila.items() if k not in columnas_base and pd.notna(v)}
        registros.append({
            "fecha": str(fila["fecha"]),
            "local": fila["local"],
            "visitante": fila["visitante"],
            "pick_recomendado": fila["pick_recomendado"],
            "es_combo": bool(fila["es_combo"]),
            "pick_probabilidad": float(fila["pick_probabilidad"]),
            "pick_cuota_aprox": float(fila["pick_cuota_aprox"]) if pd.notna(fila["pick_cuota_aprox"]) else None,
            "pick_es_seguro": bool(fila["pick_es_seguro"]),
            "es_gratis": bool(fila["es_gratis"]),
            "mercados_json": mercados,
            "liga": liga,
        })

    limpiar_tabla_supabase("picks", liga)
    resp = requests.post(f"{SUPABASE_URL}/rest/v1/picks", headers=supabase_headers(), json=registros)
    if resp.status_code in (200, 201):
        gratis_n = sum(1 for r in registros if r["es_gratis"])
        print(f"Subidos {len(registros)} picks a Supabase ({gratis_n} gratis, {len(registros)-gratis_n} VIP).")
    else:
        print(f"Aviso: fallo al subir picks a Supabase ({resp.status_code}): {resp.text[:300]}")

def subir_combinadas_supabase(combinadas, liga):
    if not supabase_configurado():
        return
    if not combinadas:
        return

    registros = [{
        "nombre": c["nombre"],
        "es_gratis": bool(c["es_gratis"]),
        "partidos_json": json.loads(json.dumps(c["partidos"], default=str)),
        "probabilidad_combinada": float(c["probabilidad_combinada"]),
        "cuota_combinada": float(c["cuota_combinada"]),
        "liga": liga,
    } for c in combinadas]

    limpiar_tabla_supabase("combinadas", liga)
    resp = requests.post(f"{SUPABASE_URL}/rest/v1/combinadas", headers=supabase_headers(), json=registros)
    if resp.status_code in (200, 201):
        print(f"Subidas {len(registros)} combinadas a Supabase.")
    else:
        print(f"Aviso: fallo al subir combinadas a Supabase ({resp.status_code}): {resp.text[:300]}")

def subir_historial_combinadas_supabase(historial_combinadas, liga):
    """A diferencia de picks/combinadas, el historial NUNCA se borra --
    se actualiza (upsert) para ir agregando fechas nuevas y marcando
    resultados sin perder lo que ya existia."""
    if not supabase_configurado():
        return
    if len(historial_combinadas) == 0:
        return

    registros = []
    for _, fila in historial_combinadas.iterrows():
        registros.append({
            "id_combinada": fila["id_combinada"],
            "numero_fecha": int(fila["numero_fecha"]),
            "fecha_generado": str(fila["fecha_generado"]),
            "es_gratis": bool(fila["es_gratis"]),
            "partidos_json": json.loads(fila["partidos_json"]),
            "cuota_combinada": float(fila["cuota_combinada"]),
            "resultado": fila["resultado"] if pd.notna(fila["resultado"]) else None,
            "liga": liga,
        })

    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/historial_combinadas?on_conflict=id_combinada",
        headers=supabase_headers(upsert=True), json=registros)
    if resp.status_code in (200, 201, 204):
        print(f"Historial de combinadas sincronizado con Supabase ({len(registros)} registros).")
    else:
        print(f"Aviso: fallo al sincronizar historial en Supabase ({resp.status_code}): {resp.text[:300]}")

# ---------- Paso 4: generar picks para los proximos partidos ----------

def generar_picks(partidos, fuerzas, prom_l, prom_v, rho, umbral_seguro=0.75,
                   fuerzas_corners=None, prom_l_corners=None, prom_v_corners=None, corners_combinable=False,
                   fuerzas_tarjetas=None, factores_arbitro=None, prom_l_tarjetas=None, prom_v_tarjetas=None, tarjetas_combinable=False,
                   fuerzas_tiros=None, prom_l_tiros=None, prom_v_tiros=None, tiros_combinable=False):
    programados = [p for p in partidos if p["status"] in ("SCHEDULED", "TIMED")]
    picks = []

    if not programados:
        return pd.DataFrame(picks)

    # Usamos el numero de jornada REAL que trae football-data.org (campo
    # "matchday") en vez de adivinar por fechas. Esto agrupa correctamente
    # incluso partidos reprogramados entre semana que pertenecen a la misma
    # jornada, sin importar que tan separados esten en el calendario.
    jornadas = [p.get("matchday") for p in programados if p.get("matchday") is not None]
    if jornadas:
        proxima_jornada = min(jornadas)
        sin_jornada = len([p for p in programados if p.get("matchday") is None])
        print(f"DIAGNOSTICO: jornadas detectadas en los partidos programados: {sorted(set(jornadas))}")
        print(f"DIAGNOSTICO: se eligio la jornada {proxima_jornada} como la proxima a mostrar")
        if sin_jornada:
            print(f"DIAGNOSTICO: aviso -- {sin_jornada} partidos programados NO traen numero de jornada y quedaron excluidos")
        programados = [p for p in programados if p.get("matchday") == proxima_jornada]
    else:
        print("DIAGNOSTICO: NINGUN partido programado trae el campo 'matchday' -- revisar la respuesta de la API")
    # Si por alguna razon la API no trae "matchday" en algun partido, ese
    # partido simplemente no se incluye en este lote (se recogera solo
    # cuando si tenga el dato, en vez de arriesgarnos a mezclar jornadas).

    for p in programados:
        fecha_partido = pd.to_datetime(p["utcDate"]).tz_localize(None)
        local = MAPEO_NOMBRES.get(p["homeTeam"]["name"], p["homeTeam"]["name"])
        visitante = MAPEO_NOMBRES.get(p["awayTeam"]["name"], p["awayTeam"]["name"])

        matriz, lam, mu = matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho)
        if matriz is None:
            continue
        mercados_sin_calibrar = calcular_mercados(matriz)

        mercados_corners = {}
        if fuerzas_corners:
            mercados_corners = calcular_mercados_corners(local, visitante, fuerzas_corners,
                                                           prom_l_corners, prom_v_corners)

        mercados_tarjetas = {}
        if fuerzas_tarjetas:
            arbitro_partido = obtener_arbitro_partido(p)  # None si no esta asignado todavia
            # Decision del CEO: el mercado de tarjetas SOLO se usa cuando el
            # arbitro esta confirmado Y reconocido en nuestro historial.
            # Si no hay arbitro asignado, o su nombre no coincide con ninguno
            # de los que ya conocemos, este mercado queda descartado por
            # completo para ese partido (no se usa un valor "promedio").
            if arbitro_partido and arbitro_partido in (factores_arbitro or {}):
                mercados_tarjetas = calcular_mercados_tarjetas(
                    local, visitante, fuerzas_tarjetas, factores_arbitro,
                    prom_l_tarjetas, prom_v_tarjetas, arbitro=arbitro_partido)

        mercados_tiros = {}
        if fuerzas_tiros:
            mercados_tiros = calcular_mercados_tiros(local, visitante, fuerzas_tiros, prom_l_tiros, prom_v_tiros)

        # Version calibrada de TODOS los mercados, solo para mostrar en el
        # detalle desplegable "ver todos los mercados" -- los valores SIN
        # calibrar (arriba) son los que entran a elegir_mejor_pick, que ya
        # calibra internamente antes de decidir (evita calibrar dos veces)
        mercados = {k: calibrar_probabilidad(v) for k, v in mercados_sin_calibrar.items()}
        mercados_corners_mostrar = {k: calibrar_probabilidad(v) for k, v in mercados_corners.items()}
        mercados_tarjetas_mostrar = {k: calibrar_probabilidad(v) for k, v in mercados_tarjetas.items()}
        mercados_tiros_mostrar = {k: calibrar_probabilidad(v) for k, v in mercados_tiros.items()}

        mercados_extra_todos = {**mercados_corners, **mercados_tarjetas, **mercados_tiros}
        mercados_extra_combinables = {}
        if corners_combinable:
            mercados_extra_combinables.update(mercados_corners)
        if tarjetas_combinable:
            mercados_extra_combinables.update(mercados_tarjetas)
        if tiros_combinable:
            mercados_extra_combinables.update(mercados_tiros)

        nombres_pick, pick_prob, pick_cuota, cumple_umbral = elegir_mejor_pick(
            matriz, umbral_seguro, mercados_extra=mercados_extra_todos, mercados_extra_combinables=mercados_extra_combinables)
        es_combo = len(nombres_pick) > 1

        picks.append({
            "fecha": fecha_partido, "local": local, "visitante": visitante,
            "goles_esperados_local": round(lam, 2), "goles_esperados_visitante": round(mu, 2),
            "pick_recomendado": " + ".join(nombres_pick),
            "es_combo": es_combo,
            "pick_probabilidad": round(pick_prob*100, 1),
            "pick_cuota_aprox": round(pick_cuota, 2) if pick_cuota else None,
            "pick_es_seguro": cumple_umbral,
            **{k: round(v*100, 1) for k, v in mercados.items()},
            **{k: round(v*100, 1) for k, v in mercados_corners_mostrar.items()},
            **{k: round(v*100, 1) for k, v in mercados_tarjetas_mostrar.items()},
            **{k: round(v*100, 1) for k, v in mercados_tiros_mostrar.items()},
        })

    return pd.DataFrame(picks)

# ---------- Programa principal ----------

# ---------- Herramienta: verificar correlacion real entre goles y corners ----------

def verificar_correlacion_goles_metrica(df, columna_local, columna_visitante, linea_goles=1.5, linea_metrica=10.5, nombre_metrica="metrica"):
    """
    Version generica de la verificacion de correlacion: sirve para corners,
    tarjetas, o cualquier otra metrica nueva que se agregue despues.
    """
    df = df.dropna(subset=[columna_local, columna_visitante, "FTHG", "FTAG"])
    if len(df) < 50:
        print(f"No hay suficientes partidos con {nombre_metrica} para medir la correlacion todavia.")
        return None

    goles_total = df["FTHG"] + df["FTAG"]
    metrica_total = df[columna_local] + df[columna_visitante]

    over_goles = goles_total > linea_goles
    under_metrica = metrica_total < linea_metrica

    p_a = over_goles.mean()
    p_b = under_metrica.mean()
    p_conjunta_real = (over_goles & under_metrica).mean()
    p_conjunta_si_independientes = p_a * p_b
    diferencia = p_conjunta_real - p_conjunta_si_independientes
    correlacion = goles_total.corr(metrica_total)

    print(f"[{nombre_metrica}] Diferencia real vs independiente: {diferencia*100:+.1f} pp | Correlacion: {correlacion:.3f}")
    independientes = abs(diferencia) < 0.03
    print(f"[{nombre_metrica}] ¿Se puede combinar con goles? {'SI' if independientes else 'NO'}")
    return independientes

def correr_pipeline_liga(liga_key):
    """Corre el pipeline completo (datos, modelo, picks, combinadas, Supabase)
    para UNA liga especifica. Reasigna las variables globales dependientes
    de la liga (archivos, mapeo de nombres) antes de correr la logica ya
    existente, que no necesita saber que hay mas de una liga."""
    global ARCHIVO_HISTORICO, MAPEO_NOMBRES, EQUIPOS_SIN_HISTORIAL
    global ARCHIVO_PICKS, ARCHIVO_COMBINADAS
    global ARCHIVO_HISTORIAL_PICKS, ARCHIVO_HISTORIAL_COMBINADAS, ARCHIVO_CONTADOR_FECHAS

    config = LIGAS[liga_key]
    print(f"\n{'#'*70}\n# LIGA: {config['nombre_mostrar']}\n{'#'*70}")

    ARCHIVO_HISTORICO = config["archivo_historico"]
    MAPEO_NOMBRES = config["mapeo_nombres"]
    EQUIPOS_SIN_HISTORIAL = config["equipos_sin_historial"]
    ARCHIVO_PICKS = f"picks_del_dia_{liga_key}.csv"
    ARCHIVO_COMBINADAS = f"combinadas_del_dia_{liga_key}.json"
    ARCHIVO_HISTORIAL_PICKS = f"historial_picks_{liga_key}.csv"
    ARCHIVO_HISTORIAL_COMBINADAS = f"historial_combinadas_{liga_key}.csv"
    ARCHIVO_CONTADOR_FECHAS = f"contador_fechas_{liga_key}.json"

    print("Descargando datos de football-data.org...")
    partidos = obtener_partidos_temporada(config["codigo_api"])

    print("Actualizando historico con partidos ya jugados...")
    historico = actualizar_historico(partidos)

    if historico is None or len(historico) == 0:
        print("No hay historico disponible todavia para esta liga.")
        return

    historico["Date"] = pd.to_datetime(historico["Date"])

    print("Actualizando corners/tarjetas desde football-data.co.uk...")
    historico = actualizar_estadisticas_extra(historico, config["codigo_footballdata"])

    print("Calculando fuerzas de equipos...")
    fuerzas, prom_l, prom_v = calcular_fuerzas(historico)

    print("Calculando fuerzas de corners (si hay datos disponibles)...")
    fuerzas_corners, prom_l_corners, prom_v_corners = calcular_fuerzas_corners(historico)
    corners_combinable = False
    if fuerzas_corners:
        print(f"  Corners disponibles para {len(fuerzas_corners)} equipos.")
        print("  Verificando si es seguro combinar goles+corners con datos reales...")
        corners_combinable = bool(verificar_correlacion_goles_metrica(
            historico, "HC", "AC", nombre_metrica="corners"))
    else:
        print("  Sin datos de corners todavia (se activara solo cuando esten disponibles).")

    print("Calculando fuerzas de tarjetas (si hay datos disponibles)...")
    fuerzas_tarjetas, factores_arbitro, prom_l_tarjetas, prom_v_tarjetas = calcular_fuerzas_tarjetas(historico)
    tarjetas_combinable = False
    if fuerzas_tarjetas:
        print(f"  Tarjetas disponibles para {len(fuerzas_tarjetas)} equipos, "
              f"{len(factores_arbitro)} arbitros con historial suficiente.")
        print("  Verificando si es seguro combinar goles+tarjetas con datos reales...")
        tarjetas_combinable = bool(verificar_correlacion_goles_metrica(
            historico, "HY", "AY", linea_metrica=3.5, nombre_metrica="tarjetas"))
    else:
        print("  Sin datos de tarjetas todavia (se activara solo cuando esten disponibles).")

    print("Calculando fuerzas de tiros a puerta (si hay datos disponibles)...")
    fuerzas_tiros, prom_l_tiros, prom_v_tiros = calcular_fuerzas_tiros(historico)
    tiros_combinable = False
    if fuerzas_tiros:
        print(f"  Tiros a puerta disponibles para {len(fuerzas_tiros)} equipos.")
        print("  Verificando si es seguro combinar goles+tiros a puerta con datos reales...")
        tiros_combinable = bool(verificar_correlacion_goles_metrica(
            historico, "HST", "AST", linea_metrica=8.5, nombre_metrica="tiros a puerta"))
    else:
        print("  Sin datos de tiros a puerta todavia (se activara solo cuando esten disponibles).")

    print("Ajustando Dixon-Coles...")
    rho = ajustar_rho(historico, fuerzas, prom_l, prom_v)
    print(f"Rho: {rho:.3f}")

    print("Actualizando el registro de historial (track record)...")
    historial = cargar_historial_picks()
    historial = verificar_picks_resueltos(historial, historico)

    umbral_dinamico = calcular_umbral_dinamico(historial, umbral_base=0.80, umbral_alto=0.85)

    print(f"\nGenerando picks de los proximos dias (umbral: {umbral_dinamico*100:.0f}%)...")
    picks = generar_picks(partidos, fuerzas, prom_l, prom_v, rho, umbral_seguro=umbral_dinamico,
                           fuerzas_corners=fuerzas_corners, prom_l_corners=prom_l_corners, prom_v_corners=prom_v_corners,
                           corners_combinable=corners_combinable,
                           fuerzas_tarjetas=fuerzas_tarjetas, factores_arbitro=factores_arbitro,
                           prom_l_tarjetas=prom_l_tarjetas, prom_v_tarjetas=prom_v_tarjetas,
                           tarjetas_combinable=tarjetas_combinable,
                           fuerzas_tiros=fuerzas_tiros, prom_l_tiros=prom_l_tiros, prom_v_tiros=prom_v_tiros,
                           tiros_combinable=tiros_combinable)

    if len(picks) == 0:
        print("No hay partidos programados en los proximos dias para esta liga.")
        return

    picks.to_csv(ARCHIVO_PICKS, index=False)
    print(f"\n{len(picks)} picks guardados en '{ARCHIVO_PICKS}'\n")
    print("=== PICKS RECOMENDADOS (mercado mas seguro por partido) ===")
    print(picks[["fecha", "local", "visitante", "pick_recomendado", "es_combo",
                  "pick_probabilidad", "pick_cuota_aprox", "pick_es_seguro"]].to_string(index=False))

    historial = registrar_picks_nuevos(picks, historial)

    historial_a_guardar = historial.copy()
    historial_a_guardar["fecha_partido"] = pd.to_datetime(historial_a_guardar["fecha_partido"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    historial_a_guardar.to_csv(ARCHIVO_HISTORIAL_PICKS, index=False)

    resumen_track_record(historial)
    verificar_calibracion_continua(historial)

    combinadas = calcular_combinadas_multiples(picks, cuota_objetivo=1.70, max_combinadas=3, max_partidos_por_combinada=3)
    with open(ARCHIVO_COMBINADAS, "w", encoding="utf-8") as f:
        json.dump(combinadas, f, ensure_ascii=False, indent=2, default=str)
    print(f"Combinadas guardadas en '{ARCHIVO_COMBINADAS}'")

    print("\nActualizando historial de combinadas por fecha...")
    historial_combinadas = cargar_historial_combinadas()
    historial_combinadas = registrar_combinadas_historial(combinadas, picks, historial_combinadas)
    historial_combinadas = verificar_combinadas_resueltas(historial_combinadas, historico)
    historial_combinadas.to_csv(ARCHIVO_HISTORIAL_COMBINADAS, index=False)

    resueltas = historial_combinadas[historial_combinadas["resultado"].notna()]
    if len(resueltas) > 0:
        cumplidas = (resueltas["resultado"] == "Cumplida").sum()
        print(f"Historial de combinadas: {cumplidas}/{len(resueltas)} cumplidas ({cumplidas/len(resueltas)*100:.1f}%)")

    print("\nSincronizando con Supabase...")
    subir_picks_supabase(picks, liga=liga_key, n_gratis=3)
    subir_combinadas_supabase(combinadas, liga=liga_key)
    subir_historial_combinadas_supabase(historial_combinadas, liga=liga_key)


if __name__ == "__main__":
    for liga_key in LIGAS_ACTIVAS:
        try:
            correr_pipeline_liga(liga_key)
        except Exception as e:
            print(f"\nERROR corriendo la liga '{liga_key}': {e}")
            print("Continuando con la siguiente liga...")