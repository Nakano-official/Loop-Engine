@echo off
REM Refresh the host-side copy of the sandbox repository.
REM
REM Until this runs, everything the loop has produced lives only inside the
REM distro's VHDX. The runner pushes to /srv/loop/repo.git, but that bare repo
REM is in the same VHDX -- it protects a green step from `reset` and `clean`,
REM not from losing the disk. This is the step that puts it on another one.
REM
REM The host pulls; the sandbox never pushes outward. That is deliberate: the
REM sandbox is where generated code runs, so no credential that reaches
REM outside it may live in there.

setlocal
set MIRROR=C:\dev\roop-engin\project

if not exist "%MIRROR%\.git" (
  echo no clone at %MIRROR% -- make one first:
  echo   git clone ssh://loop-runner/srv/loop/repo.git "%MIRROR%"
  exit /b 1
)

REM --prune-tags --force, because this is a mirror and not a working copy: it
REM should say what repo.git says. Without them a step-<id> tag that has moved
REM -- a step re-run after a reset, or a repository rebuilt from scratch -- is
REM refused as "would clobber existing tag" and the whole fetch fails, which is
REM how a backup quietly stops being one.
git -C "%MIRROR%" fetch --prune --prune-tags --tags --force origin
if errorlevel 1 exit /b 1
git -C "%MIRROR%" merge --ff-only origin/main
if errorlevel 1 exit /b 1

echo.
git -C "%MIRROR%" log --oneline -5
