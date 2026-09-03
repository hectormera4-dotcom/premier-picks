# Revision liviana "en vivo": corre cada 15 minutos (via GitHub Actions,
# ver .github/workflows/revisar_en_vivo.yml) mientras hay partidos en
# curso, y hace SOLO 3 cosas -- a proposito no recalcula el modelo ni
# genera picks nuevos (eso sigue siendo trabajo exclusivo del pipeline
# nocturno, mas pesado y mas lento):
#
#   1. Revisa si algun partido de HOY ya termino (usando UN SOLO llamado a
#      la API, que cubre todas las ligas activas de una vez -- para no
#      exceder el limite gratuito de football-data.org al consultar cada
#      15 minutos todo el dia). Esto trae los GOLES.
#   2. Refresca corners/tarjetas/tiros a puerta de cada liga activa desde
#      football-data.co.uk (la fuente que SI tiene esos datos -- sin
#      limite de peticiones, asi que se puede consultar cada 15 minutos
#      sin problema). SIN ESTE PASO, una combinada armada con picks de
#      corners/tarjetas/tiros nunca se resolvia aqui -- se quedaba
#      "Pendiente" hasta la proxima corrida nocturna completa, aunque el
#      partido ya llevara horas terminado (goles NO es lo mismo que
#      corners: son 2 fuentes de datos distintas).
#   3. Si con eso alguna combinada pendiente termina de resolverse (todas
#      sus patas ya jugadas), le manda una notificacion push a todos los
#      que se suscribieron, avisando si se cumplio o fallo -- minutos
#      despues de que termino el ultimo partido, no horas.
#
# Reutiliza las funciones ya existentes y probadas de actualizar_y_predecir.py
# (traduccion de nombres de equipo, verificacion de combinadas, descarga de
# corners/tarjetas) en vez de duplicar esa logica.

import json
import os
from datetime import datetime, timedelta

import pandas as pd
import requests

import actualizar_y_predecir as core

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:soporte@picksfc.app")

# codigo de football-data.org -> liga_key, para saber a que liga
# pertenece cada partido que devuelve el llamado global de la API.
CODIGO_API_A_LIGA = {cfg["codigo_api"]: liga_key for liga_key, cfg in core.LIGAS.items()}


def obtener_partidos_de_hoy_todas_las_ligas():
    """Un solo llamado a la API que trae los partidos de HOY de TODAS las
    competencias a las que da acceso el token (no hace falta un llamado
    por liga) -- asi revisar cada 15 minutos no dispara el limite gratuito."""
    hoy = (datetime.utcnow() - timedelta(hours=1)).date()  # margen de 1h por si el partido empezo ayer en UTC
    manana = hoy + timedelta(days=1)
    resp = core._get_football_data_org(
        f"{core.BASE_URL}/matches",
        params={"dateFrom": str(hoy), "dateTo": str(manana)},
    )
    resp.raise_for_status()
    return resp.json().get("matches", [])


def actualizar_historico_liviano(liga_key, partidos_finalizados):
    """Version liviana de actualizar_historico(): SOLO agrega los goles de
    los partidos ya finalizados al historico de esa liga (los datos de
    corners/tarjetas/tiros se refrescan aparte, ver actualizar_extra_liga)."""
    config = core._fijar_globales_liga(liga_key)
    archivo = config["archivo_historico"]
    if not os.path.exists(archivo):
        return False

    historico = pd.read_csv(archivo)
    historico["Date"] = pd.to_datetime(historico["Date"], dayfirst=True).dt.normalize()

    hubo_cambios = False
    nuevos = []
    for p in partidos_finalizados:
        local = core._traducir_nombre_equipo(p["homeTeam"]["name"])
        visitante = core._traducir_nombre_equipo(p["awayTeam"]["name"])
        fecha = pd.to_datetime(p["utcDate"]).tz_localize(None).normalize()

        ya_existe = ((historico["Date"] == fecha) &
                     (historico["HomeTeam"] == local) &
                     (historico["AwayTeam"] == visitante)).any()
        if ya_existe:
            continue

        gh = p["score"]["fullTime"]["home"]
        ga = p["score"]["fullTime"]["away"]
        if gh is None or ga is None:
            continue
        ftr = "H" if gh > ga else ("A" if ga > gh else "D")
        nuevos.append({"Date": fecha, "HomeTeam": local, "AwayTeam": visitante, "FTHG": gh, "FTAG": ga, "FTR": ftr})

    if nuevos:
        historico = pd.concat([historico, pd.DataFrame(nuevos)], ignore_index=True)
        historico_a_guardar = historico.copy()
        historico_a_guardar["Date"] = pd.to_datetime(historico_a_guardar["Date"]).dt.strftime("%d/%m/%Y")
        historico_a_guardar.to_csv(archivo, index=False)
        print(f"[{liga_key}] {len(nuevos)} partido(s) recien finalizado(s) agregado(s) al historico.")
        hubo_cambios = True

    return hubo_cambios


def actualizar_extra_liga(liga_key):
    """Refresca corners/tarjetas/tiros a puerta de UNA liga desde
    football-data.co.uk -- sin esto, una combinada armada solo con esos
    mercados nunca se resuelve aqui (se queda esperando a la corrida
    nocturna). football-data.co.uk no tiene el limite de peticiones que
    si tiene football-data.org, asi que no hay problema en consultarlo
    cada 15 minutos. (actualizar_estadisticas_extra ya se encarga de
    guardar el archivo solo si de verdad hubo algun cambio real.)"""
    config = core._fijar_globales_liga(liga_key)
    if not config.get("codigo_footballdata"):
        return  # esta liga no tiene esta fuente (ej. competencias europeas)
    if not os.path.exists(config["archivo_historico"]):
        return

    historico = pd.read_csv(config["archivo_historico"])
    historico["Date"] = pd.to_datetime(historico["Date"], dayfirst=True).dt.normalize()
    core.actualizar_estadisticas_extra(historico, config["codigo_footballdata"])


NOMBRES_ESTADISTICAS_SOFASCORE = {
    "corner kicks": ("HC", "AC"),
    "yellow cards": ("HY", "AY"),
    "shots on target": ("HST", "AST"),
}


def actualizar_extra_sofascore(liga_key, fecha):
    """Complementa actualizar_extra_liga(): trae corners/tarjetas/tiros a
    puerta desde SofaScore, que publica minutos despues de que termina el
    partido (a diferencia de football-data.co.uk, que solo actualiza un
    par de veces por semana). 'fecha' es un date de Python.

    OJO -- esta es la API SIN DOCUMENTAR que usa la propia pagina web de
    SofaScore (sin llave, sin costo, de uso comun en proyectos
    independientes para esto mismo) -- no es un servicio contratado, y
    podria cambiar de formato sin aviso. Por eso NO reemplaza a
    football-data.co.uk, que sigue corriendo igual como respaldo: si
    SofaScore alguna vez deja de funcionar, el sistema sigue resolviendo
    todo, solo que otra vez al ritmo mas lento de antes de este cambio."""
    config = core._fijar_globales_liga(liga_key)
    tournament_id = config.get("sofascore_tournament_id")
    mapeo = config.get("mapeo_sofascore")
    if not tournament_id or not mapeo:
        return
    archivo = config["archivo_historico"]
    if not os.path.exists(archivo):
        return

    try:
        resp = requests.get(
            f"https://www.sofascore.com/api/v1/unique-tournament/{tournament_id}/scheduled-events/{fecha}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 404:
            return  # sin partidos programados ese dia para esta liga -- normal
        resp.raise_for_status()
        eventos = resp.json().get("events", [])
    except Exception as e:
        print(f"[{liga_key}] Aviso: SofaScore no disponible ahorita ({e}) -- sigue football-data.co.uk como respaldo.")
        return

    historico = pd.read_csv(archivo)
    historico["Date"] = pd.to_datetime(historico["Date"], dayfirst=True).dt.normalize()
    for col in ["HC", "AC", "HY", "AY", "HST", "AST"]:
        if col not in historico.columns:
            historico[col] = pd.NA

    hubo_cambios = False
    fecha_partido = pd.Timestamp(fecha)

    for ev in eventos:
        if ev.get("status", {}).get("type") != "finished":
            continue

        local = mapeo.get(ev.get("homeTeam", {}).get("name"))
        visitante = mapeo.get(ev.get("awayTeam", {}).get("name"))
        if not local or not visitante:
            continue  # equipo que no reconocemos en la tabla -- lo agarra football-data.co.uk despues

        mask = ((historico["Date"] == fecha_partido) &
                (historico["HomeTeam"] == local) &
                (historico["AwayTeam"] == visitante))
        if not mask.any() or pd.notna(historico.loc[mask, "HC"].iloc[0]):
            continue  # el partido no esta en nuestro historico, o ya tenemos sus corners

        try:
            stats_resp = requests.get(
                f"https://www.sofascore.com/api/v1/event/{ev['id']}/statistics",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            stats_resp.raise_for_status()
            stats = stats_resp.json()
        except Exception as e:
            print(f"[{liga_key}] Aviso: no se pudo traer estadisticas de {local} vs {visitante} ({e}).")
            continue

        valores = {}
        for grupo in stats.get("statistics", []):
            if grupo.get("period") != "ALL":
                continue
            for categoria in grupo.get("groups", []):
                for item in categoria.get("statisticsItems", []):
                    columnas = NOMBRES_ESTADISTICAS_SOFASCORE.get(str(item.get("name", "")).lower())
                    if not columnas:
                        continue
                    # SofaScore manda estos numeros como texto (ej. "7",
                    # no 7) -- sin convertir, pandas rechaza guardarlos en
                    # una columna numerica.
                    try:
                        valor_local = int(item.get("home"))
                        valor_visitante = int(item.get("away"))
                    except (TypeError, ValueError):
                        continue
                    valores[columnas[0]] = valor_local
                    valores[columnas[1]] = valor_visitante

        if not valores:
            continue

        for col, val in valores.items():
            historico.loc[mask, col] = val
        hubo_cambios = True
        print(f"[{liga_key}] SofaScore: {local} vs {visitante} -> {valores}")

    if hubo_cambios:
        historico_a_guardar = historico.copy()
        historico_a_guardar["Date"] = pd.to_datetime(historico_a_guardar["Date"]).dt.strftime("%d/%m/%Y")
        historico_a_guardar.to_csv(archivo, index=False)
        print(f"[{liga_key}] Estadisticas de SofaScore guardadas para {fecha}.")


def enviar_notificacion_push(titulo, cuerpo):
    """Le manda la notificacion a TODAS las suscripciones guardadas.
    Si una suscripcion ya no es valida (el usuario desinstalo la app,
    borro el navegador, etc.), la borramos de la base -- asi no se
    acumulan suscripciones muertas para siempre."""
    if not VAPID_PRIVATE_KEY or not core.supabase_configurado():
        print("Notificaciones push no configuradas (falta VAPID_PRIVATE_KEY o Supabase) -- se omite el envio.")
        return

    from pywebpush import webpush, WebPushException

    resp = requests.get(
        f"{core.SUPABASE_URL}/rest/v1/push_subscripciones?select=id,endpoint,suscripcion_json",
        headers=core.supabase_headers(),
    )
    if resp.status_code != 200:
        print(f"Aviso: no se pudieron leer las suscripciones ({resp.status_code}): {resp.text[:300]}")
        return

    suscripciones = resp.json()
    payload = json.dumps({"title": titulo, "body": cuerpo})
    enviados, muertas = 0, []

    for s in suscripciones:
        try:
            webpush(
                subscription_info=s["suscripcion_json"],
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
            )
            enviados += 1
        except WebPushException as e:
            codigo = getattr(e.response, "status_code", None)
            if codigo in (404, 410):  # suscripcion ya no existe (expiro o el usuario la borro)
                muertas.append(s["id"])
            else:
                print(f"Aviso: fallo al enviar una notificacion ({codigo}): {e}")

    if muertas:
        ids_csv = ",".join(str(i) for i in muertas)
        requests.delete(f"{core.SUPABASE_URL}/rest/v1/push_subscripciones?id=in.({ids_csv})", headers=core.supabase_headers())

    print(f"Notificacion enviada a {enviados}/{len(suscripciones)} suscripciones ({len(muertas)} vencidas, borradas).")


if __name__ == "__main__":
    partidos_hoy = obtener_partidos_de_hoy_todas_las_ligas()
    finalizados_por_liga = {}
    for p in partidos_hoy:
        codigo = p.get("competition", {}).get("code")
        liga_key = CODIGO_API_A_LIGA.get(codigo)
        if liga_key is None or liga_key not in core.LIGAS_ACTIVAS or p["status"] != "FINISHED":
            continue
        finalizados_por_liga.setdefault(liga_key, []).append(p)

    for liga_key, partidos in finalizados_por_liga.items():
        actualizar_historico_liviano(liga_key, partidos)

    # Refrescamos corners/tarjetas/tiros de TODAS las ligas activas, no
    # solo las que tuvieron un gol nuevo ahorita -- football-data.co.uk es
    # una fuente totalmente aparte de football-data.org, con su propio
    # ritmo de publicacion, asi que un partido puede llevar horas con el
    # marcador de goles ya confirmado y sus corners recien apareciendo
    # ahora. Sin este paso, cualquier combinada armada solo con esos
    # mercados se quedaba esperando a la corrida nocturna para resolverse.
    for liga_key in core.LIGAS_ACTIVAS:
        actualizar_extra_liga(liga_key)

    # SofaScore (mas rapido, ver actualizar_extra_sofascore) -- revisamos
    # hoy, ayer y antier por cada liga activa, para tambien destrabar
    # cualquier combinada que se hubiera quedado pendiente uno o dos dias
    # esperando a football-data.co.uk.
    hoy_ecuador = (datetime.utcnow() - timedelta(hours=core.ZONA_ECUADOR_OFFSET_HORAS)).date()
    for liga_key in core.LIGAS_ACTIVAS:
        for hace_dias in (0, 1, 2):
            actualizar_extra_sofascore(liga_key, hoy_ecuador - timedelta(days=hace_dias))

    # Juntamos el historico actualizado de TODAS las ligas activas (no solo
    # las que tuvieron partidos ahorita) para poder resolver cualquier
    # combinada pendiente, igual que hace el pipeline nocturno.
    historicos_completos = []
    for liga_key in core.LIGAS_ACTIVAS:
        config = core._fijar_globales_liga(liga_key)
        if not os.path.exists(config["archivo_historico"]):
            continue
        h = pd.read_csv(config["archivo_historico"])
        h["Date"] = pd.to_datetime(h["Date"], dayfirst=True).dt.normalize()
        historicos_completos.append(h)
    pool_historico = pd.concat(historicos_completos, ignore_index=True) if historicos_completos else pd.DataFrame()

    historial_combinadas = core.cargar_historial_combinadas()
    pendientes_antes = set(historial_combinadas.loc[historial_combinadas["resultado"].isna(), "id_combinada"])

    historial_combinadas = core.verificar_combinadas_resueltas(historial_combinadas, pool_historico)
    historial_combinadas.to_csv(core.ARCHIVO_HISTORIAL_COMBINADAS_MULTILIGA, index=False)
    if core.supabase_configurado():
        core.subir_historial_combinadas_liga_ya_incluida(historial_combinadas)

    recien_resueltas = historial_combinadas[
        historial_combinadas["id_combinada"].isin(pendientes_antes) & historial_combinadas["resultado"].notna()
    ]

    for _, fila in recien_resueltas.iterrows():
        gano = fila["resultado"] == "Cumplida"
        titulo = "✅ ¡Combinada cumplida!" if gano else "❌ Combinada fallada"
        cuerpo = f"Fecha {int(fila['numero_fecha'])} — cuota {fila['cuota_combinada']}. Revisa el resultado completo en la app."
        enviar_notificacion_push(titulo, cuerpo)

    if len(recien_resueltas) == 0:
        print("El historico se actualizo, pero ninguna combinada pendiente termino de resolverse todavia.")
    else:
        print(f"{len(recien_resueltas)} combinada(s) se resolvieron en esta revision -- notificaciones enviadas.")
