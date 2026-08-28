"""
Backtest de calibracion para el Championship (segunda division inglesa).

A diferencia del backtest de Champions League (solo goles), aqui SI hay
corners/tarjetas/tiros a puerta reales -- evaluamos los 4 mercados, igual
que las 5 ligas principales. Reusa las funciones reales de
actualizar_y_predecir.py (mismo principio que el backtest de Champions
League: medir exactamente lo que correria en produccion).

Camina hacia adelante en el tiempo (walk-forward): la primera temporada
(2022-23) se usa solo para tener historial minimo; se evalua desde
2023-24 en adelante.

Ademas de fijar los propios coeficientes de Platt Scaling, tambien reporta
que tan bien se comportarian los coeficientes YA EXISTENTES de las 5 ligas
domesticas (PENDIENTE=4.8797, INTERCEPTO=-2.6940) si simplemente se
reutilizaran sin cambios -- para decidir si el Championship necesita su
propia calibracion o puede compartir la de las demas.

Correr con: python backtest_championship.py
"""
import io
import sys
import contextlib
import pandas as pd
import numpy as np
from scipy.optimize import minimize

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import actualizar_y_predecir as m

ARCHIVO = "championship_combinado.csv"
FECHA_CORTE_EVALUACION = pd.Timestamp("2023-08-01")  # la temporada 2022-23 se usa solo para entrenar

def construir_candidatos_goles():
    nombres = list(m.CONDICIONES.keys())
    candidatos = [[n] for n in nombres]
    for i in range(len(nombres)):
        for j in range(i+1, len(nombres)):
            n1, n2 = nombres[i], nombres[j]
            if m.CATEGORIAS[n1] == m.CATEGORIAS[n2]:
                continue
            candidatos.append([n1, n2])
    return candidatos

CANDIDATOS_GOLES = construir_candidatos_goles()

def main():
    df = pd.read_csv(ARCHIVO)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    entrenamiento_inicial = df[df["Date"] < FECHA_CORTE_EVALUACION]
    evaluacion = df[df["Date"] >= FECHA_CORTE_EVALUACION].reset_index(drop=True)
    print(f"Partidos de entrenamiento inicial (2022-23, no se evaluan): {len(entrenamiento_inicial)}")
    print(f"Partidos a evaluar (2023-24 en adelante): {len(evaluacion)}\n")

    print("Ajustando rho con la temporada inicial...")
    fuerzas_ini, prom_l_ini, prom_v_ini = m.calcular_fuerzas(entrenamiento_inicial)
    rho = m.ajustar_rho(entrenamiento_inicial, fuerzas_ini, prom_l_ini, prom_v_ini)
    print(f"Rho ajustado: {rho:.3f}\n")

    observaciones = []  # (prob_cruda, resultado_bool, tipo_mercado)
    partidos_evaluados = 0

    print("Caminando hacia adelante en el tiempo (esto tarda varios minutos, son mas de 1600 partidos)...")
    for idx, partido in evaluacion.iterrows():
        datos_hasta_ahora = df[df["Date"] < partido["Date"]]

        with contextlib.redirect_stdout(io.StringIO()):
            fuerzas, prom_l, prom_v = m.calcular_fuerzas(datos_hasta_ahora)
            matriz, lam, mu = m.matriz_marcadores(partido["HomeTeam"], partido["AwayTeam"], fuerzas, prom_l, prom_v, rho)

            fuerzas_c, prom_l_c, prom_v_c = m.calcular_fuerzas_corners(datos_hasta_ahora)
            mercados_corners = m.calcular_mercados_corners(partido["HomeTeam"], partido["AwayTeam"], fuerzas_c, prom_l_c, prom_v_c) if fuerzas_c else {}

            fuerzas_t, factores_arb, prom_l_t, prom_v_t = m.calcular_fuerzas_tarjetas(datos_hasta_ahora)
            arbitro = partido.get("Referee")
            mercados_tarjetas = {}
            if fuerzas_t and arbitro and arbitro in (factores_arb or {}):
                mercados_tarjetas = m.calcular_mercados_tarjetas(partido["HomeTeam"], partido["AwayTeam"], fuerzas_t, factores_arb, prom_l_t, prom_v_t, arbitro=arbitro)

            fuerzas_s, prom_l_s, prom_v_s = m.calcular_fuerzas_tiros(datos_hasta_ahora)
            mercados_tiros = m.calcular_mercados_tiros(partido["HomeTeam"], partido["AwayTeam"], fuerzas_s, prom_l_s, prom_v_s) if fuerzas_s else {}

        if matriz is None:
            continue
        partidos_evaluados += 1

        # Mercados de goles (individuales + combos entre categorias)
        for condiciones in CANDIDATOS_GOLES:
            prob = m.calcular_combo(matriz, condiciones)
            resultados_leg = [m.verificar_pick_individual(c, partido) for c in condiciones]
            if any(r is None for r in resultados_leg):
                continue
            observaciones.append((prob, all(resultados_leg), "goles"))

        # Mercados extra (corners/tarjetas/tiros), cada uno individual
        for nombre, prob in {**mercados_corners, **mercados_tarjetas, **mercados_tiros}.items():
            real = m.verificar_pick_individual(nombre, partido)
            if real is None:
                continue
            tipo = "corners" if "corner" in nombre else ("tarjetas" if "tarjetas" in nombre else "tiros")
            observaciones.append((prob, real, tipo))

        if (idx + 1) % 200 == 0:
            print(f"  ...{idx + 1}/{len(evaluacion)} partidos procesados, {len(observaciones)} observaciones hasta ahora")

    obs = pd.DataFrame(observaciones, columns=["prob_cruda", "resultado", "tipo"])
    print(f"\nPartidos evaluados: {partidos_evaluados}/{len(evaluacion)}")
    print(f"Total de observaciones: {len(obs)}")
    print(obs["tipo"].value_counts())
    print()

    # ---------- Como se comportarian los coeficientes YA EXISTENTES (compartidos con las 5 ligas) ----------
    PENDIENTE_ACTUAL, INTERCEPTO_ACTUAL = 4.8797, -2.6940
    obs["prob_calibrada_actual"] = 1 / (1 + np.exp(-np.clip(INTERCEPTO_ACTUAL + PENDIENTE_ACTUAL * obs["prob_cruda"], -30, 30)))
    print("=== Usando la calibracion YA EXISTENTE de las 5 ligas (sin ajustar nada nuevo) ===")
    bins = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]
    for i in range(len(bins)-1):
        sub = obs[(obs["prob_calibrada_actual"] >= bins[i]) & (obs["prob_calibrada_actual"] < bins[i+1])]
        if len(sub) == 0:
            continue
        declarado = sub["prob_calibrada_actual"].mean() * 100
        real = sub["resultado"].astype(float).mean() * 100
        print(f"  [{bins[i]*100:.0f}-{bins[i+1]*100:.0f}%)  n={len(sub):5d}   declarado={declarado:.1f}%   real={real:.1f}%   diferencia={real-declarado:+.1f}pp")
    techo_actual = obs[obs["prob_calibrada_actual"] < 1.0]["prob_calibrada_actual"].max() * 100
    print(f"Techo con calibracion compartida: {techo_actual:.1f}%\n")

    # ---------- Ajuste de Platt Scaling PROPIO del Championship ----------
    def neg_log_verosimilitud(params):
        intercepto, pendiente = params
        z = intercepto + pendiente * obs["prob_cruda"].values
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        p = np.clip(p, 1e-10, 1 - 1e-10)
        y = obs["resultado"].astype(float).values
        return -np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))

    print("Ajustando Platt Scaling PROPIO para el Championship...")
    resultado_opt = minimize(neg_log_verosimilitud, x0=[0.0, 1.0], method="Nelder-Mead",
                              options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 5000})
    intercepto, pendiente = resultado_opt.x
    print(f"\n{'='*60}\nPENDIENTE  = {pendiente:.4f}\nINTERCEPTO = {intercepto:.4f}\n{'='*60}\n")

    obs["prob_calibrada_propia"] = 1 / (1 + np.exp(-np.clip(intercepto + pendiente * obs["prob_cruda"], -30, 30)))
    print("=== Con calibracion PROPIA (recien ajustada) ===")
    for i in range(len(bins)-1):
        sub = obs[(obs["prob_calibrada_propia"] >= bins[i]) & (obs["prob_calibrada_propia"] < bins[i+1])]
        if len(sub) == 0:
            continue
        declarado = sub["prob_calibrada_propia"].mean() * 100
        real = sub["resultado"].astype(float).mean() * 100
        print(f"  [{bins[i]*100:.0f}-{bins[i+1]*100:.0f}%)  n={len(sub):5d}   declarado={declarado:.1f}%   real={real:.1f}%   diferencia={real-declarado:+.1f}pp")

    techo_propio = obs["prob_calibrada_propia"].max() * 100
    brier_actual = ((obs["prob_calibrada_actual"] - obs["resultado"].astype(float)) ** 2).mean()
    brier_propio = ((obs["prob_calibrada_propia"] - obs["resultado"].astype(float)) ** 2).mean()
    print(f"\nTecho con calibracion propia: {techo_propio:.1f}%")
    print(f"Brier score con calibracion compartida: {brier_actual:.4f}")
    print(f"Brier score con calibracion propia:      {brier_propio:.4f}")

if __name__ == "__main__":
    main()
