-- Tabla para guardar las suscripciones a notificaciones push. No esta
-- ligada a un usuario especifico (cualquier visitante puede activarlas,
-- este logueado o no -- las notificaciones de "combinada resuelta" son
-- genericas, no muestran picks VIP).
CREATE TABLE push_subscripciones (
  id bigint generated always as identity primary key,
  endpoint text NOT NULL UNIQUE,
  suscripcion_json jsonb NOT NULL,
  creado_en timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE push_subscripciones ENABLE ROW LEVEL SECURITY;

-- Cualquiera puede suscribirse (insertar su propia suscripcion) desde el
-- navegador -- pero nadie desde el navegador puede LEER, MODIFICAR ni
-- BORRAR suscripciones (ni las suyas ni las de nadie mas). Solo el
-- backend (llave de servicio, usada por revisar_combinadas_en_vivo.py)
-- puede leerlas para mandar los push, y borrar las que ya vencieron.
CREATE POLICY "cualquiera puede suscribirse a notificaciones" ON push_subscripciones
  FOR INSERT TO anon, authenticated WITH CHECK (true);
