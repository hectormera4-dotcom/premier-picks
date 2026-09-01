# Revision liviana "en vivo": corre cada 15 minutos (via GitHub Actions,
# ver .github/workflows/revisar_en_vivo.yml) mientras hay partidos en
# curso, y hace SOLO 2 cosas -- a proposito no recalcula el modelo ni
# genera picks nuevos (eso sigue siendo trabajo exclusivo del pipeline
# nocturno, mas pesado y mas lento):
#
#   1. Revisa si algun partido de HOY ya termino (usando UN SOLO llamado a
#      la API, que cubre todas las ligas activas de una vez -- para no
#      exceder el limite gratuito de football-data.org al consultar cada
#      15 minutos todo el dia).
#   2. Si eso hace que alguna combinada pendiente termine de resolverse
#      (todas sus patas ya jugadas), le manda una notificacion push a
#      todos los que se suscribieron, avisando si se cumplio o fallo --
#      minutos despues de que termino el ultimo partido, no horas.
#
# Reutiliza las funciones ya existentes y probadas de actualizar_y_predecir.py
# (traduccion de nombres de equipo, verificacion de combinadas) en vez de
# duplicar esa logica.

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
    """Version liviana de actualizar_historico(): SOLO agrega los partidos
    ya finalizados (goles) al historico de esa liga -- no descarga
    corners/tarjetas/tiros (eso solo lo trae el pipeline nocturno desde
    football-data.co.uk, que de todas formas actualiza pocas veces por
    semana, no tiene sentido pedirselo cada 15 minutos)."""
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

    if not finalizados_por_liga:
        print("Ningun partido de las ligas activas termino en esta ventana de tiempo -- nada que revisar.")
        raise SystemExit(0)

    hubo_cambios_en_algun_historico = False
    for liga_key, partidos in finalizados_por_liga.items():
        if actualizar_historico_liviano(liga_key, partidos):
            hubo_cambios_en_algun_historico = True

    if not hubo_cambios_en_algun_historico:
        print("Los partidos finalizados que se vieron ya estaban registrados -- nada nuevo que resolver.")
        raise SystemExit(0)

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
