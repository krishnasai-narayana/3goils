@echo off
:: ─────────────────────────────────────────────────────────────────
:: 3G OILS Dashboard - Data Update Script
:: Run this whenever the 3G2026.mdb file is updated with new data.
:: It exports CSVs, commits, and pushes to GitHub automatically.
:: ─────────────────────────────────────────────────────────────────

echo.
echo ===================================================
echo  3G OILS Dashboard - Data Update
echo ===================================================
echo.

:: Make paths work even when this file is launched from another directory.
cd /d "%~dp0"

:: Use the default Python if ready; otherwise use the existing Anaconda
:: install and add its DLL directories to PATH for SQLite.
set "PYTHON=python"
python -c "import pyodbc, pandas, sqlite3; assert 'Microsoft Access Driver (*.mdb, *.accdb)' in pyodbc.drivers()" >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramData%\Anaconda3\python.exe" (
        set "PATH=%ProgramData%\Anaconda3;%ProgramData%\Anaconda3\Library\bin;%ProgramData%\Anaconda3\Scripts;%PATH%"
        set "PYTHON=%ProgramData%\Anaconda3\python.exe"
    )
)
echo Using Python command: %PYTHON%
%PYTHON% -c "import pyodbc, pandas, sqlite3; assert 'Microsoft Access Driver (*.mdb, *.accdb)' in pyodbc.drivers()" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python needs pyodbc, pandas, and a working SQLite module.
    echo Install dependencies with: python -m pip install pyodbc pandas
    pause
    exit /b 1
)

:: Step 1: Export CSVs from .mdb and sync local database cache
echo [1/3] Exporting CSVs from 3G2026.mdb ...
%PYTHON% scripts\export_mdb.py
if %errorlevel% neq 0 (
    echo ERROR: CSV export failed. Check that:
    echo   - 3G2026.mdb is in the database\ folder
    echo   - Microsoft Access ODBC driver is installed
    echo   - The selected Python has pyodbc and pandas installed
    pause
    exit /b 1
)
echo Export complete.

echo Updating local SQLite cache ...
%PYTHON% scripts\sync_databases.py
if %errorlevel% neq 0 (
    echo ERROR: Local database cache update failed. No changes will be staged.
    pause
    exit /b 1
)
echo.

:: Step 2: Stage the updated CSV files
echo [2/3] Staging changes for Git ...
git add data\*.csv
git status --short

:: Check if there is anything to commit
git diff --cached --quiet -- data\*.csv
if %errorlevel% equ 0 (
    echo.
    echo No new changes detected in data files.
    echo Checking for previously committed changes that still need pushing.
) else (
    :: Step 3: Commit updated CSV files
    echo.
    echo [3/3] Committing data changes ...

    :: Get current date using PowerShell (wmic is deprecated/removed in newer Windows)
    for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format dd-MM-yyyy"') do set COMMIT_DATE=%%D

    git commit -m "Data update: %COMMIT_DATE%" --only -- data\*.csv
    if errorlevel 1 (
        echo.
        echo ERROR: Data commit failed. No pull or push was attempted.
        pause
        exit /b 1
    )
)

:: Rebase local commits; temporarily preserve unrelated working-tree edits.
echo.
echo Synchronizing local commits with GitHub ...
git pull --rebase --autostash origin main
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Pull/rebase failed. Resolve conflicts, then rerun this script.
    pause
    exit /b 1
)

for /f %%C in ('git rev-list --count origin/main..HEAD') do set AHEAD_COUNT=%%C
if "%AHEAD_COUNT%"=="0" (
    echo.
    echo No pending commits to push. Local branch is up to date.
    pause
    exit /b 0
)

echo Pushing %AHEAD_COUNT% pending commit(s) to GitHub ...
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Push failed. Check your internet connection
    echo and GitHub credentials.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo  Done! Data pushed to GitHub.
echo  Streamlit Cloud will auto-update in ~1 minute.
echo  https://3goils.streamlit.app
echo ===================================================
echo.
pause