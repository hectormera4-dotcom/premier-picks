"""
Construye un rating tipo Elo para los equipos de Premier League
usando el historico combinado de partidos.
"""
import pandas as pd

# --- Configuracion del modelo ---
RATING_INICIAL = 1500      # todos los equipos empiezan igual
K_FACTOR = 20               # que tanto se mueve el rating por partido (20 es un valor estandar)
VENTAJA_LOCAL = 65          # puntos extra de "fuerza" por jugar en casa

def probabilidad_esperada(rating_a, rating_b):
    """Probabilidad de que el equipo A gane, segun la formula de Elo."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def actualizar_elo(rating, resultado_real, resultado_esperado, k=K_FACTOR):
    """Ajusta el rating segun si el resultado real fue mejor o peor de lo esperado."""
    return rating + k * (resultado_real - resultado_esperado)

def main():
    # 1. Cargar los datos y ordenarlos cronologicamente (esto es CRITICO para Elo)
    df = pd.read_csv("premier_league_combinado.csv")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)

    # 2. Inicializar el rating de cada equipo
    equipos = pd.unique(df[["HomeTeam", "AwayTeam"]].values.ravel())
    ratings = {equipo: RATING_INICIAL for equipo in equipos}

    print(f"Procesando {len(df)} partidos en orden cronologico...\n")

    # 3. Recorrer cada partido, en orden, y actualizar los ratings
    for _, partido in df.iterrows():
        local = partido["HomeTeam"]
        visitante = partido["AwayTeam"]
        goles_local = partido["FTHG"]
        goles_visitante = partido["FTAG"]

        rating_local = ratings[local] + VENTAJA_LOCAL
        rating_visitante = ratings[visitante]

        prob_local = probabilidad_esperada(rating_local, rating_visitante)
        prob_visitante = 1 - prob_local

        # resultado real: 1 = gano, 0.5 = empato, 0 = perdio
        if goles_local > goles_visitante:
            resultado_local, resultado_visitante = 1, 0
        elif goles_local < goles_visitante:
            resultado_local, resultado_visitante = 0, 1
        else:
            resultado_local, resultado_visitante = 0.5, 0.5

        ratings[local] = actualizar_elo(ratings[local], resultado_local, prob_local)
        ratings[visitante] = actualizar_elo(ratings[visitante], resultado_visitante, prob_visitante)

    # 4. Mostrar la tabla final de ratings, ordenada de mayor a menor
    tabla_final = pd.DataFrame(list(ratings.items()), columns=["Equipo", "Rating_Elo"])
    tabla_final = tabla_final.sort_values("Rating_Elo", ascending=False).reset_index(drop=True)

    print("=== RATING ELO FINAL (tras 4 temporadas) ===\n")
    print(tabla_final.to_string(index=False))

    tabla_final.to_csv("elo_ratings_actuales.csv", index=False)
    print("\nGuardado como 'elo_ratings_actuales.csv'")

if __name__ == "__main__":
    main()