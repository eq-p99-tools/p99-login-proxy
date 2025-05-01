@echo off
echo Installing PyInstaller if not already installed...
pip install pyinstaller

echo Building with PyInstaller using spec file...
pyinstaller P99LoginProxy.spec

echo Build complete. Executable is in the 'dist' folder.
echo.