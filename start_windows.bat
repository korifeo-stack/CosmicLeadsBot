@echo off
setlocal

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo [!] Created .env from .env.example. Fill BOT_TOKEN and ADMIN_CHAT_ID, then run again.
  exit /b 1
)

python bot.py
