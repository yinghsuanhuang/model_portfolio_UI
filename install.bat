@echo off
REM ============================================================
REM  首次安裝（Windows）— 只需執行一次
REM  使用方式：把整個資料夾複製到 Windows 後，「雙擊」本檔。
REM  完成後，日後啟動請改雙擊 start.bat。
REM ============================================================
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ============================================================
echo   模型投組平台 - 首次安裝
echo ============================================================
echo.

REM ── 1) 檢查 Python ──
where python >nul 2>nul
if errorlevel 1 (
    echo [!] 找不到 Python。請先安裝 Python 3.11 並勾選 "Add to PATH"。
    echo     下載： https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── 2) 建立虛擬環境（已存在則略過）──
if exist "venv\Scripts\activate.bat" (
    echo [v] venv 已存在，略過建立。
) else (
    echo [.] 建立虛擬環境 venv ...
    python -m venv venv
    if errorlevel 1 ( echo [!] 建立 venv 失敗。 & pause & exit /b 1 )
)

REM ── 3) 安裝套件 ──
call venv\Scripts\activate.bat
echo [.] 升級 pip ...
python -m pip install --upgrade pip
echo [.] 安裝套件（依 requirements.txt，可能需幾分鐘）...
pip install -r requirements.txt
if errorlevel 1 ( echo [!] 套件安裝失敗，請檢查網路後重試。 & pause & exit /b 1 )

REM ── 4) 檢查必要的機密檔（不隨程式碼附帶，需手動放入）──
echo.
echo ------------------------------------------------------------
if not exist ".env" (
    echo [!] 缺少 .env（API 金鑰）。請放入專案根目錄，內容範例：
    echo        GEMINI_API_KEY=你的金鑰
    echo        ANTHROPIC_API_KEY=你的金鑰
)
if not exist "data\TAA_RawData.xlsx" (
    echo [!] 缺少 data\TAA_RawData.xlsx，請放入 data 資料夾。
)
if not exist "data\SAA_RawData.xlsx" (
    echo [!] 缺少 data\SAA_RawData.xlsx，請放入 data 資料夾。
)
echo ------------------------------------------------------------
echo.
echo [v] 安裝完成。日後啟動請雙擊 start.bat。
echo.
pause
