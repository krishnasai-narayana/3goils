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

:: Step 1: Export CSVs from .mdb and sync local database cache
echo [1/3] Exporting CSVs from 3G2026.mdb ...
python scripts\export_mdb.py
if %errorlevel% neq 0 (
    echo ERROR: CSV export failed. Check that:
    echo   - 3G2026.mdb is in the database\ folder
    echo   - Microsoft Access ODBC driver is installed
    echo   - pyodbc is installed: pip install pyodbc
    pause
    exit /b 1
)
echo Export complete.

echo Updating local SQLite cache ...
python scripts\sync_databases.py
echo.

:: Step 2: Stage the updated CSV files
echo [2/3] Staging changes for Git ...
git add data\*.csv
git status --short

:: Check if there is anything to commit
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo.
    echo No changes detected in data files.
    echo The CSV files are already up to date.
    echo Nothing to push.
    pause
    exit /b 0
)

:: Step 3: Commit and push
echo.
echo [3/3] Committing and pushing to GitHub ...

:: Get current date using PowerShell (wmic is deprecated/removed in newer Windows)
for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format dd-MM-yyyy"') do set COMMIT_DATE=%%D

git commit -m "Data update: %COMMIT_DATE%"

:: Pull first with rebase in case GitHub has newer commits
git pull --rebase origin main
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Pull/rebase failed. Resolve conflicts manually.
    pause
    exit /b 1
)

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