// Funcion: registrar-referido
// Complementa al trigger manejar_nuevo_usuario() (ver sql/referidos.sql):
// ese trigger ya guarda quien invito a un usuario nuevo cuando se
// registra con correo/contraseña (el link ?ref=<id> viaja como metadata
// del signUp). PERO signInWithOAuth (el boton "Continuar con Google") no
// permite mandar esa metadata al crear la cuenta -- Google es quien
// decide que datos trae la cuenta nueva, no nosotros. Esta funcion es el
// mismo registro, hecho aparte, justo despues de que el usuario vuelve a
// la pagina ya logueado con Google.
//
// Reglas de seguridad (para que esto no se pueda usar para fabricar
// referidos falsos en cuentas viejas, o para cambiar de invitador
// despues de ya tener uno):
//   1. Solo se puede fijar referido_por si TODAVIA esta en null -- una
//      vez fijado, queda fijo para siempre (ni el usuario ni nadie mas
//      lo puede volver a cambiar despues).
//   2. Solo funciona en los primeros minutos desde que se creo la
//      cuenta (fecha_registro reciente) -- una cuenta que ya lleva rato
//      existiendo no puede "reclamar" un invitador con el que nunca tuvo
//      nada que ver.
//   3. El invitador tiene que ser un usuario real que ya existe, y no
//      puede ser la misma persona (auto-referido).
// Con esto sumado a que el PREMIO en si solo se entrega cuando el
// referido paga de verdad (ver payphone-confirm/index.ts), esto no abre
// ninguna forma de conseguir VIP gratis sin que alguien pague algo real.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const MINUTOS_VENTANA_REGISTRO = 15;
const REGEX_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

    // Igual que en payphone-prepare: usamos la propia sesion del usuario
    // para confirmar quien es, nunca confiamos en un id que mande el body.
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

    const body = await req.json().catch(() => ({}));
    const referidoPor = String(body?.referido_por || "");

    if (!REGEX_UUID.test(referidoPor)) {
      return new Response(JSON.stringify({ error: "referido_por invalido" }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }
    if (referidoPor.toLowerCase() === user.id.toLowerCase()) {
      return new Response(JSON.stringify({ error: "No puedes ser tu propio invitador" }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    const { data: perfilPropio } = await supabaseAdmin
      .from("perfiles")
      .select("referido_por, fecha_registro")
      .eq("id", user.id)
      .maybeSingle();

    if (!perfilPropio) {
      return new Response(JSON.stringify({ error: "Perfil no encontrado" }), {
        status: 404,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }
    if (perfilPropio.referido_por) {
      // Ya tenia uno (probablemente ya se registro por correo con el
      // trigger normal) -- no es un error, simplemente no hay nada que
      // hacer.
      return new Response(JSON.stringify({ ok: true, yaTenia: true }), {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const minutosDesdeRegistro = (Date.now() - new Date(perfilPropio.fecha_registro).getTime()) / 60000;
    if (minutosDesdeRegistro > MINUTOS_VENTANA_REGISTRO) {
      return new Response(JSON.stringify({ error: "Cuenta ya no es lo bastante nueva para vincular un referido" }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const { data: perfilInvitador } = await supabaseAdmin
      .from("perfiles")
      .select("id")
      .eq("id", referidoPor)
      .maybeSingle();
    if (!perfilInvitador) {
      return new Response(JSON.stringify({ error: "El invitador no existe" }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    // El "is null" en el WHERE es la ultima linea de defensa contra una
    // condicion de carrera (dos llamadas casi al mismo tiempo): solo la
    // primera que llegue de verdad escribe algo.
    const { error: updateError } = await supabaseAdmin
      .from("perfiles")
      .update({ referido_por: referidoPor })
      .eq("id", user.id)
      .is("referido_por", null);

    if (updateError) {
      return new Response(JSON.stringify({ error: "No se pudo vincular el referido", detalle: updateError }), {
        status: 500,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ ok: true }), {
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }
});
