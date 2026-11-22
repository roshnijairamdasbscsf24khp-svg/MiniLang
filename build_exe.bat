@echo off
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name MiniLang main.py
echo.
echo Done: dist\MiniLang.exe
pause
