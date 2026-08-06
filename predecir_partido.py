"""
Usa el rating Elo ya calculado para predecir un partido especifico.
"""
import pandas as pd

VENTAJA_LOCAL = 65

def probabilidad_esperada(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def predecir(equipo_local, equipo_visitante):
    ratings = pd.read_csv("elo_ratings_actuales.csv").set_index("Equipo")["Rating_Elo"]

    if equipo_local not in ratings.index or equipo_visitante not in ratings.index:
        print("Uno de los equipos no se encuentra en la tabla. Revisa el nombre exacto.")
        print("Equipos disponibles:", list(ratings.index))
        return

    rating_local = ratings[equipo_local] + VENTAJA_LOCAL
    rating_visitante = ratings[equipo_visitante]

    prob_local = probabilidad_esperada(rating_local, rating_visitante)
    prob_visitante = probabilidad_esperada(rating_visitante, rating_local)

    # Aproximacion simple de empate (se refina despues con el modelo de goles)
    prob_empate = 0.25
    prob_local_ajustada = prob_local * (1 - prob_empate)
    prob_visitante_ajustada = prob_visitante * (1 - prob_empate)

    print(f"\n{equipo_local} vs {equipo_visitante}")
    print(f"  Probabilidad {equipo_local} gana:  {prob_local_ajustada*100:.1f}%")
    print(f"  Probabilidad empate:              {prob_empate*100:.1f}%")
    print(f"  Probabilidad {equipo_visitante} gana: {prob_visitante_ajustada*100:.1f}%")
    print(f"  Doble oportunidad 1X: {(prob_local_ajustada+prob_empate)*100:.1f}%")
    print(f"  Doble oportunidad X2: {(prob_visitante_ajustada+prob_empate)*100:.1f}%")

if __name__ == "__main__":
    # Cambia estos dos nombres por cualquier partido que quieras probar
    # (deben coincidir EXACTAMENTE con como aparecen en la tabla de ratings)
    predecir("Arsenal", "Man City")