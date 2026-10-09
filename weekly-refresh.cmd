@echo off
REM Weekly sync of the against-interpolation MapRoulette challenges, per city:
REM refetch OSM ways, rebuild tasks, then diff-sync the live challenges.
REM Run by the kk-AgainstInterpolation scheduled task (Wednesdays 12:00).
REM
REM Toronto always runs. Another city runs only once it has challenges, i.e.
REM once `run.py --city <city> create` has written manifest.<city>.json.
REM One city failing does not skip the next; the run exits 1 if any failed.
REM
REM Needs MAPROULETTE_API_KEY (user env var), the sibling city checkouts
REM (toronto-2-address-import, guelph-address-import) for `build`, plus a
REM stored GitHub credential that Credential Manager can hand over without
REM prompting.

setlocal
cd /d "%~dp0" || exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\kk\Code\check-git-locks.ps1" -Clear

echo [%DATE% %TIME%] weekly refresh starting
set "FAILED=0"
call :sync toronto manifest.json
if exist manifest.guelph.json (
    call :sync guelph manifest.guelph.json
) else (
    echo [%DATE% %TIME%] guelph: no manifest.guelph.json yet, skipped
)

REM refresh updates the committed manifests; commit them so the repo reflects
REM the live challenge state. Fail loudly, never silently.
git add manifest*.json || (echo [%DATE% %TIME%] git add FAILED & exit /b 1)
git diff --cached --quiet -- manifest*.json && (
    echo [%DATE% %TIME%] no manifest changes
) || (
    git commit -m "weekly refresh: sync manifest" -- manifest*.json || (echo [%DATE% %TIME%] git commit FAILED & exit /b 1)
)

REM Push so the public repo reflects the live challenge state. The task runs
REM unattended at midday, so never let a credential prompt hang it -- fail
REM loudly instead and let next week's run send both commits.
set GIT_TERMINAL_PROMPT=0
git -c credential.interactive=false push origin main || (echo [%DATE% %TIME%] git push FAILED & exit /b 1)

if %FAILED%==1 (
    echo [%DATE% %TIME%] weekly refresh done, with failures
    exit /b 1
)
echo [%DATE% %TIME%] weekly refresh done
exit /b 0

:sync
REM %1 = city, %2 = its manifest (unused here; named for the reader)
echo [%DATE% %TIME%] %1: sync starting
python run.py --city %1 fetch --force || (echo [%DATE% %TIME%] %1: fetch FAILED & set "FAILED=1" & exit /b 1)
python run.py --city %1 build || (echo [%DATE% %TIME%] %1: build FAILED & set "FAILED=1" & exit /b 1)
python run.py --city %1 refresh || (echo [%DATE% %TIME%] %1: refresh FAILED & set "FAILED=1" & exit /b 1)
echo [%DATE% %TIME%] %1: sync done
exit /b 0
