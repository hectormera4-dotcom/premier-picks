// Funcion: payphone-confirm
// Payphone redirige aqui al usuario despues del pago (via la pagina web,
// que llama a esta funcion con los parametros que recibio). Confirma con
// Payphone que el pago sea real y aprobado, y si lo es, activa el VIP.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

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

    const resp = await fetch("https://pay.payphonetodoesposible.com/api/button/V2/Confirm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${PAYPHONE_TOKEN}`,
      },
      body: JSON.stringify({ id: Number(id), clientTxId: clientTransactionId }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      return new Response(JSON.stringify({ error: "Error confirmando con Payphone", detalle: data }), {
        status: 400,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    const aprobado = data.statusCode === 3 && data.transactionStatus === "Approved";

    if (aprobado) {
      // El clientTransactionId tiene la forma "{userId}__{plan}__{timestamp}"
      const partes = String(clientTransactionId).split("__");
      const userId = partes[0];
      const plan = partes[1] || "mes";

      const DIAS_POR_PLAN: Record<string, number> = { dia: 5, mes: 30 };
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