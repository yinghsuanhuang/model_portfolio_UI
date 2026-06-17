@echo off
REM ============================================================
REM  一鍵啟動模型投組平台（Windows）
REM  使用方式：直接「雙擊」這個檔案即可，不需打任何指令。
REM  視窗會自動開啟系統網頁；用完關閉這個黑視窗即可結束。
REM ============================================================

REM 切換到這個 .bat 所在的資料夾（不論放在哪台電腦、哪個位置都適用）
cd /d "%~dp0"

REM 啟用 Python 虛擬環境
if not exist "venv\Scripts\activate.bat" (
    echo.
    echo [!] 找不到 venv 環境，系統尚未安裝完成。
    echo     請先「雙擊 install.bat」完成首次安裝後，再啟動本檔。
    echo.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

REM 啟動網頁介面
echo.
echo 正在啟動系統，請稍候，瀏覽器會自動打開操作畫面...
echo （要關閉系統時，直接關掉這個黑色視窗即可）
echo.
streamlit run ui/app.py

pause
