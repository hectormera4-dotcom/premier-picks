@echo off
cd /d C:\Users\Personal\Desktop\ligapro-picks
call venv\Scripts\activate.bat
python actualizar_y_predecir.py >> log_actualizacion.txt 2>&1