"""
MODELO FINAL - LigaPro Picks / Premier League
Combina: fuerzas de equipo ponderadas por recencia + Poisson + correccion Dixon-Coles.
Genera los 5 mercados: 1X2, Doble oportunidad, BTTS, Over/Under 2.5, Handicap asiatico.

Este es el script que se usara en produccion (con el pipeline automatico que
se construye mas adelante) para generar los picks del dia.
"""
import pandas as pd
import numpy as np
from scipy.stats import poisson

MAX_GOLES = 6
ARCHIVO_DATOS = "premier_league_combinado.csv"

# ---------- Fuerzas de equipo (ataque / defensa) ----------

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
    return fuerzas, prom_local, prom_visit

def goles_esperados(local, visitante, fuerzas, prom_local, prom_visit):
    if local not in fuerzas or visitante not in fuerzas:
        return None
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam_l = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    lam_v = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    return lam_l, lam_v

# ---------- Correccion Dixon-Coles ----------

def tau_dixon_coles(x, y, lam, mu, rho):
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    elif x == 0 and y == 1:
        return 1 + lam * rho
    elif x == 1 and y == 0:
        return 1 + mu * rho
    elif x == 1 and y == 1:
        return 1 - rho
    else:
        return 1

def ajustar_rho(df, fuerzas, prom_l, prom_v):
    mejor_rho, mejor_verosim = 0, -np.inf
    for rho in np.arange(-0.30, 0.11, 0.01):
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

# ---------- Matriz de marcadores y mercados ----------

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
    p_over_25 = sum(matriz[i][j] for i in range(n) for j in range(n) if i + j > 2)
    p_under_25 = 1 - p_over_25

    p_handicap_local = p_local / (p_local + p_visit)  # gana sin contar empate

    return {
        "1X2_local": p_local, "1X2_empate": p_empate, "1X2_visitante": p_visit,
        "doble_oportunidad_1X": p_local + p_empate,
        "doble_oportunidad_X2": p_visit + p_empate,
        "btts_si": p_btts_si, "btts_no": 1 - p_btts_si,
        "over_2.5": p_over_25, "under_2.5": p_under_25,
        "handicap_asiatico_local_-0.5": p_handicap_local,
        "handicap_asiatico_visitante_+0.5": 1 - p_handicap_local,
    }

def generar_pick(local, visitante, fuerzas, prom_l, prom_v, rho):
    matriz, lam, mu = matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho)
    if matriz is None:
        print(f"No hay suficiente historial para {local} o {visitante}.")
        return
    mercados = calcular_mercados(matriz)

    print(f"\n{'='*50}")
    print(f"{local} vs {visitante}")
    print(f"Goles esperados: {lam:.2f} - {mu:.2f}")
    print(f"{'='*50}")
    print(f"1X2:")
    print(f"  {local} gana:        {mercados['1X2_local']*100:.1f}%")
    print(f"  Empate:              {mercados['1X2_empate']*100:.1f}%")
    print(f"  {visitante} gana:    {mercados['1X2_visitante']*100:.1f}%")
    print(f"Doble oportunidad:")
    print(f"  1X: {mercados['doble_oportunidad_1X']*100:.1f}%   X2: {mercados['doble_oportunidad_X2']*100:.1f}%")
    print(f"Ambos anotan (BTTS):")
    print(f"  Si: {mercados['btts_si']*100:.1f}%   No: {mercados['btts_no']*100:.1f}%")
    print(f"Total de goles:")
    print(f"  Over 2.5: {mercados['over_2.5']*100:.1f}%   Under 2.5: {mercados['under_2.5']*100:.1f}%")
    print(f"Handicap asiatico (gana sin empate):")
    print(f"  {local} -0.5: {mercados['handicap_asiatico_local_-0.5']*100:.1f}%")
    print(f"  {visitante} +0.5: {mercados['handicap_asiatico_visitante_+0.5']*100:.1f}%")

# ---------- Programa principal ----------

if __name__ == "__main__":
    df = pd.read_csv(ARCHIVO_DATOS)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    print("Calculando fuerzas de equipos...")
    fuerzas, prom_l, prom_v = calcular_fuerzas(df)

    print("Ajustando parametro Dixon-Coles (rho)... esto puede tardar unos minutos")
    rho = ajustar_rho(df, fuerzas, prom_l, prom_v)
    print(f"Rho ajustado: {rho:.3f}")

    # -------------------------------------------------------
    # Cambia aqui los partidos que quieras predecir.
    # Los nombres deben coincidir EXACTAMENTE con los del CSV.
    # -------------------------------------------------------
    partidos_a_predecir = [
        ("Arsenal", "Man City"),
        ("Liverpool", "Chelsea"),
    ]

    for local, visitante in partidos_a_predecir:
        generar_pick(local, visitante, fuerzas, prom_l, prom_v, rho)