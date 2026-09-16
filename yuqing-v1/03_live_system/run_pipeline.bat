@echo off
rem 实时流水线（Windows）：采集 -> 清洗入事实表 -> 重算 data.js
rem 用法：
rem   run_pipeline.bat "D:\路径\Excel数据库改造示例.xlsx"
rem   或先 set ATOMIC_XLSX=D:\路径\库.xlsx 再运行 run_pipeline.bat
setlocal
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul || set "PY=C:\Python\python.exe"

if "%ATOMIC_XLSX%"=="" (
  if "%~1"=="" (
    echo 未指定原子化工作簿：请设置 ATOMIC_XLSX 或传入路径参数
    exit /b 1
  )
  set "ATOMIC_XLSX=%~1"
)

if not exist logs mkdir logs

echo === %date% %time% 开始 === >> logs\pipeline.log
echo [1/3] collect.py >> logs\pipeline.log
%PY% collect.py >> logs\pipeline.log 2>&1
if errorlevel 1 exit /b 1

echo [2/3] clean_and_append.py >> logs\pipeline.log
%PY% clean_and_append.py --xlsx "%ATOMIC_XLSX%" >> logs\pipeline.log 2>&1
if errorlevel 1 exit /b 1

echo [3/3] build_data.py --atomic >> logs\pipeline.log
%PY% ..\01_code_docs\scripts\build_data.py --atomic "%ATOMIC_XLSX%" >> logs\pipeline.log 2>&1
if errorlevel 1 exit /b 1

echo === %date% %time% 完成 === >> logs\pipeline.log
endlocal
