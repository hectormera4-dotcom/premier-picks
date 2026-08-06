"""
Backtesting: valida el modelo prediciendo partidos pasados
usando SOLO datos anteriores a cada partido (sin trampa, sin ver el futuro).
"""
import pandas as pd
from scipy.stats import poisson

MAX_GOLES = 6

def calcular_fuerzas(df_entrenamiento):
    fecha_max = df_entrenamiento["Date"].max()
    dias_desde = (fecha_max - df_entrenamiento["Date"]).dt.days
    peso = 0.5 ** (dias_desde / 365)
    df_entrenamiento = df_entrenamiento.copy()
    df_entrenamiento["peso"] = peso

    prom_local = (df_entrenamiento["FTHG"] * df_entrenamiento["peso"]).sum() / df_entrenamiento["peso"].sum()
    prom_visit = (df_entrenamiento["FTAG"] * df_entrenamiento["peso"]).sum() / df_entrenamiento["peso"].sum()

    equipos = pd.unique(df_entrenamiento[["HomeTeam", "AwayTeam"]].values.ravel())
    fuerzas = {}
    for equipo in equipos:
        pl = df_entrenamiento[df_entrenamiento["HomeTeam"] == equipo]
        pv = df_entrenamiento[df_entrenamiento["AwayTeam"] == equipo]
        if pl["peso"].sum() == 0 or pv["peso"].sum() == 0:
            continue
        fuerzas[equipo] = {
            "ataque_local": (pl["FTHG"]*pl["peso"]).sum()/pl["peso"].sum() / prom_local,
            "defensa_local": (pl["FTAG"]*pl["peso"]).sum()/pl["peso"].sum() / prom_visit,
            "ataque_visitante": (pv["FTAG"]*pv["peso"]).sum()/pv["peso"].sum() / prom_visit,
            "defensa_visitante": (pv["FTHG"]*pv["peso"]).sum()/pv["peso"].sum() / prom_local,
        }
    return fuerzas, prom_local, prom_visit

def predecir_1x2(local, visitante, fuerzas, prom_local, prom_visit):
    if local not in fuerzas or visitante not in fuerzas:
        return None
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam_l = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    lam_v = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    p_l = p_e = p_v = 0
    for i in range(MAX_GOLES+1):
        for j in range(MAX_GOLES+1):
            p = poisson.pmf(i, lam_l) * poisson.pmf(j, lam_v)
            if i > j: p_l += p
            elif i == j: p_e += p
            else: p_v += p
    return p_l, p_e, p_v

def main():
    df = pd.read_csv("premier_league_combinado.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    # Usamos la temporada mas reciente completa como conjunto de prueba
    fecha_corte = df["Date"].max() - pd.Timedelta(days=365)
    entrenamiento_inicial = df[df["Date"] < fecha_corte]
    prueba = df[df["Date"] >= fecha_corte]

    print(f"Partidos de entrenamiento inicial: {len(entrenamiento_inicial)}")
    print(f"Partidos a predecir (backtest): {len(prueba)}\n")

    brier_scores = []
    aciertos = 0
    total_evaluado = 0

    for idx, partido in prueba.iterrows():
        # Solo usamos partidos ANTERIORES a este para entrenar (sin ver el futuro)
        datos_hasta_ahora = df[df["Date"] < partido["Date"]]
        fuerzas, prom_l, prom_v = calcular_fuerzas(datos_hasta_ahora)

        resultado = predecir_1x2(partido["HomeTeam"], partido["AwayTeam"], fuerzas, prom_l, prom_v)
        if resultado is None:
            continue  # equipo sin suficiente historial todavia

        p_l, p_e, p_v = resultado
        real = partido["FTR"]  # 'H', 'D', 'A'
        real_vector = [1 if real=="H" else 0, 1 if real=="D" else 0, 1 if real=="A" else 0]
        pred_vector = [p_l, p_e, p_v]

        brier = sum((pv - rv)**2 for pv, rv in zip(pred_vector, real_vector))
        brier_scores.append(brier)

        pick = max([("H", p_l), ("D", p_e), ("A", p_v)], key=lambda x: x[1])[0]
        if pick == real:
            aciertos += 1
        total_evaluado += 1

    print(f"Partidos evaluados: {total_evaluado}")
    print(f"Aciertos (pick con mayor probabilidad vs resultado real): {aciertos} ({aciertos/total_evaluado*100:.1f}%)")
    print(f"Brier score promedio: {sum(brier_scores)/len(brier_scores):.4f}")
    print("(Brier score: mientras mas bajo, mejor calibrado esta el modelo. 0 = perfecto, 0.667 = adivinar al azar)")

if __name__ == "__main__":
    main()