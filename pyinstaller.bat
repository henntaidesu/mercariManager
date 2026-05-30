@echo off
chcp 65001 >nul
echo ========================================
echo   mercari 一键打包 (PyInstaller)
echo ========================================

:: ===== 版本号（每次发布修改这里）=====
set VERSION=v1.0.0

:: ===== 是否打入 OCR(easyocr/torch，体积约 2GB，启动变慢)。0=否 1=是 =====
set BUNDLE_OCR=0

set ROOT=%~dp0
set RELEASE=%ROOT%Releases\%VERSION%

:: ===== 激活 conda 环境 mercari =====
echo.
echo [0/6] 激活 conda 环境 mercari ...
call conda activate mercari
if %errorlevel% neq 0 (
    echo 错误: 无法激活 conda 环境 mercari
    pause
    exit /b 1
)

:: 确保 pyinstaller 可用
where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 未检测到 pyinstaller，正在安装...
    pip install pyinstaller
)

:: ===== 准备发布目录 =====
echo.
echo [1/6] 清理并创建发布目录 %RELEASE% ...
if exist "%RELEASE%" rmdir /s /q "%RELEASE%"
mkdir "%RELEASE%"
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

:: ===== 构建前端 =====
echo.
echo [2/6] 构建前端 webside ...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到 npm，请安装 Node.js: https://nodejs.org/
    pause
    exit /b 1
)
pushd "%ROOT%webside"
if not exist "node_modules" (
    echo 安装前端依赖...
    call npm install
    if %errorlevel% neq 0 ( echo 错误: npm install 失败 & popd & pause & exit /b 1 )
)
call npm run build
if %errorlevel% neq 0 ( echo 错误: 前端构建失败 & popd & pause & exit /b 1 )
popd
if not exist "%ROOT%webside\dist\index.html" (
    echo 错误: 未找到 webside\dist\index.html，前端构建可能失败
    pause
    exit /b 1
)

:: ===== 打包主程序 mercari.exe =====
echo.
echo [3/6] 打包 mercari.exe ...
pyinstaller --clean --noconfirm "%ROOT%mercari.spec" ^
    --distpath "%RELEASE%" --workpath "%ROOT%build\mercari"
if %errorlevel% neq 0 (
    echo 错误: mercari.exe 打包失败
    pause
    exit /b 1
)

:: ===== 打包 mitmdump.exe 到 Scripts\ (供 MITM 子进程调用) =====
echo.
echo [4/6] 打包 Scripts\mitmdump.exe ...
pyinstaller --clean --noconfirm "%ROOT%mitmdump.spec" ^
    --distpath "%RELEASE%\Scripts" --workpath "%ROOT%build\mitmdump"
if %errorlevel% neq 0 (
    echo 警告: mitmdump.exe 打包失败 —— MITM 抓包功能在该包中将不可用，主程序其余功能不受影响。
)

:: ===== 复制前端 dist 到 exe 同级 webside\dist =====
echo.
echo [5/6] 复制前端 webside\dist ...
mkdir "%RELEASE%\webside\dist"
xcopy "%ROOT%webside\dist" "%RELEASE%\webside\dist\" /E /I /H /Y /Q
if %errorlevel% neq 0 (
    echo 错误: 复制 webside\dist 失败
    pause
    exit /b 1
)

:: ===== 生成启动脚本 =====
echo.
echo [6/6] 生成启动脚本与打包 ZIP ...
(
    echo @echo off
    echo chcp 65001 ^>nul
    echo cd /d %%~dp0
    echo echo mercari 启动中... 浏览器访问 http://localhost:9601
    echo start "" http://localhost:9601
    echo mercari.exe
    echo pause
) > "%RELEASE%\start_mercari.bat"

:: 提示: Playwright 用系统已装的 Microsoft Edge(channel=msedge)，目标机需安装 Edge(Win11 自带)。

:: ===== 打 ZIP =====
set ZIP_FILE=%ROOT%Releases\mercari_%VERSION%.zip
if exist "%ZIP_FILE%" del /q "%ZIP_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Compress-Archive -Path '%RELEASE%\*' -DestinationPath '%ZIP_FILE%' -CompressionLevel Optimal -Force"

:: ===== 清理构建中间产物 =====
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

echo.
echo ========================================
echo   打包完成! 输出目录: %RELEASE%
echo ========================================
dir /b "%RELEASE%"
echo ----------------------------------------
echo   双击运行: %RELEASE%\start_mercari.bat
echo   或直接运行 mercari.exe，然后访问 http://localhost:9601
echo   ZIP: %ZIP_FILE%
echo ========================================
pause
