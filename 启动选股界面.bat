@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  智能选股系统 正在启动...
echo  浏览器将自动打开页面，请稍候
echo  关闭本窗口即可退出系统
echo ============================================
"D:\ProgramData\anaconda3\envs\stock\python.exe" -m streamlit run app.py
pause
