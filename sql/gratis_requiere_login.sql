-- Antes, un pick o combinada marcado "es_gratis" era visible para
-- CUALQUIERA que abriera la app, incluso sin haber iniciado sesion --
-- eso quitaba el incentivo para registrarse (ya recibian el contenido
-- gratis sin crear cuenta). Ahora "gratis" sigue siendo gratis, pero
-- exige estar logueado (con cualquier cuenta, no hace falta ser VIP) para
-- ver el pick/los partidos reales. Un visitante sin sesion sigue viendo
-- la cuota de las combinadas (eso no cambia, sirve de anzuelo -- ver
-- crearCombinada() en index.html, que ya maneja ese caso), pero no el
-- contenido en si.

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
  liga
from public.picks;

create or replace view public.combinadas_publicas as
select
  id,
  nombre,
  es_gratis,
  cuota_combinada,
  case
    when (es_gratis and auth.uid() is not null) or es_usuario_vip_o_admin() then partidos_json
    else (
      select jsonb_agg(jsonb_build_object('local', elem.value->>'local', 'visitante', elem.value->>'visitante'))
      from jsonb_array_elements(combinadas.partidos_json) elem
    )
  end as partidos_json,
  liga
from public.combinadas;

-- OJO: historial_combinadas_publico (combinadas YA resueltas) NO se toca
-- aqui a proposito -- fue una decision explicita anterior que una vez
-- resuelta una combinada, se muestre a todo el mundo sin importar sesion
-- ni pago (sirve de prueba social: "miren que si acertamos").
