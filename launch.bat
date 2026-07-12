@echo off
cd /d "%~dp0"
echo Installing/checking dependencies...
pip install -r requirements.txt >nul 2>&1
echo Launching Page Capture...
streamlit run app.py
pause
