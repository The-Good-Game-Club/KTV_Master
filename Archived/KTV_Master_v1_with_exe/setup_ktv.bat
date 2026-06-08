@echo off
title KTV Karaoke Generator - 安裝程式
chcp 65001 >nul

REM ── 到期檢查（2027-06-05）────────────────────────
set year=%date:~10,4%
set month=%date:~4,2%
set day=%date:~7,2%

if %year% GTR 2027 goto EXPIRED
if %year% EQU 2027 if %month% GTR 06 goto EXPIRED
if %year% EQU 2027 if %month% EQU 06 if %day% GTR 05 goto EXPIRED
goto CHECK_CONTINUE

:EXPIRED
echo ============================================
echo  ❌ 安裝程式已到期
echo ============================================
echo.
echo 此安裝程式已於 2027-06-05 到期。
echo 請向作者索取最新版本。
echo.
pause
exit /b 1

:CHECK_CONTINUE
echo ============================================
echo  🎤 KTV Karaoke Generator - 安裝程式
echo ============================================
echo.

REM ── 檢查／安裝 Python ────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/4] Python 未安裝，正在安裝內建 Python 3.12…
    if exist "%~dp0python-installer.exe" (
        echo 執行靜默安裝（約 1-2 分鐘）…
        "%~dp0python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0
        if %errorlevel% equ 0 (
            echo [✓] Python 3.12 安裝成功！
        ) else (
            echo [❌] Python 安裝失敗（請手動下載 https://www.python.org/downloads/）
            pause
            exit /b 1
        )
    ) else (
        echo [❌] 找不到 python-installer.exe（請手動下載 https://www.python.org/downloads/）
        pause
        exit /b 1
    )
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set pyver=%%v
    echo [✓] Python %pyver% 已安裝
)

REM ── 下載 FFmpeg ──────────────────────────────
echo.
echo [2/4] 下載 FFmpeg…
if exist "%~dp0ffmpeg.exe" (
    echo [✓] FFmpeg 已存在
) else (
    echo 正在從 gyan.dev 下載 FFmpeg essentials…
    echo （約 100 MB，視網路速度可能需要 1-5 分鐘）
    echo.
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%~dp0ffmpeg.zip' -UseBasicParsing"
    if exist "%~dp0ffmpeg.zip" (
        echo 下載完成，解壓縮中…
        powershell -NoProfile -Command ^
            "Expand-Archive -Path '%~dp0ffmpeg.zip' -DestinationPath '%~dp0' -Force; " ^
            "$ffd = Get-ChildItem -Path '%~dp0' -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1; " ^
            "if ($ffd) { Move-Item -Path $ffd.FullName -Destination '%~dp0ffmpeg.exe' -Force; " ^
            "Get-ChildItem '%~dp0' -Directory | Where-Object { $_.Name -like 'ffmpeg*' } | Remove-Item -Recurse -Force; }"
        del /f /q "%~dp0ffmpeg.zip" >nul 2>&1
        if exist "%~dp0ffmpeg.exe" (
            echo [✓] FFmpeg 下載完成
        ) else (
            echo [⚠] FFmpeg 解壓失敗，請手動下載 https://ffmpeg.org/download.html
        )
    ) else (
        echo [⚠] FFmpeg 下載失敗，請手動下載 https://ffmpeg.org/download.html
    )
)

REM ── 安裝 Python 套件 ────────────────────────────
echo.
echo [3/4] 安裝 Python 套件...
echo 這可能需要 10-30 分鐘（需下載約 2-5 GB）
echo.
pip install -r "%~dp0requirements.txt"
if %errorlevel% equ 0 (
    echo [✓] Python 套件安裝完成
) else (
    echo [⚠] 部分套件安裝可能失敗
    echo 你可以稍後手動執行：pip install -r requirements.txt
)

REM ── 建立桌面捷徑 ────────────────────────────────
echo.
echo [4/4] 建立桌面捷徑...
if exist "%~dp0KTV.exe" (
    set TARGET=%~dp0KTV.exe
) else (
    set TARGET=%~dp0KTV_GUI.py
)

powershell -Command ^
    "$WS = New-Object -ComObject WScript.Shell; " ^
    "$SC = $WS.CreateShortcut('%USERPROFILE%\Desktop\KTV Karaoke.lnk'); " ^
    "$SC.TargetPath = '%TARGET%'; " ^
    "$SC.WorkingDirectory = '%~dp0'; " ^
    "$SC.Description = 'KTV Karaoke Generator - YouTube 卡拉 OK（2027-06-05到期）'; " ^
    "$SC.Save()" >nul 2>&1
if %errorlevel% equ 0 (
    echo [✓] 桌面捷徑已建立
) else (
    echo [⚠] 捷徑建立失敗，可手動建立
)

echo.
echo ============================================
echo  🎉 安裝完成！
echo ============================================
echo.
echo 雙擊桌面「KTV Karaoke」捷徑即可使用！
echo.
pause

REM ── 啟動 KTV ────────────────────────────────────
if exist "%~dp0KTV.exe" (
    start "" "%~dp0KTV.exe"
) else (
    start "" python "%~dp0KTV_GUI.py"
)
