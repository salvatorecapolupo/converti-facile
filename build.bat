@echo off
setlocal
cd /d "%~dp0"

echo === ConvertiFacile 1.1 - build ===
py -3 -m venv .venv || goto :err
call .venv\Scripts\activate || goto :err
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt || goto :err

echo.
echo Prova rapida delle conversioni...
python selftest.py || goto :err

python icon.py || goto :err
pyinstaller --noconfirm --clean ConvertiFacile.spec || goto :err

echo.
echo EXE creato in: dist\ConvertiFacile.exe
pause
exit /b 0

:err
echo.
echo ERRORE: build interrotta. Leggi i messaggi qui sopra.
pause
exit /b 1
