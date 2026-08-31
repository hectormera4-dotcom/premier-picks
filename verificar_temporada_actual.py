"""
Verifica los datos de la temporada 2026/2027 en football-data.org:
- Confirma que la temporada esta disponible
- Muestra los nombres EXACTOS de los equipos (para compararlos con los del CSV historico)
- Cuenta cuantos partidos ya se jugaron vs cuantos faltan
"""
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

def verificar():
    resp = requests.get(
        f"{BASE_URL}/competitions/PL/matches",
        headers=HEADERS,
        params={"season": 2026}
    )
    resp.raise_for_status()
    data = resp.json()
    partidos = data.get("matches", [])

    print(f"Total de partidos en la temporada 2026/2027: {len(partidos)}\n")

    finalizados = [p for p in partidos if p["status"] == "FINISHED"]
    programados = [p for p in partidos if p["status"] in ("SCHEDULED", "TIMED")]

    print(f"Ya jugados: {len(finalizados)}")
    print(f"Por jugar: {len(programados)}\n")

    equipos = sorted(set(p["homeTeam"]["name"] for p in partidos))
    print("Nombres EXACTOS de los equipos segun football-data.org:")
    for equipo in equipos:
        print(f"  - {equipo}")

    if programados:
        print(f"\nEjemplo de proximo partido programado:")
        prox = programados[0]
        print(f"  {prox['homeTeam']['name']} vs {prox['awayTeam']['name']}")
        print(f"  Fecha: {prox['utcDate']}")

if __name__ == "__main__":
    verificar()