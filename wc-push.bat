@echo off
rem WoodCraft - commit the add-in folder and push it to GitHub.
rem
rem     wc-push "what changed"
rem
rem Run it from anywhere in Command Prompt; it cd's to the add-in folder itself.
rem The first push opens a browser to sign in to GitHub - Git Credential Manager
rem remembers it after that, so every later push is silent.

setlocal

if "%~1"=="" (
    echo Usage: wc-push "what changed"
    echo   e.g. wc-push "Add Fit Handles and the config commands"
    exit /b 1
)

cd /d "%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\WoodCraft"
if errorlevel 1 exit /b 1

rem Point at the right remote, and get GitHub's latest without touching files.
git remote set-url origin https://github.com/Bassem-Tarek/WoodCraft.git
if errorlevel 1 exit /b 1
git fetch origin
if errorlevel 1 exit /b 1

rem Move HEAD to origin/main but KEEP every file exactly as it is, so the commit
rem is a clean delta against what is on GitHub rather than against the old clone
rem point this folder was created from.
git reset --mixed origin/main >nul
if errorlevel 1 exit /b 1

git add -A
if errorlevel 1 exit /b 1

git diff --cached --quiet
if not errorlevel 1 (
    echo Nothing to push - the folder already matches origin/main.
    exit /b 0
)

echo.
echo About to commit:
git diff --cached --stat
echo.

git commit -m "%~1"
if errorlevel 1 exit /b 1
git push origin HEAD:main
if errorlevel 1 exit /b 1

echo.
echo Pushed to https://github.com/Bassem-Tarek/WoodCraft
