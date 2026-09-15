-- Indicador de calidad de datos para "Picks del dia" (ligas domesticas) --
-- mismo concepto que calidad_datos en analisis_champions (completo/
-- limitado), reemplaza el badge "Verificacion mas lenta" que no le gusto
-- al usuario. 'limitado' = alguno de los 2 equipos todavia lleva pocos
-- partidos jugados esta temporada (arranque de temporada), 'completo' en
-- cualquier otro caso -- misma señal real que ya usaba el pipeline para
-- exigir un umbral mas alto en corners/tarjetas/tiros al inicio de
-- temporada (ver es_inicio_temporada en generar_picks), ahora tambien
-- expuesta al usuario en vez de quedarse solo interna.
alter table public.picks
  add column if not exists calidad_datos text not null default 'completo';

-- IMPORTANTE: va AL FINAL de la lista en picks_publicos -- Postgres no
-- permite insertar columnas nuevas en medio de una vista existente con
-- CREATE OR REPLACE VIEW (falla con "cannot change name of view column").
create or replace view public.picks_publicos as
select
  id,
  fecha,
  local,
  visitante,
  es_gratis,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then pick_recomendado else null::text end as pick_recomendado,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then pick_probabilidad else null::numeric end as pick_probabilidad,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then pick_cuota_aprox else null::numeric end as pick_cuota_aprox,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then pick_es_seguro else null::boolean end as pick_es_seguro,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then es_combo else null::boolean end as es_combo,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then mercados_json else null::jsonb end as mercados_json,
  liga,
  escudo_local,
  escudo_visitante,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then marcadores_probables else null::jsonb end as marcadores_probables,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then explicacion_ia else null::jsonb end as explicacion_ia,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then calidad_datos else null::text end as calidad_datos
from public.picks;
