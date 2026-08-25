"""
Genera las 5 líneas de narración final del video de Picks FC, con la voz
y el nivel de energía que ya elegiste (es-EC-LuisNeural, rate +20%, pitch +30Hz).

Cómo correrlo:
    python generar_narracion_final.py

Genera 5 archivos .mp3 en esta misma carpeta, uno por sección. Súbelos
al chat cuando terminen y los sincronizo con el video.
"""

import asyncio
import edge_tts

VOZ = "es-EC-LuisNeural"
RATE = "+20%"
PITCH = "+30Hz"

LINEAS = [
    ("seccion1_gancho", "Analicé más de tres mil partidos de fútbol profesional."),
    ("seccion2_montaje", "Con lo cual poco a poco fui creando esta app, donde: se armó el modelo, se diseñó la interfaz, se logueó todo el sistema, y todo fue tomando forma."),
    ("seccion3_distincion", "No es magia. Todo esto está respaldado con datos reales de las diferentes ligas."),
    ("seccion4_recorrido", "Aqui encontrarás: picks diarios, combinadas hechas con inteligencia artificial, y todo organizado para las diferentes ligas."),
    ("seccion5_cierre", "Puedes entrar ahora mismo ingresando al link que ya se encuentra en mi perfil."),
]

async def generar(nombre, texto):
    archivo = f"narracion_{nombre}.mp3"
    communicate = edge_tts.Communicate(texto, VOZ, rate=RATE, pitch=PITCH)
    await communicate.save(archivo)
    print(f"OK -> {archivo}")


async def main():
    print(f"Generando narración final con {VOZ} (rate={RATE}, pitch={PITCH})...\n")
    for nombre, texto in LINEAS:
        await generar(nombre, texto)
    print("\nListo. Sube los 5 archivos narracion_*.mp3 al chat.")


if __name__ == "__main__":
    asyncio.run(main())
