@echo off
rem Starts ComfyUI so phones and tablets on your Wi-Fi can open Comfy Remote.
rem ComfyUI has no password: anyone on this network can use it. Only run this on a network you trust.
cd /d "%~dp0"
set "LANIP="
for /f "usebackq delims=" %%i in (`.\python_embeded\python.exe -c "import socket;s=socket.socket(2,2);s.connect(('8.8.8.8',80));print(s.getsockname()[0])"`) do set "LANIP=%%i"
echo.
echo  Comfy Remote on this PC:    http://127.0.0.1:8188/remote
if defined LANIP echo  Comfy Remote on your phone: http://%LANIP%:8188/remote
echo  (phone and PC must be on the same Wi-Fi; allow Python through Windows Firewall if asked)
echo.
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 0.0.0.0
echo If you see this and ComfyUI did not start try updating your Nvidia Drivers to the latest. If you get a c10.dll error you need to install vc redist that you can find: https://aka.ms/vc14/vc_redist.x64.exe
pause
