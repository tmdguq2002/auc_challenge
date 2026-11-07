@echo off
rem LawEdit build (Windows). Usage: build\build_exe.bat
setlocal
if "%SRC%"=="" set SRC=%~dp0..
set VENV=%USERPROFILE%\lawedit-build\venv
set WORK=%USERPROFILE%\lawedit-build
robocopy "%SRC%\lawedit" "%WORK%\src\lawedit" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS >nul
copy /Y "%SRC%\run_lawedit.py" "%WORK%\src\" >nul
if not exist "%WORK%\src\build" mkdir "%WORK%\src\build"
copy /Y "%SRC%\build\lawedit.spec" "%WORK%\src\build\" >nul
copy /Y "%SRC%\build\make_icon.py" "%WORK%\src\build\" >nul
copy /Y "%SRC%\build\make_icons.py" "%WORK%\src\build\" >nul
cd /d "%WORK%\src"
"%VENV%\Scripts\python.exe" build\make_icon.py || exit /b 1
"%VENV%\Scripts\python.exe" build\make_icons.py || exit /b 1
"%VENV%\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "%WORK%\dist" --workpath "%WORK%\work" build\lawedit.spec || exit /b 1
echo BUILD OK: %WORK%\dist
