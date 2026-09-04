-- Sistema de referidos: 7 dias VIP gratis para quien invita, entregados
-- SOLO cuando el referido hace su primera suscripcion paga real (no al
-- registrarse) -- la app no verifica el correo, asi que dar el premio en
-- el registro dejaria crear cuentas fantasma sin costo para "ganar" el
-- premio de otra persona. Ver payphone-confirm/index.ts para la logica
-- de entrega del premio.

alter table public.perfiles
  add column if not exists referido_por uuid references public.perfiles(id),
  add column if not exists recompensa_referido_otorgada boolean not null default false;

-- Reemplaza la funcion que ya existia (manejar_nuevo_usuario, disparada
-- por el trigger al_crear_usuario en auth.users) agregando la captura de
-- quien invito a este usuario nuevo. El id del invitador viaja como
-- metadata del registro (ver hacerSignup() en index.html) -- se valida
-- aqui, del lado del servidor, que sea un uuid con formato valido, que no
-- sea el mismo usuario (auto-referido) y que exista de verdad en
-- perfiles; si algo no calza, simplemente queda NULL (no invitado), nunca
-- se rompe el registro de la cuenta.
create or replace function public.manejar_nuevo_usuario()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.perfiles (id, email, es_admin, referido_por)
  values (
    new.id,
    new.email,
    new.email = 'hectormera4@gmail.com',
    case
      when new.raw_user_meta_data->>'referido_por' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       and new.raw_user_meta_data->>'referido_por' <> new.id::text
      then (select p.id from public.perfiles p where p.id = (new.raw_user_meta_data->>'referido_por')::uuid)
      else null
    end
  );
  return new;
end;
$$;
