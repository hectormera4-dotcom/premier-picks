"""Confirma que los rangos de corners y tiros a puerta estan correctos en tu copia local."""
with open("actualizar_y_predecir.py", encoding="utf-8") as f:
    contenido = f.read()

if "5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5" in contenido:
    print("Corners: rango 5.5 a 13.5 -- CORRECTO")
else:
    print("Corners: el rango NO coincide con lo esperado")

if "3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5" in contenido:
    print("Tiros a puerta: rango 3.5 a 12.5 -- CORRECTO")
else:
    print("Tiros a puerta: el rango NO coincide con lo esperado")