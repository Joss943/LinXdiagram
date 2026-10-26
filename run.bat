@echo off
rem Lance LinXdiagram depuis les sources sous Windows (Python 3.11+ et PyQt6 requis :
rem   py -m pip install PyQt6 cryptography).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 -P -m linxdiagram %*) || (start "" pythonw -P -m linxdiagram %*)
