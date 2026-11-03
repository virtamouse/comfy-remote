@echo off
rem Starts ComfyUI so your own devices on Tailscale can open Comfy Remote from anywhere (not the rest of your Wi-Fi).
rem Tailscale must be connected on this PC before you start this, and on the phone when you use it.
cd /d "%~dp0"
set "TS=C:\Program Files\Tailscale\tailscale.exe"
if not exist "%TS%" (
    echo Tailscale is not installed. Get it free at https://tailscale.com/download on this PC and your phone.
    pause
    exit /b 1
)
set "TSIP="
for /f "usebackq delims=" %%i in (`"%TS%" ip -4`) do set "TSIP=%%i"
if not defined TSIP (
    echo Tailscale is not connected on this PC. Open Tailscale, connect, then run this again.
    pause
    exit /b 1
)
echo.
echo  Comfy Remote on this PC:                  http://127.0.0.1:8188/remote
echo  Comfy Remote on your phone (Tailscale on): http://%TSIP%:8188/remote
echo.
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1,%TSIP%
echo If you see this and ComfyUI did not start try updating your Nvidia Drivers to the latest. If you get a c10.dll error you need to install vc redist that you can find: https://aka.ms/vc14/vc_redist.x64.exe
pause
