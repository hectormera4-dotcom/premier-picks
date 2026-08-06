import requests

API_TOKEN = "98cececafb38425e9ace0546b73ffcff"  # lo obtienes al registrarte gratis en football-data.org
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