-- Agrega Handicap asiatico y Handicap europeo al panel de analisis de
-- Champions League. A diferencia de corners/tarjetas/tiros/faltas (que
-- SI necesitan una fuente de datos que no existe gratis para competencias
-- europeas -- ver el comentario en analisis_champions.sql), estos 2
-- mercados se derivan directo de la misma matriz de goles que Champions
-- League ya calcula, asi que no dependen de ninguna fuente de datos
-- nueva.
--
-- A diferencia de las 8 ligas domesticas (que muestran varias lineas por
-- partido en el panel desplegable), aqui solo se guarda UNA linea
-- central por partido y por tipo de handicap (la mas pareja, offset=0
-- sobre el centro que ya calcula calcular_mercados_handicap_asiatico/
-- europeo) -- el panel de Champions League ya muestra TODOS los mercados
-- de una vez en la tarjeta (sin "Ver mas"), asi que no tiene sentido
-- saturarlo con 4 lineas de handicap por partido.
alter table public.analisis_champions
  add column if not exists handicap_asiatico_linea numeric,
  add column if not exists handicap_asiatico_local numeric,
  add column if not exists handicap_asiatico_visitante numeric,
  add column if not exists handicap_europeo_linea integer,
  add column if not exists handicap_europeo_local numeric,
  add column if not exists handicap_europeo_empate numeric,
  add column if not exists handicap_europeo_visitante numeric;

-- Postgres no deja insertar columnas en medio de un CREATE OR REPLACE
-- VIEW ya existente (solo agregar al final) -- por eso las columnas
-- nuevas van al final del select, igual que ya se hizo antes en
-- gratis_requiere_login.sql. El orden no afecta nada en el codigo
-- (index.html las lee por nombre).
create or replace view public.analisis_champions_publico as
select
  id,
  fecha,
  local,
  visitante,
  escudo_local,
  escudo_visitante,
  es_gratis,
  orden,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then prob_local else null::numeric end as prob_local,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then prob_empate else null::numeric end as prob_empate,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then prob_visitante else null::numeric end as prob_visitante,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then doble_op_1x else null::numeric end as doble_op_1x,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then doble_op_x2 else null::numeric end as doble_op_x2,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then over_25 else null::numeric end as over_25,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then under_25 else null::numeric end as under_25,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then btts_si else null::numeric end as btts_si,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then btts_no else null::numeric end as btts_no,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then calidad_datos else null::text end as calidad_datos,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_asiatico_linea else null::numeric end as handicap_asiatico_linea,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_asiatico_local else null::numeric end as handicap_asiatico_local,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_asiatico_visitante else null::numeric end as handicap_asiatico_visitante,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_europeo_linea else null::integer end as handicap_europeo_linea,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_europeo_local else null::numeric end as handicap_europeo_local,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_europeo_empate else null::numeric end as handicap_europeo_empate,
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then handicap_europeo_visitante else null::numeric end as handicap_europeo_visitante
from public.analisis_champions;

grant select on public.analisis_champions_publico to anon, authenticated;
