"""
Backtest con la correccion de Dixon-Coles aplicada:
ajusta las probabilidades de marcadores bajos (0-0, 1-0, 0-1, 1-1)
que el modelo de Poisson simple suele calcular mal.
"""
import pandas as pd
import numpy as np
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

def goles_esperados(local, visitante, fuerzas, prom_local, prom_visit):
    if local not in fuerzas or visitante not in fuerzas:
        return None
    fl, fv = fuerzas[local], fuerzas[visitante]
    lam_l = prom_local * fl["ataque_local"] * fv["defensa_visitante"]
    lam_v = prom_visit * fv["ataque_visitante"] * fl["defensa_local"]
    return lam_l, lam_v

def tau_dixon_coles(x, y, lam, mu, rho):
    """Factor de correccion para marcadores bajos."""
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

def ajustar_rho(df_entrenamiento):
    """Encuentra el mejor valor de rho probando un rango de valores."""
    fuerzas, prom_l, prom_v = calcular_fuerzas(df_entrenamiento)
    mejor_rho, mejor_verosimilitud = 0, -np.inf

    for rho in np.arange(-0.30, 0.11, 0.01):
        log_verosim = 0
        for _, partido in df_entrenamiento.iterrows():
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
        if log_verosim > mejor_verosimilitud:
            mejor_verosimilitud = log_verosim
            mejor_rho = rho

    return mejor_rho

def predecir_1x2_dc(local, visitante, fuerzas, prom_l, prom_v, rho):
    resultado = goles_esperados(local, visitante, fuerzas, prom_l, prom_v)
    if resultado is None:
        return None
    lam, mu = resultado

    matriz = np.zeros((MAX_GOLES+1, MAX_GOLES+1))
    for i in range(MAX_GOLES+1):
        for j in range(MAX_GOLES+1):
            tau = tau_dixon_coles(min(i,1), min(j,1), lam, mu, rho)
            matriz[i][j] = max(tau, 0) * poisson.pmf(i, lam) * poisson.pmf(j, mu)

    matriz = matriz / matriz.sum()  # renormalizar para que sume 1

    p_l = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i > j)
    p_e = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i == j)
    p_v = sum(matriz[i][j] for i in range(MAX_GOLES+1) for j in range(MAX_GOLES+1) if i < j)
    return p_l, p_e, p_v

def main():
    df = pd.read_csv("premier_league_combinado.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    fecha_corte = df["Date"].max() - pd.Timedelta(days=365)
    entrenamiento_inicial = df[df["Date"] < fecha_corte]
    prueba = df[df["Date"] >= fecha_corte]

    print("Ajustando el parametro rho de Dixon-Coles con los datos de entrenamiento...")
    rho = ajustar_rho(entrenamiento_inicial)
    print(f"Rho ajustado: {rho:.3f}\n")

    print(f"Partidos a predecir (backtest): {len(prueba)}\n")

    brier_scores = []
    aciertos = 0
    total_evaluado = 0

    for _, partido in prueba.iterrows():
        datos_hasta_ahora = df[df["Date"] < partido["Date"]]
        fuerzas, prom_l, prom_v = calcular_fuerzas(datos_hasta_ahora)

        resultado = predecir_1x2_dc(partido["HomeTeam"], partido["AwayTeam"], fuerzas, prom_l, prom_v, rho)
        if resultado is None:
            continue

        p_l, p_e, p_v = resultado
        real = partido["FTR"]
        real_vector = [1 if real=="H" else 0, 1 if real=="D" else 0, 1 if real=="A" else 0]
        pred_vector = [p_l, p_e, p_v]

        brier = sum((pv-rv)**2 for pv, rv in zip(pred_vector, real_vector))
        brier_scores.append(brier)

        pick = max([("H",p_l),("D",p_e),("A",p_v)], key=lambda x: x[1])[0]
        if pick == real:
            aciertos += 1
        total_evaluado += 1

    print(f"Partidos evaluados: {total_evaluado}")
    print(f"Aciertos: {aciertos} ({aciertos/total_evaluado*100:.1f}%)")
    print(f"Brier score promedio: {sum(brier_scores)/len(brier_scores):.4f}")
    print("\nCompara contra el modelo sin Dixon-Coles: 48.7% aciertos, Brier 0.6233")
    print("Y contra el baseline ingenuo: 42.1% aciertos, Brier 0.6575")

if __name__ == "__main__":
    main()