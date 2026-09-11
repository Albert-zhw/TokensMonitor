@echo off
rem TokensMonitor EXE 打包脚本：双击运行后自动生成 dist\TokensMonitor.exe
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 安装打包依赖...
pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple || pip install -r requirements.txt -q
echo [2/3] 开始打包（约 1-3 分钟）...
pyinstaller --noconsole --onefile --name TokensMonitor ^
  --add-data "static;static" ^
  --add-data "README.md;." ^
  --add-data "LICENSE;." ^
  tray_app.py
echo [3/3] 完成！
echo 输出文件: dist\TokensMonitor.exe
echo （首次运行会在 exe 同目录生成 config.json）
pause
