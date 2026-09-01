@echo off
REM Refresh the host-side copies of EVERY repository the sandbox holds.
REM
REM Until this runs, everything the loop has produced lives only inside the
REM distro's VHDX. The runner pushes to /srv/loop/repo.git, but that bare repo
REM is in the same VHDX -- it protects a green step from `reset` and `clean`,
REM not from losing the disk. This is the step that puts it on another one.
REM
REM The host pulls; the sandbox never pushes outward. That is deliberate: the
REM sandbox is where generated code runs, so no credential that reaches
REM outside it may live in there.
REM
REM ONE DIRECTORY PER RUN, because a single mirror cannot hold more than one.
REM Every run creates step-S1..step-S11 -- the same tag names -- so a fetch into
REM a shared clone has to pass --force and overwrite the previous run's tags,
REM and moving `main` as well would leave the old run's commits with no ref
REM pointing at them. Unreachable objects are what `git gc` deletes, and gc runs
REM on its own inside ordinary commands. The backup would stop existing at a
REM moment nobody observed. So:
REM
REM     /srv/loop/repo.runN.git  ->  C:\dev\roop-engin\runs\run-NNN  (immutable)
REM     /srv/loop/repo.git       ->  C:\dev\roop-engin\project        (the live one)
REM
REM which is the shape the sandbox already uses for project.runN. A copy should
REM look like the thing it is a copy of.

setlocal enabledelayedexpansion

set "MIRRORROOT=C:\dev\roop-engin"
set "ARCHIVEROOT=%MIRRORROOT%\runs"
set "SSHHOST=loop-runner"

if not exist "%ARCHIVEROOT%" mkdir "%ARCHIVEROOT%"
if errorlevel 1 (
  echo cannot create archive root %ARCHIVEROOT%
  exit /b 1
)

REM One line, space separated, straight from the shell's own glob: no pipes, so
REM nothing here needs batch escaping.
set "REPOS="
for /f "delims=" %%L in ('ssh -o BatchMode^=yes %SSHHOST% "cd /srv/loop && echo repo*.git"') do set "REPOS=%%L"

if not defined REPOS (
  echo cannot reach %SSHHOST%, or /srv/loop holds no repository.
  echo   is the distro up?   loop-dev
  exit /b 1
)

echo repositories on the sandbox: %REPOS%
echo.

REM Archives BEFORE the live one, and the order is load-bearing. `repo.git` is
REM reset to whatever run it now holds, and that is only safe once the run it
REM used to hold has been captured as project.runN. Left to the glob, repo.git
REM would come first ("g" sorts before "r").
for %%R in (%REPOS%) do (
  if /i not "%%R"=="repo.git" (
    call :sync "%%R" ff
    if errorlevel 1 (
      echo FAILED: stopping before the live mirror is changed.
      exit /b 1
    )
  )
)
for %%R in (%REPOS%) do (
  if /i "%%R"=="repo.git" (
    call :sync "%%R" live
    if errorlevel 1 (
      echo FAILED: the live mirror was not synchronized.
      exit /b 1
    )
  )
)

echo.
echo done.
exit /b 0


:sync
setlocal
set "NAME=%~1"
set "MODE=%~2"
if /i "%NAME%"=="repo.git" (
  set "DEST=%MIRRORROOT%\project"
) else (
  REM repo.run4.git -> 4 -> run-004. Delayed expansion is required because
  REM this subroutine is parsed before RUNNO and PAD are assigned.
  set "RUNNO=%NAME:~8,-4%"
  set "PAD=000!RUNNO!"
  set "PAD=!PAD:~-3!"
  set "DEST=%ARCHIVEROOT%\run-!PAD!"
)

if not exist "%DEST%\.git" (
  echo   %NAME%  ^-^>  %DEST%   [clone]
  git clone --quiet "ssh://%SSHHOST%/srv/loop/%NAME%" "%DEST%"
  if errorlevel 1 exit /b 1
  exit /b 0
)

echo   %NAME%  ^-^>  %DEST%   [fetch]
git -C "%DEST%" fetch --prune --prune-tags --tags --force origin
if errorlevel 1 exit /b 1

if /i "%MODE%"=="live" (
  REM Not --ff-only. Each run starts a fresh repo.git with an unrelated root
  REM commit, so the live mirror can never fast-forward; it is replaced. Safe
  REM only because the loop above has already captured the previous run.
  REM
  REM `clean` as well, or files from a run that had them would sit here as
  REM untracked leftovers and a mirror would stop being a faithful copy.
  REM Consequence, and it is the reason this is spelled out: do not keep
  REM anything of your own in project\ -- it is rebuilt, not maintained.
  git -C "%DEST%" reset --hard --quiet origin/main
  if errorlevel 1 exit /b 1
  git -C "%DEST%" clean -fdq
  if errorlevel 1 exit /b 1
) else (
  REM An archive never changes, so this can only ever fast-forward -- and if it
  REM somehow does not, something rewrote history that is supposed to be frozen,
  REM which should stop the script rather than be forced past.
  git -C "%DEST%" merge --ff-only --quiet origin/main
  if errorlevel 1 (
    echo      REFUSED: %DEST% diverged from an archive that cannot change.
    exit /b 1
  )
)
git -C "%DEST%" log --oneline -1
exit /b 0
