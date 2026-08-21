// Funcion: payphone-confirm
// Payphone redirige aqui al usuario despues del pago (via la pagina web,
// que llama a esta funcion con los parametros que recibio). Confirma con
// Payphone que el pago sea real y aprobado, y si lo es, activa el VIP.
//
// NOTA: usamos Axios en vez de fetch() para hablar con la API de Payphone,
// por recomendacion directa de su equipo de soporte.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import axios from "npm:axios@1.7.7";

const PAYPHONE_TOKEN = Deno.env.get("PAYPHONE_TOKEN")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
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
    const { id, clientTransactionId } = await req.json();

    if (!id || !clientTransactionId) {
      return new Response(JSON.stringify({ error: "Faltan parametros id o clientTransactionId" }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    let data: any;
    try {
      const respuestaAxios = await axios.post(
        "https://pay.payphonetodoesposible.com/api/button/V2/Confirm",
        { id: Number(id), clientTxId: clientTransactionId },
        {
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${PAYPHONE_TOKEN}`,
          },
          timeout: 15000,
        }
      );
      data = respuestaAxios.data;
    } catch (errAxios: any) {
      if (errAxios.response) {
        return new Response(JSON.stringify({
          error: "Error confirmando con Payphone",
          status_http_de_payphone: errAxios.response.status,
          detalle: errAxios.response.data,
        }), {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({
        error: "No se pudo conectar con Payphone: " + errAxios.message,
      }), {
        status: 502,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const aprobado = data.statusCode === 3 && data.transactionStatus === "Approved";

    if (aprobado) {
      // El clientTransactionId tiene la forma "{userId}_{d o m}_{timestamp}"
      const partes = String(clientTransactionId).split("_");
      const userId = partes[0];
      const planCorto = partes[1] || "m";
      const plan = planCorto === "s" ? "semana" : "mes";

      const DIAS_POR_PLAN: Record<string, number> = { semana: 7, mes: 30 };
      const dias = DIAS_POR_PLAN[plan] || 30;
      const vipHasta = new Date(Date.now() + dias * 24 * 60 * 60 * 1000).toISOString();

      const supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
      const { error: updateError } = await supabaseAdmin
        .from("perfiles")
        .update({ es_vip: true, vip_hasta: vipHasta })
        .eq("id", userId);

      if (updateError) {
        return new Response(JSON.stringify({ error: "Pago aprobado pero fallo activar VIP", detalle: updateError }), {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
    }

    return new Response(JSON.stringify({
      aprobado,
      transactionStatus: data.transactionStatus,
      amount: data.amount,
    }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }
});