"""
Script de UNA SOLA VEZ para construir el historico de Bundesliga, igual que
se hizo con LaLiga, Serie A y Ligue 1. Descarga varias temporadas de
football-data.co.uk y las combina en un solo archivo.

Correr esto UNA VEZ desde tu computadora (no es parte del pipeline diario):
    python construir_historico_bundesliga.py
"""
import pandas as pd
import requests
import io

TEMPORADAS = ["2223", "2324", "2425", "2526"]
COLUMNAS_NECESARIAS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
                        "HC", "AC", "HY", "AY", "HST", "AST", "Referee"]

partes = []
for temporada in TEMPORADAS:
    url = f"https://www.football-data.co.uk/mmz4281/{temporada}/D1.csv"
    print(f"Descargando temporada {temporada}...")
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        columnas_disponibles = [c for c in COLUMNAS_NECESARIAS if c in df.columns]
        df = df[columnas_disponibles]
        partes.append(df)
        print(f"  {len(df)} partidos descargados.")
    except Exception as e:
        print(f"  Aviso: no se pudo descargar la temporada {temporada}: {e}")

if partes:
    historico = pd.concat(partes, ignore_index=True)
    historico = historico.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    historico.to_csv("bundesliga_combinado.csv", index=False)
    print(f"\nListo: bundesliga_combinado.csv creado con {len(historico)} partidos en total.")
else:
    print("\nNo se pudo descargar ninguna temporada. Revisa tu conexion e intenta de nuevo.")
