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

      const supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

      // Un pago real de Payphone sigue confirmando "Approved" para
      // siempre, aunque ya se haya usado -- sin este registro, alguien
      // podria guardar el id+clientTransactionId de un solo pago real y
      // volver a llamar a esta funcion cuantas veces quiera para
      // extender su VIP sin pagar de nuevo. Insertamos el pago aqui
      // ANTES de activar el VIP; si ya existia (mismo pago reenviado), la
      // restriccion de llave primaria lo rechaza y no se vuelve a activar.
      const { error: dedupeError } = await supabaseAdmin
        .from("pagos_procesados")
        .insert({ client_transaction_id: String(clientTransactionId) });

      if (dedupeError) {
        if (dedupeError.code === "23505") { // unique_violation: este pago ya se proceso antes
          return new Response(JSON.stringify({
            aprobado: true,
            yaProcesado: true,
            transactionStatus: data.transactionStatus,
            amount: data.amount,
          }), { headers: { ...CORS_HEADERS, "Content-Type": "application/json" } });
        }
        return new Response(JSON.stringify({ error: "Pago aprobado pero fallo verificar duplicado", detalle: dedupeError }), {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }

      const DIAS_POR_PLAN: Record<string, number> = { semana: 7, mes: 30 };
      const dias = DIAS_POR_PLAN[plan] || 30;

      // Si el usuario todavia tenia VIP vigente al momento de pagar, el
      // plan nuevo se SUMA a lo que le quedaba (en vez de reemplazarlo
      // desde ahora) -- asi no pierde dias por renovar antes de que se le
      // acabe el plan actual.
      const { data: perfilActual } = await supabaseAdmin
        .from("perfiles")
        .select("vip_hasta")
        .eq("id", userId)
        .maybeSingle();

      const ahora = Date.now();
      const vipHastaActual = perfilActual?.vip_hasta ? new Date(perfilActual.vip_hasta).getTime() : 0;
      const base = Math.max(ahora, vipHastaActual);
      const vipHasta = new Date(base + dias * 24 * 60 * 60 * 1000).toISOString();

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

      // Sistema de referidos: si quien acaba de pagar fue invitado por
      // alguien (referido_por, guardado al registrarse -- ver
      // manejar_nuevo_usuario() en la base) y todavia no le hemos dado el
      // premio a ese invitador, esta es su PRIMERA suscripcion paga real
      // (llegar hasta aqui significa que el pago con Payphone se aprobo y
      // no era un duplicado, ver la deduplicacion arriba) -- justo el
      // momento en el que dijimos que se entrega el premio, nunca antes,
      // para que una cuenta fantasma sin pagar nunca le regale VIP a nadie.
      const { data: perfilPagador } = await supabaseAdmin
        .from("perfiles")
        .select("referido_por, recompensa_referido_otorgada")
        .eq("id", userId)
        .maybeSingle();

      if (perfilPagador?.referido_por && !perfilPagador.recompensa_referido_otorgada) {
        const DIAS_PREMIO_REFERIDO = 7;
        const referenteId = perfilPagador.referido_por;

        const { data: perfilReferente } = await supabaseAdmin
          .from("perfiles")
          .select("vip_hasta")
          .eq("id", referenteId)
          .maybeSingle();

        // Misma logica de "sumar dias" que una renovacion anticipada: si el
        // invitador ya tenia VIP vigente, el premio se suma a lo que le
        // quedaba en vez de reemplazarlo desde ahora.
        const vipHastaReferenteActual = perfilReferente?.vip_hasta ? new Date(perfilReferente.vip_hasta).getTime() : 0;
        const baseReferente = Math.max(Date.now(), vipHastaReferenteActual);
        const nuevoVipHastaReferente = new Date(baseReferente + DIAS_PREMIO_REFERIDO * 24 * 60 * 60 * 1000).toISOString();

        const { error: errorPremio } = await supabaseAdmin
          .from("perfiles")
          .update({ es_vip: true, vip_hasta: nuevoVipHastaReferente })
          .eq("id", referenteId);

        // Marcamos la bandera SIN IMPORTAR si el paso anterior fallo -- el
        // premio es "mejor esfuerzo" (nunca debe tumbar la activacion del
        // VIP del que si pago, que ya se confirmo arriba), pero solo debe
        // poder dispararse una vez por cada referido, pase lo que pase.
        if (!errorPremio) {
          await supabaseAdmin
            .from("perfiles")
            .update({ recompensa_referido_otorgada: true })
            .eq("id", userId);
        } else {
          console.error("Fallo al otorgar premio de referido:", errorPremio);
        }
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