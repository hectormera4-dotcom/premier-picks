import pandas as pd
import glob

# Busca automáticamente todos los archivos que empiecen con "pl_" en la carpeta actual
archivos = glob.glob("pl_*.csv")

if not archivos:
    print("No se encontraron archivos que empiecen con 'pl_' en esta carpeta.")
    print("Verifica que los CSV estén en la misma carpeta que este script y que los hayas renombrado.")
else:
    print(f"Archivos encontrados: {archivos}\n")

    lista_dataframes = []
    for archivo in archivos:
        df = pd.read_csv(archivo)
        df["archivo_origen"] = archivo
        lista_dataframes.append(df)
        print(f"=== {archivo} ===")
        print(f"Partidos: {len(df)}")
        print(f"Columnas disponibles: {list(df.columns)[:15]}...")
        print(f"Rango de fechas: {df['Date'].min()} a {df['Date'].max()}\n")

    # Combina todo en un solo dataset
    datos_completos = pd.concat(lista_dataframes, ignore_index=True)
    print(f"TOTAL combinado: {len(datos_completos)} partidos")

    # Revisa si hay datos faltantes en las columnas clave
    columnas_clave = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
    print("\nDatos faltantes en columnas clave:")
    print(datos_completos[columnas_clave].isnull().sum())

    # Guarda el dataset combinado y limpio
    datos_completos.to_csv("premier_league_combinado.csv", index=False)
    print("\nGuardado como 'premier_league_combinado.csv'")