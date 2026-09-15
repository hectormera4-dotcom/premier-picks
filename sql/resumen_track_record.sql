-- Resumen agregado del track record real de la app (picks individuales Y
-- combinadas), pedido por el usuario para mostrar algo como "100 de 150
-- picks acertados" en la seccion de Historial.
--
-- Los picks individuales se resuelven por separado en cada una de las 8
-- ligas (cada una lleva su propio historial_picks_<liga>.csv, ver
-- ARCHIVO_HISTORIAL_PICKS en actualizar_y_predecir.py) y nunca se habian
-- sumado -- esta tabla guarda SOLO el total agregado (2 numeros por fila:
-- resueltos y acertados), no el detalle partido por partido. Combinadas
-- ya tenia su detalle completo publico (historial_combinadas_publico) y
-- el frontend ya calculaba este mismo resumen al vuelo desde ahi -- se
-- sube aqui tambien, nada mas por consistencia (una sola tabla chiquita
-- para los 2 resumenes, en vez de 2 mecanismos distintos).
create table if not exists public.resumen_track_record (
  tipo text primary key,  -- 'picks' o 'combinadas'
  total_resueltos integer not null default 0,
  total_acertados integer not null default 0,
  actualizado_en timestamptz not null default now()
);

alter table public.resumen_track_record enable row level security;

-- Son solo 2 numeros agregados, nada sensible -- se puede leer sin
-- necesidad de una vista intermedia (a diferencia de picks/combinadas,
-- que si esconden datos VIP detras de una vista).
revoke all on public.resumen_track_record from anon, authenticated;
grant select on public.resumen_track_record to anon, authenticated;

-- Solo el pipeline (con la llave de servicio, que ignora RLS) escribe
-- aqui -- no hace falta una policy de INSERT/UPDATE para anon/authenticated.
