-- Panel de estadisticas para el admin: cuantos usuarios, cuantos VIP,
-- ingresos del mes, etc. Ver admin-stats/index.ts (la funcion que expone
-- esto de forma segura, verificando que quien pregunta sea admin de
-- verdad) e index.html (vista "Estadisticas" del menu, solo visible para
-- perfilActual.es_admin).

-- pagos_procesados ya existia (para evitar procesar un mismo pago de
-- Payphone dos veces, ver payphone-confirm/index.ts) pero solo guardaba
-- el id de transaccion, sin quien pago, que plan ni cuanto -- no alcanzaba
-- para calcular ingresos. Estas columnas se llenan desde ahora en
-- adelante (ver el UPDATE nuevo en payphone-confirm/index.ts); los pagos
-- de ANTES de este cambio quedan con estos campos en null, asi que los
-- ingresos "historicos" que muestra el panel solo cuentan desde aqui.
alter table public.pagos_procesados
  add column if not exists user_id uuid references public.perfiles(id),
  add column if not exists plan text,
  add column if not exists monto_centavos integer;

create or replace function public.obtener_estadisticas_admin()
returns json
language sql
stable
security definer
set search_path = public
as $$
  select json_build_object(
    'usuarios_totales', (select count(*) from public.perfiles),
    'usuarios_vip_activos', (select count(*) from public.perfiles where vip_hasta > now()),
    'usuarios_nuevos_mes', (select count(*) from public.perfiles where fecha_registro >= date_trunc('month', now())),
    'pagos_mes', (select count(*) from public.pagos_procesados where procesado_en >= date_trunc('month', now())),
    'ingresos_mes_centavos', (select coalesce(sum(monto_centavos), 0) from public.pagos_procesados where procesado_en >= date_trunc('month', now())),
    'ingresos_totales_centavos', (select coalesce(sum(monto_centavos), 0) from public.pagos_procesados),
    'pagos_por_plan_mes', (
      select coalesce(json_object_agg(plan, cantidad), '{}'::json)
      from (
        select plan, count(*) as cantidad
        from public.pagos_procesados
        where procesado_en >= date_trunc('month', now()) and plan is not null
        group by plan
      ) t
    ),
    'referidos_premiados_total', (select count(*) from public.perfiles where recompensa_referido_otorgada = true)
  );
$$;

-- CRITICO: por defecto Supabase le da permiso de EXECUTE en funciones
-- nuevas del schema public a "anon" y "authenticated" -- sin este REVOKE,
-- CUALQUIER usuario logueado podria llamar a esta funcion directo por la
-- API REST (no solo el admin) y ver los ingresos del negocio. La unica
-- verificacion real de "es admin de verdad" vive en admin-stats/index.ts
-- (que usa la llave de servicio, no afectada por este REVOKE).
revoke execute on function public.obtener_estadisticas_admin() from public, anon, authenticated;
