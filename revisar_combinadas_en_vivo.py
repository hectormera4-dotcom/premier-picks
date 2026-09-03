# Revision liviana "en vivo": corre cada 15 minutos (via GitHub Actions,
# ver .github/workflows/revisar_en_vivo.yml) mientras hay partidos en
# curso, y hace SOLO 2 cosas -- a proposito no recalcula el modelo ni
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
#      sin problema).
#
# Con eso, resuelve cualquier combinada pendiente que ya tenga todas sus
# patas jugadas y actualiza el historial en Supabase -- asi la pagina de
# Historial refleja resultados mas rapido que esperando a la corrida
# nocturna completa, aunque no se manda ninguna notificacion push desde
# aqui (ver actualizar_y_predecir.py: las notificaciones push avisan
# cuando los picks del dia siguiente ya estan disponibles, no cuando una
# combinada se resuelve -- se intento que fuera al instante tambien para
# esto, pero no hay ninguna fuente de datos externa gratuita de
# corners/tarjetas/tiros que actualice lo bastante rapido y que ademas no
# bloquee peticiones automatizadas; se probaron SofaScore, ESPN y FotMob,
# los 3 sin exito -- ver el historial de commits para el detalle).
#
# Reutiliza las funciones ya existentes y probadas de actualizar_y_predecir.py
# (traduccion de nombres de equipo, verificacion de combinadas, descarga de
# corners/tarjetas) en vez de duplicar esa logica.

import os
from datetime import datetime, timedelta

import pandas as pd

import actualizar_y_predecir as core

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
    # ahora.
    for liga_key in core.LIGAS_ACTIVAS:
        actualizar_extra_liga(liga_key)

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
    historial_combinadas = core.verificar_combinadas_resueltas(historial_combinadas, pool_historico)
    historial_combinadas.to_csv(core.ARCHIVO_HISTORIAL_COMBINADAS_MULTILIGA, index=False)
    if core.supabase_configurado():
        core.subir_historial_combinadas_liga_ya_incluida(historial_combinadas)

    print("Revision en vivo completada.")
