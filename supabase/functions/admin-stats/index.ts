// Funcion: admin-stats
// Le devuelve al admin un resumen de numeros del negocio (usuarios,
// VIP activos, ingresos del mes, etc.) -- ver obtener_estadisticas_admin()
// en sql/estadisticas_admin.sql, que hace el calculo real.
//
// Por que una funcion aparte y no una consulta directa desde el
// navegador: la tabla perfiles y pagos_procesados no tienen (ni deben
// tener) una politica de RLS que deje a un usuario cualquiera leer los
// datos de TODOS los demas -- solo los suyos propios. Verificar aqui,
// del lado del servidor, que quien pregunta es de verdad admin (leyendo
// su propio perfil con la llave de servicio) evita tener que abrir esa
// puerta en la base de datos solo para este panel.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }

  try {
    const authHeader = req.headers.get("Authorization");
    if (!authHeader) {
      return new Response(JSON.stringify({ error: "No autenticado" }), {
        status: 401,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    // Confirmamos quien es el usuario con su propia sesion (nunca
    // confiamos en nada que mande el body para decidir identidad).
    const supabaseClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      global: { headers: { Authorization: authHeader } },
    });
    const { data: { user }, error: userError } = await supabaseClient.auth.getUser();
    if (userError || !user) {
      return new Response(JSON.stringify({ error: "Usuario no valido" }), {
        status: 401,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    const { data: perfil } = await supabaseAdmin
      .from("perfiles")
      .select("es_admin")
      .eq("id", user.id)
      .maybeSingle();

    if (!perfil?.es_admin) {
      return new Response(JSON.stringify({ error: "No autorizado" }), {
        status: 403,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const { data: estadisticas, error: errorRpc } = await supabaseAdmin.rpc("obtener_estadisticas_admin");
    if (errorRpc) {
      return new Response(JSON.stringify({ error: "No se pudieron calcular las estadisticas", detalle: errorRpc }), {
        status: 500,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify(estadisticas), {
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }
});
