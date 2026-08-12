import pandas as pd
df = pd.read_csv("premier_league_combinado.csv")
columnas_buscadas = ["HC", "AC", "HY", "AY", "HST", "AST", "Referee"]
print("Columnas en tu archivo:", list(df.columns))
print()
for col in columnas_buscadas:
    if col in df.columns:
        no_vacios = df[col].notna().sum()
        print(f"  {col}: SI esta presente ({no_vacios} de {len(df)} filas con dato)")
    else:
        print(f"  {col}: NO esta en el archivo")