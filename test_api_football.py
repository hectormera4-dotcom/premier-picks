import os
import requests

# El token NUNCA va escrito aqui -- se lee de una variable de entorno para
# no volver a exponerlo publicamente en el repo. Antes de correr este
# script: set FOOTBALL_DATA_TOKEN=tu_token (PowerShell: $env:FOOTBALL_DATA_TOKEN="tu_token")
API_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
if not API_TOKEN:
    raise SystemExit("Falta la variable de entorno FOOTBALL_DATA_TOKEN. Configúrala antes de correr este script.")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_TOKEN}

COMPETITION_CODE = "PL"  # PL = Premier League

def probar_temporada(temporada):
    """Descarga los partidos de una temporada específica para revisar calidad de datos."""
    resp = requests.get(
        f"{BASE_URL}/competitions/{COMPETITION_CODE}/matches",
        headers=HEADERS,
        params={"season": temporada}
    )
    resp.raise_for_status()
    data = resp.json()
    partidos = data.get("matches", [])
    print(f"\n=== Temporada {temporada} ===")
    print(f"Total de partidos encontrados: {len(partidos)}")
    if partidos:
        ejemplo = [p for p in partidos if p["status"] == "FINISHED"][0]
        print(f"Ejemplo: {ejemplo['homeTeam']['name']} {ejemplo['score']['fullTime']['home']} - "
              f"{ejemplo['score']['fullTime']['away']} {ejemplo['awayTeam']['name']}")
        print(f"Fecha: {ejemplo['utcDate']} | Estado: {ejemplo['status']}")
    return partidos

if __name__ == "__main__":
    for temporada in [2022, 2023, 2024, 2025]:
        probar_temporada(temporada)