-- Cuotas reales de casas de apuestas verificadas (the-odds-api.com, plan
-- gratis) para el mercado 1X2 -- reemplaza la cuota estimada
-- (1/probabilidad - margen) SOLO cuando el pick recomendado es Local
-- gana/Empate/Visitante gana en solitario (el unico mercado que el plan
-- gratis de esa API cubre para todas las ligas de forma sostenible, ver
-- el comentario junto a obtener_cuotas_reales() en actualizar_y_predecir.py).
-- Cuando no hay cuota real disponible (partido no cubierto, o el pick es
-- de otro mercado), cuota_es_real queda en false y pick_cuota_aprox sigue
-- siendo la estimacion de siempre -- nunca se inventa una cuota real.
alter table public.picks
  add column if not exists cuota_es_real boolean not null default false,
  add column if not exists casa_apuestas text;

-- IMPORTANTE: van AL FINAL de la lista en picks_publicos -- Postgres no
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
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then calidad_datos else null::text end as calidad_datos,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then cuota_es_real else null::boolean end as cuota_es_real,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then casa_apuestas else null::text end as casa_apuestas
from public.picks;
