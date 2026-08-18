// Funcion: payphone-prepare
// Se llama cuando el usuario hace clic en "Hazte VIP". Prepara el cobro
// con Payphone de forma segura (el token nunca toca el navegador) y
// devuelve el link de pago para redirigir al usuario.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

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
      if (body && body.plan === "dia") plan = "dia";
    } catch (_e) {
      // Si no mandan body, usamos "mes" por defecto
    }

    const PLANES: Record<string, { amount: number; reference: string }> = {
      dia: { amount: 500, reference: "Acceso VIP a la fecha actual - Picks FC" },
      mes: { amount: 1500, reference: "Suscripcion VIP mensual - Picks FC" },
    };
    const elegido = PLANES[plan];

    // El clientTransactionId incluye el id del usuario y el plan elegido,
    // para saber a quien y por cuanto tiempo activarle el VIP al confirmar
    const clientTransactionId = `${user.id}__${plan}__${Date.now()}`;

    const bodyPayphone = {
      amount: elegido.amount,
      amountWithoutTax: elegido.amount,
      clientTransactionId,
      currency: "USD",
      storeId: PAYPHONE_STOREID,
      reference: elegido.reference,
      responseUrl: SITE_URL,
    };

    const resp = await fetch("https://pay.payphonetodoesposible.com/api/button/Prepare", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${PAYPHONE_TOKEN}`,
      },
      body: JSON.stringify(bodyPayphone),
    });

    const data = await resp.json();

    if (!resp.ok) {
      return new Response(JSON.stringify({ error: "Error de Payphone", detalle: data }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({
      payWithCard: data.payWithCard,
      payWithPayPhone: data.payWithPayPhone,
    }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }
});