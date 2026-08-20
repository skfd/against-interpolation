@echo off
REM Weekly sync of the against-interpolation MapRoulette challenges:
REM refetch OSM ways, rebuild tasks, then diff-sync the live challenges.
REM Run by the kk-AgainstInterpolation scheduled task (Wednesdays 12:00).
REM
REM Needs MAPROULETTE_API_KEY (user env var) and the sibling
REM toronto-2-address-import checkout for `build`.

setlocal
cd /d "%~dp0" || exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\kk\Code\check-git-locks.ps1" -Clear

echo [%DATE% %TIME%] weekly refresh starting
python run.py fetch --force || (echo [%DATE% %TIME%] fetch FAILED & exit /b 1)
python run.py build || (echo [%DATE% %TIME%] build FAILED & exit /b 1)
python run.py refresh || (echo [%DATE% %TIME%] refresh FAILED & exit /b 1)

REM refresh updates the committed manifest.json; commit it so the repo
REM reflects the live challenge state. Fail loudly, never silently.
git add manifest.json || (echo [%DATE% %TIME%] git add FAILED & exit /b 1)
git diff --cached --quiet -- manifest.json && (
    echo [%DATE% %TIME%] no manifest changes
) || (
    git commit -m "weekly refresh: sync manifest" || (echo [%DATE% %TIME%] git commit FAILED & exit /b 1)
)
echo [%DATE% %TIME%] weekly refresh done
