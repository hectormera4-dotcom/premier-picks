-- Sistema de referidos: 7 dias VIP gratis para quien invita, entregados
-- SOLO cuando el referido hace su primera suscripcion paga real (no al
-- registrarse) -- la app no verifica el correo, asi que dar el premio en
-- el registro dejaria crear cuentas fantasma sin costo para "ganar" el
-- premio de otra persona. Ver payphone-confirm/index.ts para la logica
-- de entrega del premio.

alter table public.perfiles
  add column if not exists referido_por uuid references public.perfiles(id),
  add column if not exists recompensa_referido_otorgada boolean not null default false;

-- El "codigo" de invitacion que se comparte NO es el uuid completo (muy
-- largo para compartir a mano) -- son solo sus primeros 8 caracteres hex
-- (ver abrirModalInvitar en index.html). No se guarda como columna aparte
-- ni se le exige ser unico (evitaria un choque rarisimo de raiz, pero a
-- costo de poder bloquear el registro de una cuenta nueva por una
-- coincidencia de 8 caracteres -- preferible que sea "mejor esfuerzo": si
-- dos ids comparten los mismos 8 caracteres, el resultado es simplemente
-- que la referencia. resuelve a cualquiera de los dos, sin romper nada).
-- Esta funcion hace esa resolucion codigo -> id real, reutilizada tanto
-- por el trigger de registro (correo/contraseña) como por la funcion
-- registrar-referido (Google).
create or replace function public.buscar_id_por_codigo_referido(codigo text)
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.perfiles where substr(id::text, 1, 8) = lower(codigo) limit 1;
$$;

-- Reemplaza la funcion que ya existia (manejar_nuevo_usuario, disparada
-- por el trigger al_crear_usuario en auth.users) agregando la captura de
-- quien invito a este usuario nuevo. El codigo del invitador viaja como
-- metadata del registro (ver hacerSignup() en index.html) -- se valida
-- aqui, del lado del servidor, que tenga el formato de codigo (8 hex),
-- que no sea el propio usuario (auto-referido) y que de verdad resuelva a
-- alguien que existe; si algo no calza, simplemente queda NULL (no
-- invitado), nunca se rompe el registro de la cuenta.
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
      when new.raw_user_meta_data->>'referido_por' ~* '^[0-9a-f]{8}$'
       and lower(new.raw_user_meta_data->>'referido_por') <> substr(new.id::text, 1, 8)
      then public.buscar_id_por_codigo_referido(new.raw_user_meta_data->>'referido_por')
      else null
    end
  );
  return new;
end;
$$;
