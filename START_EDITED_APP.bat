@echo off
cd /d "%~dp0"
echo Starting the EDITED app on http://127.0.0.1:5050
echo If the old app is open, ignore it and use this new address.
python app.py
pause
