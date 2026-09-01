# Pruebas automatizadas de la logica PURA del pipeline -- funciones que no
# necesitan internet ni datos en vivo para probarse, y que ya fueron la
# causa real de varios bugs de produccion (numeracion de "Fecha", el
# calculo del "dia objetivo", el piso de cuota de las combinadas, el
# umbral mas alto para mercados extra al inicio de temporada).
#
# Estas pruebas NO reemplazan verificar la app con datos reales -- varios
# de los bugs mas dificiles de esta app (equipos mal configurados, datos
# externos que llegan tarde) solo se ven con la temporada en vivo. Lo que
# SI garantizan es que un cambio de codigo no rompa silenciosamente una
# regla de negocio que ya sabemos que es correcta.

import json
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import actualizar_y_predecir as core


# ---------- calcular_dia_objetivo_picks ----------
# El bug real: el pipeline corrio con 6 horas de atraso (por un retraso
# del cron de GitHub) y termino generando los picks de UN DIA DE MAS,
# porque el calculo original se anclaba a la medianoche de Ecuador. El
# arreglo ancla el calculo al MEDIODIA de Ecuador, dando ~18 horas de
# margen de atraso antes de que se calcule mal.

class _RelojFalso(datetime):
    """Sustituto de datetime que siempre devuelve una hora UTC fija, para
    poder probar calcular_dia_objetivo_picks() sin depender del reloj real."""
    _fijo = None

    @classmethod
    def utcnow(cls):
        return cls._fijo


def _con_hora_utc_fija(monkeypatch, hora_utc):
    reloj = type("RelojFalso", (_RelojFalso,), {"_fijo": hora_utc})
    monkeypatch.setattr(core, "datetime", reloj)


def test_dia_objetivo_corrida_normal_a_tiempo(monkeypatch):
    # Corrida normal: 23:30 UTC del domingo (18:30 hora Ecuador) -> debe
    # calcular el lunes como dia objetivo.
    _con_hora_utc_fija(monkeypatch, datetime(2026, 8, 30, 23, 30))
    assert core.calcular_dia_objetivo_picks() == datetime(2026, 8, 31).date()


def test_dia_objetivo_tolera_el_atraso_real_que_paso(monkeypatch):
    # El caso real que ocurrio en produccion: la corrida de las 23:30 UTC
    # se disparo 6 horas tarde, a las 05:30 UTC del dia siguiente (00:30
    # hora Ecuador). Antes del arreglo, esto generaba el dia SIGUIENTE al
    # correcto (martes en vez de lunes). Con el arreglo, debe seguir
    # calculando el lunes.
    _con_hora_utc_fija(monkeypatch, datetime(2026, 8, 31, 5, 30))
    assert core.calcular_dia_objetivo_picks() == datetime(2026, 8, 31).date()


def test_dia_objetivo_tolera_atraso_hasta_casi_el_mediodia_ecuador(monkeypatch):
    # Atraso extremo pero todavia dentro del margen: 17:00 UTC del lunes
    # (12:00 hora Ecuador, justo el limite) -> todavia debe dar el lunes.
    _con_hora_utc_fija(monkeypatch, datetime(2026, 8, 31, 16, 59))
    assert core.calcular_dia_objetivo_picks() == datetime(2026, 8, 31).date()


def test_dia_objetivo_pasado_el_limite_avanza_un_dia_mas(monkeypatch):
    # Pasado el mediodia de Ecuador del dia siguiente, ya es esperable
    # (y correcto) que el dia objetivo avance uno mas -- a esas alturas
    # los partidos del dia anterior ya deberian estar resueltos de sobra.
    _con_hora_utc_fija(monkeypatch, datetime(2026, 8, 31, 18, 0))
    assert core.calcular_dia_objetivo_picks() == datetime(2026, 9, 1).date()


# ---------- Marcador de "un solo set de picks por dia" ----------

def test_marcador_dia_generado_detecta_mismo_dia(tmp_path, monkeypatch):
    archivo = tmp_path / "ultimo_dia_generado.json"
    monkeypatch.setattr(core, "ARCHIVO_MARCADOR_DIA_GENERADO", str(archivo))

    dia = datetime(2026, 9, 1).date()
    assert core.dia_ya_fue_generado(dia) is False

    core.marcar_dia_generado(dia)
    assert core.dia_ya_fue_generado(dia) is True


def test_marcador_dia_generado_no_confunde_dias_distintos(tmp_path, monkeypatch):
    archivo = tmp_path / "ultimo_dia_generado.json"
    monkeypatch.setattr(core, "ARCHIVO_MARCADOR_DIA_GENERADO", str(archivo))

    core.marcar_dia_generado(datetime(2026, 9, 1).date())
    assert core.dia_ya_fue_generado(datetime(2026, 9, 2).date()) is False


# ---------- obtener_numero_fecha ----------
# El bug real: el numero de "Fecha" (jornada) se contaba distinto segun
# que liga hubiera corrido de ultima, porque el archivo contador se
# reasignaba por liga. Ahora es un archivo unico y fijo.

def test_numero_fecha_es_secuencial_y_estable(tmp_path, monkeypatch):
    archivo = tmp_path / "contador_fechas.json"
    monkeypatch.setattr(core, "ARCHIVO_CONTADOR_FECHAS", str(archivo))

    primera = core.obtener_numero_fecha(pd.Timestamp("2026-08-21"))  # semana 1
    misma_semana = core.obtener_numero_fecha(pd.Timestamp("2026-08-23"))  # misma semana ISO
    segunda = core.obtener_numero_fecha(pd.Timestamp("2026-08-30"))  # semana siguiente

    assert primera == misma_semana  # el mismo fin de semana es la misma "Fecha"
    assert segunda == primera + 1   # la semana siguiente avanza el contador


# ---------- calcular_combinadas_multiples ----------
# El bug real (y el error que yo mismo cometi al intentar arreglarlo):
# agregar una pierna a una combinada SIEMPRE sube la cuota (nunca la baja),
# porque cada probabilidad que se multiplica es menor a 1.

def _picks_de_prueba(probabilidades):
    filas = []
    for idx, prob in enumerate(probabilidades):
        filas.append({
            "local": f"Local{idx}", "visitante": f"Visitante{idx}",
            "pick_recomendado": "Over 1.5 goles", "pick_probabilidad": prob,
            "pick_es_seguro": True, "liga": "premier_league", "fecha": "2026-09-01 18:00:00",
        })
    return pd.DataFrame(filas)


def test_cuota_sube_al_agregar_mas_piernas():
    picks = _picks_de_prueba([85, 85, 85, 85, 85])
    combinadas = core.calcular_combinadas_multiples(
        picks, cuota_objetivo=1.70, cuota_minima=1.60, max_combinadas=1, max_partidos_por_combinada=5)

    assert len(combinadas) == 1
    combinada = combinadas[0]
    # Reconstruimos la cuota que hubiera dado cada cantidad de piernas, en
    # el mismo orden en que el algoritmo las va agregando (por
    # probabilidad descendente), y confirmamos que SIEMPRE sube.
    prob_acumulada = 1.0
    cuota_anterior = 0
    for p in combinada["partidos"]:
        prob_acumulada *= p["pick_probabilidad"] / 100
        cuota_actual = 1 / prob_acumulada
        assert cuota_actual > cuota_anterior
        cuota_anterior = cuota_actual


def test_combinada_respeta_el_piso_de_cuota_minima():
    # Con picks muy seguros (85%+), el algoritmo debe poder seguir
    # agregando piernas (hasta el maximo permitido) para alcanzar el piso
    # de cuota, en vez de quedarse corta con muy pocas piernas.
    picks = _picks_de_prueba([88, 87, 86, 85, 84])
    combinadas = core.calcular_combinadas_multiples(
        picks, cuota_objetivo=1.70, cuota_minima=1.60, max_combinadas=1, max_partidos_por_combinada=5)

    assert len(combinadas) == 1
    assert combinadas[0]["cuota_combinada"] >= 1.60


# ---------- verificar_pick_individual ----------
# El mercado que realmente causo una combinada perdida (Milan/Venezia y
# LOSC/PSG, corners) -- confirmamos que la logica de verificacion evalua
# bien los mercados de goles y los dinamicos (corners/tarjetas/tiros).

@pytest.mark.parametrize("pick,fthg,ftag,esperado", [
    ("Over 1.5 goles", 2, 1, True),
    ("Over 1.5 goles", 1, 0, False),
    ("Under 2.5 goles", 1, 1, True),
    ("Under 2.5 goles", 2, 1, False),
    ("Ambos anotan - Si", 1, 1, True),
    ("Ambos anotan - Si", 2, 0, False),
    ("Doble oportunidad 1X", 1, 1, True),
    ("Doble oportunidad 1X", 0, 1, False),
])
def test_verificar_pick_individual_mercados_de_goles(pick, fthg, ftag, esperado):
    fila = pd.Series({"FTHG": fthg, "FTAG": ftag})
    assert core.verificar_pick_individual(pick, fila) == esperado


def test_verificar_pick_individual_corners():
    fila = pd.Series({"FTHG": 1, "FTAG": 1, "HC": 7, "AC": 4})
    # bool(...) porque estas funciones devuelven un booleano de numpy
    # (np.True_/np.False_), no el "True"/"False" nativo de Python.
    assert bool(core.verificar_pick_individual("Under 12.5 corners", fila)) is True
    assert bool(core.verificar_pick_individual("Over 12.5 corners", fila)) is False


def test_verificar_pick_individual_datos_faltantes_devuelve_none():
    # Si el dato del mercado (ej. tiros a puerta) todavia no llego desde
    # la fuente externa, debe devolver None (ni True ni False) -- asi la
    # combinada se queda "Pendiente" en vez de marcarse mal.
    fila = pd.Series({"FTHG": 1, "FTAG": 1, "HST": np.nan, "AST": np.nan})
    assert core.verificar_pick_individual("Over 5.5 tiros a puerta", fila) is None


# ---------- calibrar_probabilidad ----------

def test_calibrar_probabilidad_es_monotona_y_esta_acotada():
    valores = [core.calibrar_probabilidad(p) for p in [0.5, 0.6, 0.7, 0.8, 0.9]]
    assert valores == sorted(valores)  # a mas probabilidad cruda, mas probabilidad calibrada
    assert all(0 <= v <= 1 for v in valores)


# ---------- elegir_mejor_pick: el gate de inicio de temporada ----------
# El bug/feature real: los mercados extra (corners/tarjetas/tiros a
# puerta) deben exigir un umbral MAS ALTO al inicio de temporada, sin que
# eso afecte a los mercados de goles/resultado.

def _matriz_pareja():
    """Matriz de marcadores realista (Poisson independiente, ambos equipos
    con la misma fuerza) donde NINGUN mercado de goles/resultado/ambos
    anotan supera el 65% de probabilidad calibrada (el maximo real es
    ~61%) -- asi el candidato ganador en las pruebas de umbral_extra
    siempre sale limpiamente de mercados_extra, sin que un mercado de
    goles se cuele por casualidad."""
    n = 8
    lam = 1.1

    def poisson_pmf(k, lam):
        return np.exp(-lam) * lam ** k / math.factorial(k)

    m = np.array([[poisson_pmf(i, lam) * poisson_pmf(j, lam) for j in range(n)] for i in range(n)])
    return m / m.sum()


def test_umbral_extra_bloquea_mercado_extra_pero_no_afecta_a_otros():
    # elegir_mejor_pick() SIEMPRE devuelve un pick (el mejor disponible,
    # aunque ninguno pase el umbral) -- el 4to valor (cumple_umbral) es lo
    # que de verdad indica si califica como "seguro" o no.
    matriz = _matriz_pareja()
    mercados_extra = {"Over 5.5 corners": 0.80}  # calibrado ~0.77: pasa el umbral normal (0.65) pero NO el extra (0.85)

    _, _, _, cumple_normal = core.elegir_mejor_pick(matriz, umbral_minimo=0.65, mercados_extra=mercados_extra)
    _, _, _, cumple_con_gate = core.elegir_mejor_pick(
        matriz, umbral_minimo=0.65, mercados_extra=mercados_extra, umbral_extra_minimo=0.85)

    # Sin el gate de temporada, el mercado extra al 80% si califica como seguro.
    assert cumple_normal is True
    # Con el gate de temporada (necesita 85%), el mismo pick de 80% ya NO califica.
    assert cumple_con_gate is False


def test_umbral_extra_no_bloquea_si_el_mercado_extra_si_lo_supera():
    matriz = _matriz_pareja()
    mercados_extra = {"Over 5.5 corners": 0.95}  # calibrado ~0.87: supera incluso el umbral alto de temporada

    nombres, _, _, cumple_con_gate = core.elegir_mejor_pick(
        matriz, umbral_minimo=0.65, mercados_extra=mercados_extra, umbral_extra_minimo=0.85)

    assert cumple_con_gate is True
    assert nombres == ["Over 5.5 corners"]
