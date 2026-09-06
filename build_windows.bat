@echo off
chcp 65001 >nul
:: ============================================================
::  法律操作系统 - Windows 打包脚本
::  运行方式：在 legal-kb 目录下双击运行，或 cmd 执行
::  产出：dist\法律操作系统\  和  dist\法律操作系统_Windows.zip
:: ============================================================

setlocal EnableDelayedExpansion

set APP_NAME=法律操作系统
set ENTRY=app_entry.py
set DIST_DIR=dist
set BUILD_DIR=build

echo.
echo ======================================================
echo   法律操作系统 Windows 打包脚本
echo ======================================================
echo.

:: ── 1. 检查 Python ──────────────────────────────────────────
echo [1/6] 检查 Python 环境...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 python，请先安装 Python 3.8+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo     Python: %%i

:: ── 2. 安装/更新依赖 ─────────────────────────────────────────
echo.
echo [2/6] 安装打包依赖...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet ^
    pyinstaller ^
    fastapi ^
    "uvicorn[standard]" ^
    requests ^
    beautifulsoup4 ^
    lxml ^
    jieba ^
    aiofiles ^
    python-multipart
if %ERRORLEVEL% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo     [OK] 依赖安装完成

:: ── 3. 清理旧产物 ────────────────────────────────────────────
echo.
echo [3/6] 清理旧打包产物...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%"  rmdir /s /q "%DIST_DIR%"
del /q *.spec 2>nul
echo     [OK] 清理完成

:: ── 4. 执行打包 ──────────────────────────────────────────────
echo.
echo [4/6] 开始打包（可能需要几分钟，请耐心等待）...

python -m PyInstaller ^
    --name "%APP_NAME%" ^
    --onedir ^
    --console ^
    --noconfirm ^
    --clean ^
    --add-data "frontend;frontend" ^
    --add-data "backend;backend" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "anyio" ^
    --hidden-import "anyio._backends._asyncio" ^
    --hidden-import "starlette" ^
    --hidden-import "fastapi" ^
    --hidden-import "jieba" ^
    --hidden-import "bs4" ^
    --hidden-import "lxml" ^
    --hidden-import "aiofiles" ^
    --hidden-import "multipart" ^
    --collect-all jieba ^
    --collect-all bs4 ^
    "%ENTRY%"

if %ERRORLEVEL% neq 0 (
    echo [错误] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)
echo     [OK] 打包完成

:: ── 5. 复制数据库 ────────────────────────────────────────────
echo.
echo [5/6] 复制数据库...
if exist "legal_kb.db" (
    copy /y "legal_kb.db" "%DIST_DIR%\%APP_NAME%\" >nul
    echo     [OK] 数据库已复制
) else (
    echo     [跳过] 未找到 legal_kb.db
)
if not exist "%DIST_DIR%\%APP_NAME%\uploads" mkdir "%DIST_DIR%\%APP_NAME%\uploads"

:: 创建启动快捷方式说明
(
echo 双击「%APP_NAME%.exe」启动法律操作系统
echo.
echo 启动后浏览器会自动打开 http://localhost:8765
echo 如未自动打开，请手动在浏览器输入上述地址
echo.
echo 关闭黑色命令窗口即可停止服务
) > "%DIST_DIR%\%APP_NAME%\README_使用说明.txt"

:: ── 6. 打包成 ZIP ────────────────────────────────────────────
echo.
echo [6/6] 压缩为 ZIP...
:: 使用 PowerShell 压缩（Windows 10+ 内置支持）
powershell -Command "Compress-Archive -Path '%DIST_DIR%\%APP_NAME%' -DestinationPath '%DIST_DIR%\%APP_NAME%_Windows.zip' -Force"
if %ERRORLEVEL% neq 0 (
    echo     [跳过] ZIP 压缩失败，请手动压缩 %DIST_DIR%\%APP_NAME% 文件夹
) else (
    echo     [OK] 已生成: %DIST_DIR%\%APP_NAME%_Windows.zip
)

echo.
echo ======================================================
echo   打包成功！
echo.
echo   产出文件:
echo     %DIST_DIR%\%APP_NAME%_Windows.zip
echo.
echo   使用方法:
echo     1. 将 ZIP 发给朋友
echo     2. 解压后进入 %APP_NAME% 文件夹
echo     3. 双击「%APP_NAME%.exe」运行
echo     4. 浏览器会自动打开 http://localhost:8765
echo ======================================================
echo.
pause
