-- Ver payphone-confirm/index.ts para el detalle del problema que esto
-- corrige. Resumen: la deduplicacion de pagos vivia SOLO en
-- client_transaction_id, un valor que el propio llamador arma y controla
-- por completo (formato "{userId}_{plan}_{timestamp}") -- eso permitia
-- reenviar el mismo pago aprobado por Payphone una y otra vez, cada vez
-- con un client_transaction_id nuevo inventado, para extender el VIP
-- infinitas veces sin volver a pagar. Ahora tambien deduplicamos por el
-- ID de transaccion REAL de Payphone (numerico, no lo elige el llamador),
-- que es el identificador que de verdad no se puede repetir sin que haya
-- un pago nuevo detras.
alter table public.pagos_procesados
  add column if not exists payphone_transaction_id bigint;

-- unique constraint aparte (no "add column ... unique") para que esto no
-- falle si la columna ya existiera de una corrida anterior de este mismo
-- script.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'pagos_procesados_payphone_transaction_id_key'
  ) then
    alter table public.pagos_procesados
      add constraint pagos_procesados_payphone_transaction_id_key unique (payphone_transaction_id);
  end if;
end $$;
