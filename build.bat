@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYVER=3.12.8"
set "PYEXE="

echo === ConvertiFacile 1.1 - build ===

rem 1) Python gia' installato (3.11 o superiore, con tkinter)
for %%V in (3.13 3.12 3.11) do (
  if not defined PYEXE (
    py -%%V -c "import tkinter" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)

rem 2) Python locale scaricato in un'esecuzione precedente
if not defined PYEXE if exist "%CD%\.python\python.exe" set PYEXE="%CD%\.python\python.exe"

rem 3) Nessun Python: lo scarico e lo installo SOLO in questa cartella (.python)
if not defined PYEXE (
  echo Python non trovato: lo scarico da python.org e lo installo in .python ^(circa 30 MB, senza amministratore, non tocca il resto del PC^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe' -OutFile 'python-setup.exe'" || goto :err
  start /wait "" python-setup.exe /quiet InstallAllUsers=0 TargetDir="%CD%\.python" Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0 PrependPath=0 AssociateFiles=0 Include_pip=1 Include_tcltk=1
  del python-setup.exe >nul 2>&1
  if not exist "%CD%\.python\python.exe" goto :err
  set PYEXE="%CD%\.python\python.exe"
)

echo Uso: %PYEXE%
if not exist ".venv\Scripts\python.exe" ( %PYEXE% -m venv .venv || goto :err )
set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pip install --upgrade pip || goto :err
"%VPY%" -m pip install -r requirements.txt || goto :err

echo.
echo Prova rapida delle conversioni...
"%VPY%" selftest.py || goto :err

"%VPY%" icon.py || goto :err
"%VPY%" -m PyInstaller --noconfirm --clean ConvertiFacile.spec || goto :err

echo.
echo EXE creato in: dist\ConvertiFacile.exe
pause
exit /b 0

:err
echo.
echo ERRORE: build interrotta. Leggi i messaggi qui sopra.
pause
exit /b 1
