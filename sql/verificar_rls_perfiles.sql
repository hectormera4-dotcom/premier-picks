-- Verificacion/refuerzo de seguridad para la tabla "perfiles" (revision
-- integral de seguridad). Esta tabla guarda email, es_admin, es_vip,
-- vip_hasta, referido_por de CADA usuario -- si un usuario cualquiera
-- pudiera leer las filas de OTROS usuarios (no solo la suya), cualquiera
-- logueado podria ver quien es admin, quien es VIP, y el email de todos
-- los demas usuarios de la app.
--
-- No pude inspeccionar la politica RLS actual de esta tabla desde aqui
-- (se creo antes del historial visible de este proyecto, fuera del
-- repositorio) -- este script es seguro de correr sin importar cual sea
-- el estado actual: solo REEMPLAZA la politica de lectura para dejarla en
-- el estado correcto (cada quien solo puede leer/editar su propia fila),
-- sin tocar ninguna otra tabla ni romper nada si ya estaba bien.
--
-- Si el panel de administrador (ver admin-stats/index.ts) o cualquier
-- otra parte de la app dejaron de funcionar despues de correr esto, es
-- señal de que dependian de una politica mas permisiva -- avisame antes
-- de nada.

alter table public.perfiles enable row level security;

drop policy if exists "usuarios pueden ver su propio perfil" on public.perfiles;
create policy "usuarios pueden ver su propio perfil" on public.perfiles
  for select to authenticated
  using (auth.uid() = id);

drop policy if exists "usuarios pueden editar su propio perfil" on public.perfiles;
create policy "usuarios pueden editar su propio perfil" on public.perfiles
  for update to authenticated
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- A proposito NO hay politica de INSERT ni DELETE para anon/authenticated
-- -- las filas nuevas las crea unicamente el trigger manejar_nuevo_usuario
-- (security definer, no pasa por RLS), y nadie debe poder borrar su
-- propio perfil desde el navegador sin pasar por un flujo controlado.
