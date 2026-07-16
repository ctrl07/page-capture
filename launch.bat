@echo off
cd /d "%~dp0"
where uv >nul 2>nul || powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv sync
uv run playwright install chromium
uv run streamlit run app.py
pause
