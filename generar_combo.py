"""
Genera picks tipo "Bet Builder": combina varias condiciones de un mismo
partido en un solo pick, calculando la probabilidad conjunta real
(no una multiplicacion ingenua) y la cuota aproximada resultante.
"""
import pandas as pd
import numpy as np
from scipy.stats import poisson

MAX_GOLES = 6
ARCHIVO_DATOS = "premier_league_combinado.csv"

# ---------- (mismas funciones del modelo que ya conoces) ----------

def calcular_fuerzas(df):
    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df = df.copy(); df["peso"] = peso
    prom_local = (df["FTHG"]*df["peso"]).sum()/df["peso"].sum()
    prom_visit = (df["FTAG"]*df["peso"]).sum()/df["peso"].sum()
    equipos = pd.unique(df[["HomeTeam","AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df[df["HomeTeam"]==equipo]; pv = df[df["AwayTeam"]==equipo]
        if pl["peso"].sum()==0 or pv["peso"].sum()==0: continue
        fuerzas[equipo] = {
            "ataque_local": (pl["FTHG"]*pl["peso"]).sum()/pl["peso"].sum()/prom_local,
            "defensa_local": (pl["FTAG"]*pl["peso"]).sum()/pl["peso"].sum()/prom_visit,
            "ataque_visitante": (pv["FTAG"]*pv["peso"]).sum()/pv["peso"].sum()/prom_visit,
            "defensa_visitante": (pv["FTHG"]*pv["peso"]).sum()/pv["peso"].sum()/prom_local,
        }
    return fuerzas, prom_local, prom_visit

def tau_dixon_coles(x, y, lam, mu, rho):
    if x==0 and y==0: return 1 - lam*mu*rho
    elif x==0 and y==1: return 1 + lam*rho
    elif x==1 and y==0: return 1 + mu*rho
    elif x==1 and y==1: return 1 - rho
    else: return 1

def matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho):
    if local not in fuerzas or visitante not in fuerzas: return None
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam = prom_l * fl["ataque_local"] * fv["defensa_visitante"]
    mu = prom_v * fv["ataque_visitante"] * fl["defensa_local"]
    matriz = np.zeros((MAX_GOLES+1, MAX_GOLES+1))
    for i in range(MAX_GOLES+1):
        for j in range(MAX_GOLES+1):
            tau = tau_dixon_coles(min(i,1), min(j,1), lam, mu, rho)
            matriz[i][j] = max(tau,0) * poisson.pmf(i,lam) * poisson.pmf(j,mu)
    return matriz / matriz.sum()

# ---------- Condiciones disponibles para armar el combo ----------
# Cada condicion es una funcion que recibe (goles_local, goles_visitante) y devuelve True/False

CONDICIONES = {
    "over_1.5": lambda i, j: (i + j) > 1.5,
    "over_2.5": lambda i, j: (i + j) > 2.5,
    "under_2.5": lambda i, j: (i + j) < 2.5,
    "btts_si": lambda i, j: i >= 1 and j >= 1,
    "btts_no": lambda i, j: not (i >= 1 and j >= 1),
    "local_gana": lambda i, j: i > j,
    "empate": lambda i, j: i == j,
    "visitante_gana": lambda i, j: i < j,
    "doble_op_1X": lambda i, j: i >= j,
    "doble_op_X2": lambda i, j: i <= j,
}

def calcular_combo(matriz, lista_condiciones):
    """Suma las celdas de la matriz que cumplen TODAS las condiciones a la vez."""
    n = matriz.shape[0]
    prob = sum(
        matriz[i][j]
        for i in range(n) for j in range(n)
        if all(CONDICIONES[c](i, j) for c in lista_condiciones)
    )
    return prob

def nivel_riesgo(cuota):
    if cuota < 1.5: return "Muy seguro"
    elif cuota < 2.0: return "Seguro"
    elif cuota < 3.0: return "Moderado"
    elif cuota < 5.0: return "Arriesgado"
    else: return "Muy arriesgado"

def generar_pick_combo(local, visitante, condiciones, fuerzas, prom_l, prom_v, rho, margen_casa=0.0):
    matriz = matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho)
    if matriz is None:
        print("No hay suficiente historial para uno de los equipos.")
        return

    prob = calcular_combo(matriz, condiciones)
    if prob <= 0:
        print("Esta combinacion es prácticamente imposible segun el modelo.")
        return

    cuota_justa = 1 / prob
    cuota_con_margen = cuota_justa * (1 - margen_casa)  # simula el margen de una casa de apuestas

    print(f"\n{'='*45}")
    print(f"BET BUILDER: {local} vs {visitante}")
    print(f"{'='*45}")
    for c in condiciones:
        print(f"  + {c}")
    print(f"\nProbabilidad combinada real: {prob*100:.1f}%")
    print(f"Cuota aproximada (justa): {cuota_justa:.2f}")
    if margen_casa > 0:
        print(f"Cuota estimada con margen de casa: {cuota_con_margen:.2f}")
    print(f"Nivel de riesgo: {nivel_riesgo(cuota_justa)}")

def buscar_pick_seguro(local, visitante, fuerzas, prom_l, prom_v, rho, umbral_minimo=0.65):
    """
    Revisa todos los mercados individuales de un partido y devuelve
    los que superan el umbral de probabilidad, ordenados del mas seguro al menos.
    """
    matriz = matriz_marcadores(local, visitante, fuerzas, prom_l, prom_v, rho)
    if matriz is None:
        print("No hay suficiente historial para uno de los equipos.")
        return []

    resultados = []
    for nombre_mercado, condicion in CONDICIONES.items():
        prob = calcular_combo(matriz, [nombre_mercado])
        if prob >= umbral_minimo:
            cuota = 1 / prob
            resultados.append((nombre_mercado, prob, cuota))

    resultados.sort(key=lambda x: x[1], reverse=True)  # mas seguro primero

    print(f"\n{'='*45}")
    print(f"PICKS SEGUROS: {local} vs {visitante} (umbral: {umbral_minimo*100:.0f}%)")
    print(f"{'='*45}")
    if not resultados:
        print("  Ningun mercado supera el umbral en este partido.")
    for nombre, prob, cuota in resultados:
        print(f"  {nombre:20s}  {prob*100:5.1f}%   cuota ~{cuota:.2f}   ({nivel_riesgo(cuota)})")

    return resultados

if __name__ == "__main__":
    df = pd.read_csv(ARCHIVO_DATOS)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    fuerzas, prom_l, prom_v = calcular_fuerzas(df)
    rho = -0.14  # ya lo tenemos ajustado de antes; evitamos recalcularlo aqui para que sea rapido

    # Ejemplo: arma tu propio combo eligiendo condiciones de la lista CONDICIONES
    generar_pick_combo(
        "Arsenal", "Man City",
        condiciones=["over_1.5", "btts_si", "doble_op_1X"],
        fuerzas=fuerzas, prom_l=prom_l, prom_v=prom_v, rho=rho
    )

    # Ejemplo: buscar automaticamente los mercados mas seguros de este partido
    buscar_pick_seguro("Arsenal", "Man City", fuerzas, prom_l, prom_v, rho, umbral_minimo=0.65)