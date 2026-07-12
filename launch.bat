@echo off
cd /d "%~dp0"
uv sync
streamlit run app.py
pause
