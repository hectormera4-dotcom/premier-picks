-- Seccion nueva y separada de "picks/combinadas": un panel de analisis
-- de Champions League (unica competencia europea gratis en football-data.org --
-- Europa League necesitaria un plan de pago). A diferencia de los picks
-- normales, aqui NO se "cura" ni se filtra por umbral de seguridad -- se
-- muestran TODOS los partidos de la jornada actual, ordenados de mas a
-- menos confiable, con el porcentaje real de CADA mercado de goles (no
-- solo el mas seguro). Nunca se combinan en combinadas ni entran al pool
-- de picks curados -- Champions League mezcla equipos de calidad y
-- cantidad de historial muy desiguales entre si (un debutante en la
-- competencia vs. un equipo con años de historial), asi que no se le
-- exige el mismo estandar de "seguro" que a las ligas domesticas.
--
-- Solo mercados de GOLES (1X2, doble oportunidad, over/under, ambos
-- anotan) -- football-data.co.uk no cubre competencias europeas, no hay
-- fuente gratuita de corners/tarjetas/tiros a puerta para esto.
create table if not exists public.analisis_champions (
  id bigint generated always as identity primary key,
  fecha timestamptz not null,
  local text not null,
  visitante text not null,
  escudo_local text,
  escudo_visitante text,
  prob_local numeric,
  prob_empate numeric,
  prob_visitante numeric,
  doble_op_1x numeric,
  doble_op_x2 numeric,
  over_25 numeric,
  under_25 numeric,
  btts_si numeric,
  btts_no numeric,
  -- 'completo' = ambos equipos tienen historial real; 'limitado' = al
  -- menos uno de los dos esta usando la fuerza conservadora por defecto
  -- (sin historial suficiente en la competencia) -- se le avisa al
  -- usuario para que sepa que este partido en particular es menos
  -- confiable que uno con datos completos.
  calidad_datos text not null default 'completo',
  es_gratis boolean not null default false,
  orden integer not null default 0,
  actualizado_en timestamptz not null default now()
);

alter table public.analisis_champions enable row level security;

-- Igual que picks/combinadas: nadie lee la tabla real directo (evita
-- filtrar los datos de los partidos VIP), solo la vista publica de abajo.
revoke all on public.analisis_champions from anon, authenticated;

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
  case when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then calidad_datos else null::text end as calidad_datos
from public.analisis_champions;

grant select on public.analisis_champions_publico to anon, authenticated;
