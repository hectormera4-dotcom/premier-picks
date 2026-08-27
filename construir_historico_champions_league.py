"""
Script de UNA SOLA VEZ para construir el historico de Champions League,
usando datos publicos de openfootball (github.com/openfootball/champions-league)
-- football-data.co.uk NO cubre competencias europeas, asi que esta es la
unica fuente gratuita de historico multi-temporada disponible.

A diferencia de las 5 ligas domesticas, este historico NO incluye
corners/tarjetas/tiros a puerta (esos datos no existen para Champions
League en ninguna fuente gratuita) -- solo el mercado de goles.

Ademas, el pool de equipos cambia cada temporada (36 clasificados
distintos, no una liga fija de ~20 equipos), y el mismo club aparece con
variantes de nombre segun el anio (ej. "Real Madrid" en 2019 vs
"Real Madrid CF" en 2024). Por eso este script normaliza nombres
automaticamente (quita sufijos corporativos) y ademas aplica una tabla
de alias para los casos que la normalizacion automatica no resuelve --
esa tabla fue verificada a mano, equipo por equipo, contra la lista
completa de clubes que aparecieron en las ultimas 7 temporadas.

Correr esto UNA VEZ desde tu computadora (no es parte del pipeline diario):
    python construir_historico_champions_league.py
"""
import re
import requests
import pandas as pd

# Reutilizamos la MISMA funcion de normalizacion y tabla de alias que usa
# el pipeline en vivo (actualizar_y_predecir.py) -- asi el historico que
# construimos aqui y los nombres que la API manda en produccion SIEMPRE
# coinciden, sin mantener dos copias que se puedan desincronizar.
from actualizar_y_predecir import normalizar_nombre_equipo

TEMPORADAS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
MESES = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}

def descargar_temporada(temporada):
    url = f"https://raw.githubusercontent.com/openfootball/champions-league/master/{temporada}/cl.txt"
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200:
        return None
    # IMPORTANTE: resp.text decodifica mal caracteres UTF-8 (ej. la u con
    # dieresis de "München") aunque resp.encoding reporte 'utf-8' --
    # decodificar los bytes crudos directamente da el resultado correcto.
    return resp.content.decode("utf-8")

def parsear_football_txt(texto):
    """Devuelve lista de dicts {Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR}."""
    partidos = []
    fecha_actual = None
    anio_actual = None

    patron_fecha = re.compile(r"^\s{2}\w{3}\s+(\w{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
    patron_partido = re.compile(r"^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+)-(\d+)(?:\s|$)")

    for linea in texto.splitlines():
        m_fecha = patron_fecha.match(linea)
        if m_fecha:
            mes_str, dia_str, anio_str = m_fecha.groups()
            if anio_str:
                anio_actual = int(anio_str)
            if anio_actual and mes_str in MESES:
                fecha_actual = pd.Timestamp(year=anio_actual, month=MESES[mes_str], day=int(dia_str))
            continue

        m_partido = patron_partido.match(linea)
        if m_partido and fecha_actual is not None:
            local_raw, visitante_raw, gh, ga = m_partido.groups()
            local_raw = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", local_raw).strip()
            visitante_raw = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", visitante_raw).strip()

            local = normalizar_nombre_equipo(local_raw)
            visitante = normalizar_nombre_equipo(visitante_raw)
            gh, ga = int(gh), int(ga)
            ftr = "H" if gh > ga else ("A" if ga > gh else "D")
            partidos.append({
                "Date": fecha_actual, "HomeTeam": local, "AwayTeam": visitante,
                "FTHG": gh, "FTAG": ga, "FTR": ftr,
            })

    return partidos

todos = []
for temporada in TEMPORADAS:
    texto = descargar_temporada(temporada)
    if texto is None:
        print(f"{temporada}: no disponible, se omite")
        continue
    partidos = parsear_football_txt(texto)
    print(f"{temporada}: {len(partidos)} partidos parseados")
    todos.extend(partidos)

df = pd.DataFrame(todos)
df["Date"] = df["Date"].dt.strftime("%d/%m/%Y")
df.to_csv("champions_league_combinado.csv", index=False)
print(f"\nListo: champions_league_combinado.csv creado con {len(df)} partidos en total, "
      f"{len(set(df['HomeTeam']) | set(df['AwayTeam']))} equipos distintos.")
