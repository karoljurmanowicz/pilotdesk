@echo off
chcp 65001 >nul
title PilotDesk - budowanie PilotDesk.exe
cd /d "%~dp0"
echo.
echo  ================================================
echo     PilotDesk - tworzenie pliku PilotDesk.exe
echo  ================================================
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python")
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if defined PY goto build
echo  Nie znaleziono Pythona - pobieram i instaluje (jednorazowo, ok. 1-2 min)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe -OutFile $env:TEMP\py312.exe"
if errorlevel 1 goto fail
"%TEMP%\py312.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
:build
echo  Przygotowuje srodowisko budowania...
%PY% -m venv .build-venv
if errorlevel 1 goto fail
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail
echo  Buduje PilotDesk.exe (ok. 1-3 min)...
python build_exe.py
if errorlevel 1 goto fail
copy /y dist\PilotDesk.exe PilotDesk.exe >nul
echo.
echo  GOTOWE!  Plik PilotDesk.exe jest w tym folderze.
echo  Uruchom go dwuklikiem i kliknij "Zainstaluj".
echo  Ten sam plik skopiuj na pozostale komputery (pendrive, chmura, e-mail).
echo.
explorer /select,"%~dp0PilotDesk.exe"
pause
exit /b 0
:fail
echo.
echo  Cos poszlo nie tak - przeczytaj komunikat powyzej.
pause
exit /b 1
