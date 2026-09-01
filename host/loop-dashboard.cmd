@echo off
setlocal
REM Host-only operator console. It reads the pulled project mirror and never
REM places a credential or a listening socket inside the solver sandbox.
set "PROJECT=%~dp0..\..\project"
if not exist "%PROJECT%\plan" (
  echo Project mirror not found: %PROJECT%
  echo Run host\loop-pull.cmd first.
  exit /b 1
)
echo Open http://127.0.0.1:8765 after the server starts.
python "%~dp0dashboard\server.py" --project "%PROJECT%"
