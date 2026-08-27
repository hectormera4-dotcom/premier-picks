"""
Backtest de calibracion para Champions League.

A diferencia de backtest.py/backtest_dixon_coles.py (que reimplementan el
modelo aparte), este script REUSA las funciones reales de
actualizar_y_predecir.py (calcular_fuerzas, matriz_marcadores, CONDICIONES,
calcular_combo, verificar_pick_individual) -- asi el backtest mide
exactamente lo que va a correr en produccion, sin riesgo de que una copia
del modelo se desincronice de la real.

Solo evalua mercados de GOLES (1X2, doble oportunidad, over/under, ambos
anotan, y combos entre esas categorias) -- Champions League no tiene
corners/tarjetas/tiros a puerta (no existe fuente de datos gratuita para
eso), asi que esos mercados nunca se evaluan aqui.

Camina hacia adelante en el tiempo (walk-forward): para cada partido a
evaluar, calcula las fuerzas SOLO con partidos anteriores a esa fecha (sin
ver el futuro), exactamente como corre el pipeline real cada dia.

Correr con: python backtest_champions_league.py
"""
import io
import sys
import contextlib
import pandas as pd
import numpy as np
from scipy.optimize import minimize

# Algunos nombres de equipo tienen caracteres que la consola de Windows
# (cp1252) no puede imprimir (ej. la "I" turca de "İstanbul Başakşehir") --
# sin esto, el aviso de fallback de un equipo asi CRASHEA todo el backtest.
# errors="replace" hace que se imprima un caracter de reemplazo en vez de
# fallar, en cualquier consola.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import actualizar_y_predecir as m

# Mismo comportamiento que en produccion para esta competencia: cualquier
# equipo sin historial usa la fuerza conservadora automaticamente.
m.FALLBACK_AUTOMATICO = True

ARCHIVO = "champions_league_combinado.csv"
FECHA_CORTE_EVALUACION = pd.Timestamp("2020-08-01")  # la temporada 2019-20 se usa solo para entrenar

def construir_candidatos():
    """Misma logica que elegir_mejor_pick: individuales + combos de 2
    categorias distintas (sin los mercados extra, que no aplican aqui)."""
    nombres = list(m.CONDICIONES.keys())
    candidatos = [[n] for n in nombres]
    for i in range(len(nombres)):
        for j in range(i+1, len(nombres)):
            n1, n2 = nombres[i], nombres[j]
            if m.CATEGORIAS[n1] == m.CATEGORIAS[n2]:
                continue
            candidatos.append([n1, n2])
    return candidatos

def main():
    df = pd.read_csv(ARCHIVO)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    entrenamiento_inicial = df[df["Date"] < FECHA_CORTE_EVALUACION]
    evaluacion = df[df["Date"] >= FECHA_CORTE_EVALUACION].reset_index(drop=True)
    print(f"Partidos de entrenamiento inicial (2019-20, no se evaluan): {len(entrenamiento_inicial)}")
    print(f"Partidos a evaluar (2020-21 en adelante): {len(evaluacion)}\n")

    print("Ajustando rho con la temporada inicial...")
    fuerzas_ini, prom_l_ini, prom_v_ini = m.calcular_fuerzas(entrenamiento_inicial)
    rho = m.ajustar_rho(entrenamiento_inicial, fuerzas_ini, prom_l_ini, prom_v_ini)
    print(f"Rho ajustado: {rho:.3f}\n")

    candidatos = construir_candidatos()
    print(f"Candidatos evaluados por partido (individuales + combos validos): {len(candidatos)}\n")

    observaciones = []  # (prob_cruda, resultado_bool)
    partidos_evaluados = 0

    print("Caminando hacia adelante en el tiempo (esto tarda unos minutos)...")
    for idx, partido in evaluacion.iterrows():
        datos_hasta_ahora = df[df["Date"] < partido["Date"]]

        # Silenciamos los avisos de fallback aqui -- se disparan tanto al
        # calcular fuerzas como (de forma perezosa) la primera vez que se
        # accede a fuerzas[equipo] dentro de matriz_marcadores, asi que
        # hay que envolver las dos llamadas, no solo la primera.
        with contextlib.redirect_stdout(io.StringIO()):
            fuerzas, prom_l, prom_v = m.calcular_fuerzas(datos_hasta_ahora)
            matriz, lam, mu = m.matriz_marcadores(partido["HomeTeam"], partido["AwayTeam"], fuerzas, prom_l, prom_v, rho)
        if matriz is None:
            continue

        partidos_evaluados += 1
        for condiciones in candidatos:
            prob = m.calcular_combo(matriz, condiciones)
            resultados_leg = [m.verificar_pick_individual(c, partido) for c in condiciones]
            if any(r is None for r in resultados_leg):
                continue
            resultado_real = all(resultados_leg)
            observaciones.append((prob, resultado_real))

        if (idx + 1) % 100 == 0:
            print(f"  ...{idx + 1}/{len(evaluacion)} partidos procesados, {len(observaciones)} observaciones hasta ahora")

    obs = pd.DataFrame(observaciones, columns=["prob_cruda", "resultado"])
    print(f"\nPartidos evaluados: {partidos_evaluados}/{len(evaluacion)}")
    print(f"Total de observaciones (mercado x partido): {len(obs)}\n")

    # ---------- Ajuste de Platt Scaling (misma forma que calibrar_probabilidad) ----------
    def neg_log_verosimilitud(params):
        intercepto, pendiente = params
        z = intercepto + pendiente * obs["prob_cruda"].values
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        p = np.clip(p, 1e-10, 1 - 1e-10)
        y = obs["resultado"].astype(float).values
        return -np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))

    print("Ajustando Platt Scaling (regresion logistica: real ~ probabilidad cruda)...")
    resultado_opt = minimize(neg_log_verosimilitud, x0=[0.0, 1.0], method="Nelder-Mead",
                              options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 5000})
    intercepto, pendiente = resultado_opt.x
    print(f"\n{'='*60}")
    print(f"PENDIENTE  = {pendiente:.4f}")
    print(f"INTERCEPTO = {intercepto:.4f}")
    print(f"{'='*60}\n")

    # ---------- Reporte de calidad de calibracion ----------
    obs["prob_calibrada"] = 1 / (1 + np.exp(-np.clip(intercepto + pendiente * obs["prob_cruda"], -30, 30)))

    brier_crudo = ((obs["prob_cruda"] - obs["resultado"].astype(float)) ** 2).mean()
    brier_calibrado = ((obs["prob_calibrada"] - obs["resultado"].astype(float)) ** 2).mean()
    print(f"Brier score SIN calibrar: {brier_crudo:.4f}")
    print(f"Brier score CALIBRADO:    {brier_calibrado:.4f}  (mientras mas bajo, mejor)\n")

    print("Declarado vs Real por rango de probabilidad CALIBRADA (asi es como se vera en produccion):")
    bins = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]
    for i in range(len(bins)-1):
        sub = obs[(obs["prob_calibrada"] >= bins[i]) & (obs["prob_calibrada"] < bins[i+1])]
        if len(sub) == 0:
            continue
        declarado = sub["prob_calibrada"].mean() * 100
        real = sub["resultado"].astype(float).mean() * 100
        print(f"  [{bins[i]*100:.0f}-{bins[i+1]*100:.0f}%)  n={len(sub):5d}   declarado={declarado:.1f}%   real={real:.1f}%   diferencia={real-declarado:+.1f}pp")

    techo = obs["prob_calibrada"].max() * 100
    print(f"\nTecho real de calibracion (probabilidad calibrada mas alta observada): {techo:.1f}%")
    print("(el umbral de seguridad de Champions League NUNCA deberia superar este numero)")

if __name__ == "__main__":
    main()
