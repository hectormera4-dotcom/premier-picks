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
import pandas as pd
import numpy as np
from scipy.stats import poisson
from datetime import datetime, timedelta
import os

API_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "TU_TOKEN_AQUI")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_TOKEN}
TEMPORADA_ACTUAL = 2026
ARCHIVO_HISTORICO = "premier_league_combinado.csv"
ARCHIVO_PICKS = "picks_del_dia.csv"
MAX_GOLES = 6

# Traductor de nombres: football-data.org (izquierda) -> football-data.co.uk (derecha)
MAPEO_NOMBRES = {
    "AFC Bournemouth": "Bournemouth",
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton",
    "Chelsea FC": "Chelsea",
    "Coventry City FC": "Coventry",       # equipo nuevo, sin historial
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Hull City AFC": "Hull",              # equipo nuevo, sin historial
    "Ipswich Town FC": "Ipswich",
    "Leeds United FC": "Leeds",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Man City",
    "Manchester United FC": "Man United",
    "Newcastle United FC": "Newcastle",
    "Nottingham Forest FC": "Nott'm Forest",
    "Sunderland AFC": "Sunderland",
    "Tottenham Hotspur FC": "Tottenham",
}

EQUIPOS_SIN_HISTORIAL = ["Coventry", "Hull"]

# ---------- Paso 1: traer datos de football-data.org ----------

def obtener_partidos_temporada():
    # No mandamos el parametro 'season': la API usa la temporada actual por
    # defecto, y el plan gratuito de todas formas solo da acceso a esa.
    # Mandar season=YYYY explicito puede causar error 400 si el sistema
    # todavia no tiene esa temporada completamente registrada.
    resp = requests.get(
        f"{BASE_URL}/competitions/PL/matches",
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

def elegir_mejor_pick(matriz, umbral_minimo=0.65):
    """
    Evalua todos los mercados individuales y todas las combinaciones validas
    de 2 mercados (de categorias distintas). De las que superan el umbral de
    seguridad, elige la de MEJOR CUOTA (menor probabilidad, mayor pago) --
    es decir, la combinacion mas rentable que sigue siendo "segura".
    Si ninguna supera el umbral, devuelve la de mayor probabilidad disponible.
    """
    candidatos = []

    # Mercados individuales
    for nombre, cond in CONDICIONES.items():
        prob = calcular_combo(matriz, [nombre])
        candidatos.append(([nombre], prob))

    # Combos de 2 mercados de categorias distintas
    nombres = list(CONDICIONES.keys())
    for i in range(len(nombres)):
        for j in range(i+1, len(nombres)):
            n1, n2 = nombres[i], nombres[j]
            if CATEGORIAS[n1] == CATEGORIAS[n2]:
                continue  # misma categoria, se descarta (redundante o contradictorio)
            prob = calcular_combo(matriz, [n1, n2])
            candidatos.append(([n1, n2], prob))

    # Filtramos los que cumplen el umbral de seguridad
    seguros = [c for c in candidatos if c[1] >= umbral_minimo]

    if seguros:
        # De los seguros, elegimos el de MENOR probabilidad (= mejor cuota, mas rentable)
        mejor = min(seguros, key=lambda c: c[1])
        cumple_umbral = True
    else:
        # Si ninguno es "seguro", devolvemos el de mayor probabilidad disponible
        mejor = max(candidatos, key=lambda c: c[1])
        cumple_umbral = False

    nombres_pick, prob = mejor
    cuota = 1 / prob if prob > 0 else None
    return nombres_pick, prob, cuota, cumple_umbral

# ---------- Paso 4: generar picks para los proximos partidos ----------

def generar_picks(partidos, fuerzas, prom_l, prom_v, rho, dias_adelante=20, umbral_seguro=0.65):
    ahora = datetime.utcnow()
    limite = ahora + timedelta(days=dias_adelante)

    programados = [p for p in partidos if p["status"] in ("SCHEDULED", "TIMED")]
    picks = []

    for p in programados:
        fecha_partido = pd.to_datetime(p["utcDate"]).tz_localize(None)
        if fecha_partido > limite:
            continue

        local = MAPEO_NOMBRES.get(p["homeTeam"]["name"], p["homeTeam"]["name"])
        visitante = MAPEO_NOMBRES.get(p["awayTeam"]["name"], p["awayTeam"]["name"])

        matriz, lam, mu = matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho)
        if matriz is None:
            continue
        mercados = calcular_mercados(matriz)
        nombres_pick, pick_prob, pick_cuota, cumple_umbral = elegir_mejor_pick(matriz, umbral_seguro)
        es_combo = len(nombres_pick) > 1

        picks.append({
            "fecha": fecha_partido, "local": local, "visitante": visitante,
            "goles_esperados_local": round(lam, 2), "goles_esperados_visitante": round(mu, 2),
            "pick_recomendado": " + ".join(nombres_pick),
            "es_combo": es_combo,
            "pick_probabilidad": round(pick_prob*100, 1),
            "pick_cuota_aprox": round(pick_cuota, 2) if pick_cuota else None,
            "pick_es_seguro": cumple_umbral,
            **{k: round(v*100, 1) for k, v in mercados.items()}
        })

    return pd.DataFrame(picks)

# ---------- Programa principal ----------

if __name__ == "__main__":
    print("Descargando datos de football-data.org...")
    partidos = obtener_partidos_temporada()

    print("Actualizando historico con partidos ya jugados...")
    historico = actualizar_historico(partidos)

    if historico is not None and len(historico) > 0:
        historico["Date"] = pd.to_datetime(historico["Date"])
        print("Calculando fuerzas de equipos...")
        fuerzas, prom_l, prom_v = calcular_fuerzas(historico)

        print("Ajustando Dixon-Coles...")
        rho = ajustar_rho(historico, fuerzas, prom_l, prom_v)
        print(f"Rho: {rho:.3f}")

        print("Generando picks de los proximos 10 dias...")
        picks = generar_picks(partidos, fuerzas, prom_l, prom_v, rho)

        if len(picks) > 0:
            picks.to_csv(ARCHIVO_PICKS, index=False)
            print(f"\n{len(picks)} picks guardados en '{ARCHIVO_PICKS}'\n")
            print("=== PICKS RECOMENDADOS (mercado mas seguro por partido) ===")
            print(picks[["fecha", "local", "visitante", "pick_recomendado", "es_combo",
                          "pick_probabilidad", "pick_cuota_aprox", "pick_es_seguro"]].to_string(index=False))
        else:
            print("No hay partidos programados en los proximos dias.")