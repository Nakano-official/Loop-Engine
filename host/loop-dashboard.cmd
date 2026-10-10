@echo off
setlocal
REM The dashboard: every app under apps\, its runs and its output. Host-only:
REM it listens on 127.0.0.1 and never places a credential or a listening
REM socket inside the sandbox. Apps live beside this checkout (..\..\apps).
echo Open http://127.0.0.1:8443 after the server starts.
python "%~dp0dashboard\server.py" %*
