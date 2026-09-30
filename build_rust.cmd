@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_rust.ps1" %*
set "BUILD_EXIT=%ERRORLEVEL%"
echo.
if "%BUILD_EXIT%"=="0" (
    echo Build completed successfully.
) else (
    echo Build failed. See the error above.
)
pause
exit /b %BUILD_EXIT%
