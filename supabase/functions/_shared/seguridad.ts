// Cabeceras CORS y limitador de tasa basico, compartidos por todas las
// Edge Functions de Picks FC.
//
// El limitador es EN MEMORIA, por instancia -- Supabase puede levantar
// varias instancias de una misma funcion bajo trafico alto, asi que esto
// no es un limite distribuido perfecto (dos instancias distintas no se
// enteran una de la otra). Aun asi frena de verdad los picos de abuso o
// bots que golpean repetidamente la misma instancia (el caso mas comun
// de spam), que es justo el problema que esto busca mitigar -- no
// pretende ser una defensa anti-DDoS a nivel de infraestructura.

const SITE_ORIGIN = "https://hectormera4-dotcom.github.io";

export const CORS_HEADERS = {
  "Access-Control-Allow-Origin": SITE_ORIGIN,
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const intentosPorClave = new Map<string, number[]>();

// Clave de rate-limit recomendada: IP del que llama (o "desconocido" si
// el proxy no manda la cabecera, para no reventar la funcion por eso).
export function claveDesdeRequest(req: Request): string {
  return req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "desconocido";
}

// true si esta clave ya supero maxIntentos dentro de los ultimos
// ventanaMs milisegundos (y registra este intento de todas formas, para
// que intentos repetidos sigan contando mientras dura el bloqueo).
export function excedeLimite(clave: string, maxIntentos: number, ventanaMs: number): boolean {
  const ahora = Date.now();
  const intentosPrevios = (intentosPorClave.get(clave) || []).filter((t) => ahora - t < ventanaMs);
  intentosPrevios.push(ahora);
  intentosPorClave.set(clave, intentosPrevios);

  // Evita que el Map crezca sin limite si hay muchas IPs distintas --
  // limpieza oportunista, no hace falta que sea exacta.
  if (intentosPorClave.size > 5000) {
    for (const [k, tiempos] of intentosPorClave) {
      if (tiempos.every((t) => ahora - t > ventanaMs)) intentosPorClave.delete(k);
    }
  }

  return intentosPrevios.length > maxIntentos;
}

export function respuestaLimiteExcedido(): Response {
  return new Response(JSON.stringify({ error: "Demasiadas solicitudes, intenta de nuevo en un momento." }), {
    status: 429,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}
