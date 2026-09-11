-- Agrega los escudos de equipo a la tabla "picks" (picks individuales de
-- "Picks del dia"), para poder mostrarlos en la app -- ver
-- actualizar_y_predecir.py (subir_picks_supabase) y crearTarjeta() en
-- index.html. Ya se habian agregado antes para las combinadas
-- (sql/gratis_requiere_login.sql).
alter table public.picks
  add column if not exists escudo_local text,
  add column if not exists escudo_visitante text;
