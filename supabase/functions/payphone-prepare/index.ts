// Funcion: payphone-prepare
// Se llama cuando el usuario hace clic en "Hazte VIP". Prepara el cobro
// con Payphone de forma segura (el token nunca toca el navegador) y
// devuelve el link de pago para redirigir al usuario.
//
// NOTA: usamos Axios en vez de fetch() para hablar con la API de Payphone,
// por recomendacion directa de su equipo de soporte -- reportaron
// inconsistencias conocidas de fetch() en entornos como Supabase Edge
// Functions al consumir su API.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import axios from "npm:axios@1.7.7";

const PAYPHONE_TOKEN = Deno.env.get("PAYPHONE_TOKEN")!;
const PAYPHONE_STOREID = Deno.env.get("PAYPHONE_STOREID")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const SITE_URL = "https://hectormera4-dotcom.github.io/premier-picks/";

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

    // Verificamos quien es el usuario que esta pidiendo esto, usando su
    // propia sesion (no exponemos nada, solo confirmamos su identidad)
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

    // El plan viene del frontend: "dia" (acceso solo a la fecha actual, $5)
    // o "mes" (suscripcion mensual completa, $15)
    let plan = "mes";
    try {
      const body = await req.json();
      if (body && body.plan === "semana") plan = "semana";
    } catch (_e) {
      // Si no mandan body, usamos "mes" por defecto
    }

    const PLANES: Record<string, { amount: number; reference: string }> = {
      semana: { amount: 500, reference: "Acceso VIP por 1 semana - Picks FC" },
      mes: { amount: 1500, reference: "Suscripcion VIP mensual - Picks FC" },
    };
    const elegido = PLANES[plan];

    // El clientTransactionId incluye el id del usuario y el plan elegido,
    // para saber a quien y por cuanto tiempo activarle el VIP al confirmar.
    // Payphone exige maximo 50 caracteres, asi que usamos un formato corto:
    // {uuid}_{s o m}_{timestamp en base36}
    const planCorto = plan === "semana" ? "s" : "m";
    const timestampCorto = Date.now().toString(36);
    const clientTransactionId = `${user.id}_${planCorto}_${timestampCorto}`;

    const bodyPayphone = {
      amount: elegido.amount,
      amountWithoutTax: elegido.amount,
      clientTransactionId,
      currency: "USD",
      storeId: PAYPHONE_STOREID,
      reference: elegido.reference,
      responseUrl: SITE_URL,
    };

    try {
      const respuestaAxios = await axios.post(
        "https://pay.payphonetodoesposible.com/api/button/Prepare",
        bodyPayphone,
        {
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${PAYPHONE_TOKEN}`,
          },
          timeout: 15000,
        }
      );

      const data = respuestaAxios.data;
      return new Response(JSON.stringify({
        payWithCard: data.payWithCard,
        payWithPayPhone: data.payWithPayPhone,
      }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });

    } catch (errAxios: any) {
      // Si Payphone respondio pero con error (4xx/5xx), Axios lo guarda en err.response
      if (errAxios.response) {
        return new Response(JSON.stringify({
          error: "Error de Payphone",
          status_http_de_payphone: errAxios.response.status,
          detalle: errAxios.response.data,
        }), {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
      // Error de red/timeout, sin respuesta de Payphone
      return new Response(JSON.stringify({
        error: "No se pudo conectar con Payphone: " + errAxios.message,
      }), {
        status: 502,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }
});