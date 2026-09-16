-- Vulnerabilidad real encontrada: la politica RLS "usuarios actualizan su
-- propio perfil" en la tabla perfiles solo restringe QUE FILA se puede
-- tocar (auth.uid() = id), no QUE COLUMNAS. Postgres RLS no distingue
-- columnas por si solo -- eso significa que cualquier usuario logueado
-- podia mandar un UPDATE directo a la API REST de Supabase (sin pasar
-- por la app ni por ninguna Edge Function) y ponerse es_vip = true,
-- es_admin = true, o inventarse un vip_hasta lejano en el futuro, sobre
-- su propia fila.
--
-- Arreglo: un trigger BEFORE UPDATE que revierte cualquier intento de
-- cambiar las columnas sensibles, EXCEPTO cuando quien escribe es el
-- propio backend (Edge Functions / pipeline), que usa la llave de
-- servicio y por eso corre con el rol "service_role" en vez de
-- "authenticated". No se bloquea con un error -- simplemente se ignora
-- el cambio a esas columnas en particular, dejando pasar cualquier otro
-- cambio legitimo que el usuario si puede hacer sobre su propio perfil
-- (username, etc.).

create or replace function public.proteger_columnas_sensibles_perfiles()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  -- El backend (Edge Functions con SUPABASE_SERVICE_ROLE_KEY, o el
  -- pipeline) ignora RLS y corre como service_role -- a esos SI se les
  -- deja escribir estas columnas normalmente.
  if auth.role() = 'service_role' then
    return new;
  end if;

  new.es_vip := old.es_vip;
  new.vip_hasta := old.vip_hasta;
  new.es_admin := old.es_admin;
  new.referido_por := old.referido_por;
  new.recompensa_referido_otorgada := old.recompensa_referido_otorgada;

  return new;
end;
$$;

drop trigger if exists trigger_proteger_columnas_sensibles_perfiles on public.perfiles;

create trigger trigger_proteger_columnas_sensibles_perfiles
before update on public.perfiles
for each row
execute function public.proteger_columnas_sensibles_perfiles();
