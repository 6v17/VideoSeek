@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
if "%~1"=="" goto usage

set "PYTHON="
for %%P in (
  "%USERPROFILE%\miniconda3\envs\VideoSeek\python.exe"
  "%USERPROFILE%\anaconda3\envs\VideoSeek\python.exe"
  "%LOCALAPPDATA%\miniconda3\envs\VideoSeek\python.exe"
  "C:\ProgramData\miniconda3\envs\VideoSeek\python.exe"
  "C:\ProgramData\anaconda3\envs\VideoSeek\python.exe"
) do (
  if not defined PYTHON if exist "%%~P" set "PYTHON=%%~P"
)
if not defined PYTHON (
  where python >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
  echo Python not found. Use the VideoSeek conda env, then run this bat again.
  exit /b 1
)

"%PYTHON%" "%~dp0import_runtime_resources.py" %*
exit /b %ERRORLEVEL%

:usage
echo Close VideoSeek first. Pass files that are already on disk.
echo   scripts\import_runtime_resources.bat --status
echo   scripts\import_runtime_resources.bat model.zip ffmpeg.exe
exit /b 2
