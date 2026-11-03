@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Comfy Remote installer
rem ----------------------------------------------------------------
rem  Comfy Remote - 1-click installer for ComfyUI Windows portable
rem  Put this file in your ComfyUI_windows_portable folder (next to run_nvidia_gpu.bat)
rem  and double-click it. Safe to run again: it only adds what is missing.
rem  Options: /yes  /update  /skip-models  /dry-run
rem ----------------------------------------------------------------
set "REPO=https://github.com/shyt47/comfy-remote"
set "BRANCH=main"

rem Find ComfyUI portable: this folder, or up to three folders above (when run from inside the package).
set "ROOT="
for %%P in ("%~dp0." "%~dp0.." "%~dp0..\.." "%~dp0..\..\..") do (
  if not defined ROOT if exist "%%~fP\python_embeded\python.exe" if exist "%%~fP\ComfyUI\main.py" set "ROOT=%%~fP"
)
if not defined ROOT (
  echo [ERROR] ComfyUI portable not found.
  echo Put this file in your ComfyUI_windows_portable folder ^(the one with run_nvidia_gpu.bat^) and run it again.
  pause
  exit /b 1
)
set "PY=%ROOT%\python_embeded\python.exe"
set "NODE=%ROOT%\ComfyUI\custom_nodes\comfy-remote"
echo ComfyUI portable: %ROOT%

rem Turn /flags into --flags for install.py
setlocal EnableDelayedExpansion
set "OPTS="
for %%A in (%*) do (
  if /I "%%~A"=="/yes"         set "OPTS=!OPTS! --yes"
  if /I "%%~A"=="/update"      set "OPTS=!OPTS! --update"
  if /I "%%~A"=="/skip-models" set "OPTS=!OPTS! --skip-models"
  if /I "%%~A"=="/dry-run"     set "OPTS=!OPTS! --dry-run"
)

rem Get or update the Comfy Remote package itself.
if exist "%NODE%\.git" (
  echo Updating Comfy Remote...
  git -C "%NODE%" pull --ff-only
) else if not exist "%NODE%\install.py" (
  git --version >nul 2>&1
  if not errorlevel 1 (
    echo Downloading Comfy Remote with git...
    git clone --depth 1 "%REPO%" "%NODE%"
  ) else (
    echo Downloading Comfy Remote...
    set "TMPD=%TEMP%\comfy-remote-%RANDOM%"
    mkdir "!TMPD!"
    curl -L --ssl-no-revoke -o "!TMPD!\cr.zip" "%REPO%/archive/refs/heads/%BRANCH%.zip"
    tar -xf "!TMPD!\cr.zip" -C "!TMPD!"
    move "!TMPD!\comfy-remote-%BRANCH%" "%NODE%" >nul
    rmdir /s /q "!TMPD!"
  )
)
if not exist "%NODE%\install.py" (
  echo [ERROR] Could not download Comfy Remote from %REPO%
  echo Check your internet connection and try again.
  pause
  exit /b 1
)

"%PY%" -s "%NODE%\install.py" --root "%ROOT%" !OPTS!
echo.
pause
