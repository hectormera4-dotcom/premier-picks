"""
Modelo de goles esperados (Poisson) para generar picks de:
1X2, BTTS, Over/Under goles, y Hándicap asiático.
"""
import pandas as pd
from scipy.stats import poisson

MAX_GOLES = 6  # hasta cuantos goles simulamos por equipo (6-0 ya es un caso extremo)

def cargar_fuerzas():
    df = pd.read_csv("premier_league_combinado.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    # Peso por recencia: partidos mas recientes pesan mas (vida media de 1 año)
    fecha_max = df["Date"].max()
    dias_desde = (fecha_max - df["Date"]).dt.days
    df["peso"] = 0.5 ** (dias_desde / 365)

    # Promedios de liga (ponderados)
    promedio_goles_local = (df["FTHG"] * df["peso"]).sum() / df["peso"].sum()
    promedio_goles_visitante = (df["FTAG"] * df["peso"]).sum() / df["peso"].sum()

    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}

    for equipo in equipos:
        # Como local: ataque y defensa
        partidos_local = df[df["HomeTeam"] == equipo]
        goles_anotados_local = (partidos_local["FTHG"] * partidos_local["peso"]).sum() / partidos_local["peso"].sum()
        goles_recibidos_local = (partidos_local["FTAG"] * partidos_local["peso"]).sum() / partidos_local["peso"].sum()

        # Como visitante: ataque y defensa
        partidos_visitante = df[df["AwayTeam"] == equipo]
        goles_anotados_visitante = (partidos_visitante["FTAG"] * partidos_visitante["peso"]).sum() / partidos_visitante["peso"].sum()
        goles_recibidos_visitante = (partidos_visitante["FTHG"] * partidos_visitante["peso"]).sum() / partidos_visitante["peso"].sum()

        fuerzas[equipo] = {
            "ataque_local": goles_anotados_local / promedio_goles_local,
            "defensa_local": goles_recibidos_local / promedio_goles_visitante,
            "ataque_visitante": goles_anotados_visitante / promedio_goles_visitante,
            "defensa_visitante": goles_recibidos_visitante / promedio_goles_local,
        }

    return fuerzas, promedio_goles_local, promedio_goles_visitante

def predecir_mercados(local, visitante, fuerzas, prom_local, prom_visitante):
    f_local = fuerzas[local]
    f_visit = fuerzas[visitante]

    # Goles esperados para este partido especifico
    lambda_local = prom_local * f_local["ataque_local"] * f_visit["defensa_visitante"]
    lambda_visit = prom_visitante * f_visit["ataque_visitante"] * f_local["defensa_local"]

    # Matriz de probabilidades de marcador (0-0, 1-0, 0-1, etc.)
    matriz = [[poisson.pmf(i, lambda_local) * poisson.pmf(j, lambda_visit)
               for j in range(MAX_GOLES+1)] for i in range(MAX_GOLES+1)]

    p_local_gana = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i > j)
    p_empate     = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i == j)
    p_visit_gana = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i < j)

    p_btts_si = sum(matriz[i][j] for i in range(1, MAX_GOLES+1) for j in range(1, MAX_GOLES+1))
    p_over_25 = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i+j > 2)
    p_under_25 = 1 - p_over_25

    print(f"\n{local} vs {visitante}")
    print(f"  Goles esperados: {local} {lambda_local:.2f} - {lambda_visit:.2f} {visitante}\n")
    print(f"  1X2:")
    print(f"    {local} gana:  {p_local_gana*100:.1f}%")
    print(f"    Empate:        {p_empate*100:.1f}%")
    print(f"    {visitante} gana: {p_visit_gana*100:.1f}%")
    print(f"  Doble oportunidad 1X: {(p_local_gana+p_empate)*100:.1f}%")
    print(f"  Doble oportunidad X2: {(p_visit_gana+p_empate)*100:.1f}%")
    print(f"  Ambos anotan (BTTS - Si): {p_btts_si*100:.1f}%")
    print(f"  Over 2.5 goles:  {p_over_25*100:.1f}%")
    print(f"  Under 2.5 goles: {p_under_25*100:.1f}%")
    print(f"  Hándicap asiático (gana sin empate) {local}: {(p_local_gana/(p_local_gana+p_visit_gana))*100:.1f}%")

if __name__ == "__main__":
    fuerzas, prom_local, prom_visitante = cargar_fuerzas()
    predecir_mercados("Arsenal", "Aston Villa", fuerzas, prom_local, prom_visitante)