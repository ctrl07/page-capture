@echo off
cd /d "%~dp0"
uv sync
uv run streamlit run app.py
pause
