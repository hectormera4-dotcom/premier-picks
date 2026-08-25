"""
Genera la misma frase con distintos niveles de "energía" (velocidad + tono)
usando la voz que elijas, para comparar cuál se siente con más chispa
sin sonar forzado.

Cómo correrlo:
    python probar_energia.py NOMBRE_DE_LA_VOZ

Ejemplo:
    python probar_energia.py es-EC-LuisNeural

Genera 3 archivos .mp3: normal, energia_media, energia_alta.
"""

import asyncio
import sys
import edge_tts

FRASE = "Analicé más de tres mil partidos de fútbol profesional."

# (etiqueta, ajuste de velocidad, ajuste de tono)
VARIANTES = [
    ("normal", "+0%", "+0Hz"),
    ("energia_media", "+12%", "+15Hz"),
    ("energia_alta", "+20%", "+30Hz"),
]


async def generar(voz, etiqueta, rate, pitch):
    archivo = f"energia_{etiqueta}_{voz}.mp3"
    try:
        communicate = edge_tts.Communicate(FRASE, voz, rate=rate, pitch=pitch)
        await communicate.save(archivo)
        print(f"OK  -> {archivo}  (rate={rate}, pitch={pitch})")
    except Exception as e:
        print(f"FALLÓ: {e}")


async def main():
    if len(sys.argv) < 2:
        print("Uso: python probar_energia.py NOMBRE_DE_LA_VOZ")
        print("Ejemplo: python probar_energia.py es-EC-LuisNeural")
        return

    voz = sys.argv[1]
    print(f"Generando 3 variantes de energía para la voz {voz}...\n")
    for etiqueta, rate, pitch in VARIANTES:
        await generar(voz, etiqueta, rate, pitch)
    print("\nListo. Compara los 3 archivos energia_*.mp3")


if __name__ == "__main__":
    asyncio.run(main())
