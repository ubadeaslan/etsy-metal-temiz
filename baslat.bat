@echo off
rem Windows: cift tikla, tarayicida panel acilir. Kapatmak icin bu pencereyi kapat.
rem Ilk acilista gerekenleri kendi klasorune (.venv) kurar; bilgisayarin geri kalanina dokunmaz.
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Ilk kurulum...
  py -3 -m venv .venv >nul 2>&1
  if not exist .venv\Scripts\python.exe python -m venv .venv >nul 2>&1
)
if not exist .venv\Scripts\python.exe (
  echo Python bulunamadi. https://www.python.org/downloads/ adresinden kur
  echo ^(kurulumda "Add python.exe to PATH" kutusunu isaretle^), sonra bu dosyayi tekrar ac.
  pause
  exit /b 1
)
.venv\Scripts\python -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
  echo Python 3.11 ya da daha yenisi gerekiyor. https://www.python.org/downloads/ adresinden kur,
  echo sonra bu klasordeki .venv klasorunu silip bu dosyayi tekrar ac.
  pause
  exit /b 1
)

fc /b requirements.txt .venv\kurulu.txt >nul 2>&1
if errorlevel 1 (
  echo Gerekli paketler kuruluyor ^(ilk seferde birkac dakika surer^)...
  .venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo Paketler kurulamadi. Internet baglantini kontrol edip tekrar dene.
    pause
    exit /b 1
  )
  copy /y requirements.txt .venv\kurulu.txt >nul
)

.venv\Scripts\python -m metal
if errorlevel 1 pause
