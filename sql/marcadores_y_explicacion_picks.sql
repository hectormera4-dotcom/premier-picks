-- Dos campos nuevos para "Picks del dia" (picks individuales), inspirados
-- en un panel de una app parecida que el usuario revisó:
--
-- 1. marcadores_probables: los marcadores exactos mas probables del
--    partido (ej. "2-0" 14.9%). No es un dato nuevo -- Dixon-Coles ya
--    calcula la probabilidad de CADA marcador exacto para poder sumar los
--    mercados de goles (ver matriz_marcadores en actualizar_y_predecir.py),
--    aqui solo se expone tal cual.
--
-- 2. explicacion_ia: un par de frases explicando por que el modelo
--    favorece a un equipo, usando SOLO numeros que ya calculamos nosotros
--    (goles esperados del propio Dixon-Coles, indices de ataque/defensa de
--    calcular_fuerzas). A proposito no se llama "xG" ni "ELO" -- no
--    tenemos esas fuentes, seria fingir un dato que no existe.
alter table public.picks
  add column if not exists marcadores_probables jsonb,
  add column if not exists explicacion_ia jsonb;

-- IMPORTANTE: igual que escudo_local/escudo_visitante, estas columnas van
-- AL FINAL de la lista en picks_publicos -- Postgres no permite insertar
-- columnas nuevas en medio de una vista existente con CREATE OR REPLACE
-- VIEW (falla con "cannot change name of view column"). El orden no afecta
-- nada en el codigo (index.html las lee por nombre).
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
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then explicacion_ia else null::jsonb end as explicacion_ia
from public.picks;
