// Service Worker minimo para Picks FC.
// A proposito NO cacheamos los datos de Supabase (picks, combinadas, sesion)
// para que el usuario SIEMPRE vea la informacion mas reciente y su estado
// de sesion/VIP correcto -- esto solo habilita que la app sea "instalable".

const CACHE_NAME = "picksfc-v1";
const ARCHIVOS_APP_SHELL = ["./", "./index.html"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ARCHIVOS_APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((nombres) =>
      Promise.all(nombres.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Cualquier peticion a Supabase (datos, auth, funciones) siempre va
  // directo a la red, nunca a cache -- son datos que cambian todo el tiempo.
  if (event.request.url.includes("supabase.co")) {
    return; // dejamos que el navegador la maneje normal
  }

  // Para el resto (el archivo de la app en si), probamos la red primero
  // y solo usamos la copia guardada si no hay conexion.
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

// ---------- Notificaciones push (combinadas resueltas) ----------
// revisar_combinadas_en_vivo.py manda un push con { title, body } en
// texto plano cada vez que una combinada pendiente termina de resolverse.
self.addEventListener("push", (event) => {
  let datos = { title: "Picks FC", body: "" };
  try {
    if (event.data) datos = event.data.json();
  } catch (e) {
    if (event.data) datos.body = event.data.text();
  }

  event.waitUntil(
    self.registration.showNotification(datos.title || "Picks FC", {
      body: datos.body || "",
      icon: "./icon-192.png",
      badge: "./icon-192.png",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow("./"));
});
