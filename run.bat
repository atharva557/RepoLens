@echo off
REM ===================================================================
REM  RepoLens - quick launch (Windows)
REM
REM  Starts the FastAPI backend and the Vite frontend in their own
REM  windows, waits until the API answers, then opens the dashboard.
REM
REM    run.bat          dev mode  (uvicorn --reload + vite dev server)
REM    run.bat api      backend only
REM    run.bat build    production build, served by vite preview
REM
REM  Close either spawned window (or press Ctrl+C in it) to stop that
REM  service. MongoDB is optional - without it the app falls back to
REM  the JSON cache and still runs.
REM ===================================================================
setlocal
title RepoLens Launcher
cd /d "%~dp0"

set "API_URL=http://127.0.0.1:8000"
set "WEB_URL=http://localhost:5173"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=dev"

echo.
echo  RepoLens launcher  [mode: %MODE%]
echo  ------------------------------------------------

REM --- prerequisites ------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo  ERROR: 'python' is not on your PATH.
    echo         Install Python 3.13+ and re-run.
    pause
    exit /b 1
)

if not "%MODE%"=="api" (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo  ERROR: 'npm' is not on your PATH.
        echo         Install Node.js, or run:  run.bat api
        pause
        exit /b 1
    )
)

REM --- optional virtualenv ------------------------------------------
if exist "venv\Scripts\activate.bat" (
    echo  [env] activating venv
    call "venv\Scripts\activate.bat"
) else if exist ".venv\Scripts\activate.bat" (
    echo  [env] activating .venv
    call ".venv\Scripts\activate.bat"
)

REM --- pick an interpreter that has the project's dependencies --------
REM  'python' on PATH may be an unrelated venv that happens to have FastAPI
REM  but not GitPython. That starts a server which serves already-cached
REM  repos and then fails on every new one with a baffling "no cached
REM  commits", so require GitPython here rather than discovering it later.
set "PY=python"
%PY% -c "import git, fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 goto pyok

set "PY=py -3"
%PY% -c "import git, fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 goto pyok

echo  ERROR: no Python found with the project's dependencies
echo         ^(needs GitPython + fastapi + uvicorn^).
echo.
echo         'python' currently resolves to:
where python
echo.
echo         Install them:   python -m pip install -r requirements.txt
pause
exit /b 1

:pyok
for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.executable)"') do set "PYEXE=%%i"
echo  [env] interpreter: %PYEXE%

REM  non-fatal: without pymongo the API silently uses the JSON cache instead
REM  of MongoDB, which looks like "my data disappeared".
%PY% -c "import pymongo" >nul 2>&1
if errorlevel 1 echo  [warn] pymongo not installed - the API will use the JSON cache, not MongoDB.

REM --- .env sanity ---------------------------------------------------
if not exist ".env" (
    echo  [warn] no .env found - defaults apply. Tools 2/3 need GITHUB_TOKEN.
    echo         Copy .env.example to .env to configure.
)

REM --- frontend dependencies (first run) ------------------------------
if not "%MODE%"=="api" (
    if not exist "frontend\node_modules" (
        echo  [npm] installing frontend dependencies ^(first run, may take a minute^)...
        pushd frontend
        call npm install
        if errorlevel 1 (
            echo  ERROR: npm install failed.
            popd
            pause
            exit /b 1
        )
        popd
    )
)

REM --- start the API --------------------------------------------------
REM  "%~dp0." - the trailing dot keeps the closing quote from being escaped
REM  by the backslash that %~dp0 always ends with.
REM  --reload-dir: without it the reloader watches the WHOLE project, so the
REM  thousands of files a clone drops into data\cache\clones\ restart the
REM  server MID-ANALYSIS, wiping the in-memory job registry (the dashboard
REM  then polls a job the server no longer remembers).
echo  [api] starting on %API_URL%  ^(docs at %API_URL%/docs^)
start "RepoLens API" /d "%~dp0." cmd /k %PY% -m uvicorn api.main:app --reload --reload-dir api --reload-dir core --reload-dir pipeline --reload-dir tools --reload-dir config

REM --- wait for the API to answer /health -----------------------------
echo  [api] waiting for it to come up...
set /a tries=0
:waitapi
set /a tries+=1
curl -s -o NUL "%API_URL%/health"
if not errorlevel 1 goto apiup
if %tries% geq 40 (
    echo  [warn] API did not answer after 40s - check the "RepoLens API" window.
    goto apidone
)
timeout /t 1 /nobreak >nul
goto waitapi

:apiup
echo  [api] up.
:apidone

if "%MODE%"=="api" (
    echo.
    echo  Backend running. Swagger docs: %API_URL%/docs
    start "" "%API_URL%/docs"
    goto end
)

REM --- start the frontend ---------------------------------------------
if "%MODE%"=="build" (
    echo  [web] building production bundle...
    pushd frontend
    call npm run build
    if errorlevel 1 (
        echo  ERROR: build failed.
        popd
        pause
        exit /b 1
    )
    popd
    echo  [web] serving the build with vite preview
    start "RepoLens Frontend (preview)" /d "%~dp0frontend" cmd /k npm run preview
    set "WEB_URL=http://localhost:4173"
) else (
    echo  [web] starting dev server on %WEB_URL%
    start "RepoLens Frontend" /d "%~dp0frontend" cmd /k npm run dev
)

REM --- open the dashboard ----------------------------------------------
echo  [web] waiting for the dev server...
timeout /t 4 /nobreak >nul
start "" "%WEB_URL%"

echo.
echo  ------------------------------------------------
echo   Dashboard : %WEB_URL%
echo   API docs  : %API_URL%/docs
echo.
echo   Two windows opened ("RepoLens API" / "RepoLens Frontend").
echo   Close them, or press Ctrl+C inside, to stop the app.
echo  ------------------------------------------------

:end
endlocal
