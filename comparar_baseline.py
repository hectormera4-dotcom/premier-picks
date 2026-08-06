"""
Compara el modelo real contra un baseline ingenuo
(predecir siempre el promedio general de la liga, sin usar informacion de equipos).
"""
import pandas as pd

def main():
    df = pd.read_csv("premier_league_combinado.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    fecha_corte = df["Date"].max() - pd.Timedelta(days=365)
    entrenamiento = df[df["Date"] < fecha_corte]
    prueba = df[df["Date"] >= fecha_corte]

    # Baseline: proporcion de H/D/A en el set de entrenamiento
    p_h = (entrenamiento["FTR"] == "H").mean()
    p_d = (entrenamiento["FTR"] == "D").mean()
    p_a = (entrenamiento["FTR"] == "A").mean()

    print(f"Baseline (promedio de liga): Local {p_h*100:.1f}% | Empate {p_d*100:.1f}% | Visitante {p_a*100:.1f}%\n")

    brier_scores = []
    aciertos = 0
    for _, partido in prueba.iterrows():
        real = partido["FTR"]
        real_vector = [1 if real=="H" else 0, 1 if real=="D" else 0, 1 if real=="A" else 0]
        pred_vector = [p_h, p_d, p_a]
        brier = sum((pv-rv)**2 for pv, rv in zip(pred_vector, real_vector))
        brier_scores.append(brier)
        pick = max([("H",p_h),("D",p_d),("A",p_a)], key=lambda x: x[1])[0]
        if pick == real:
            aciertos += 1

    print(f"Partidos evaluados: {len(prueba)}")
    print(f"Aciertos del baseline (siempre predice el resultado mas comun): {aciertos} ({aciertos/len(prueba)*100:.1f}%)")
    print(f"Brier score del baseline: {sum(brier_scores)/len(brier_scores):.4f}")
    print("\nCompara esto contra tu modelo real:")
    print("  Tu modelo: 48.7% aciertos, Brier 0.6233")

if __name__ == "__main__":
    main()