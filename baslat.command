#!/bin/bash
# Mac (ve Linux): çift tıkla, tarayıcıda panel açılır. Kapatmak için bu pencereyi kapat.
# İlk açılışta gerekenleri kendi klasörüne (.venv) kurar; bilgisayarın geri kalanına dokunmaz.

cd "$(dirname "$0")" || exit 1

dur() {
  echo
  echo "$1"
  if [ -t 0 ]; then read -r -p "Kapatmak için Enter'a bas. " _; fi
  exit 1
}

uygun() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }

python_bul() {
  local p
  for p in \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3 \
    python3.13 python3.12 python3.14 python3.11 python3; do
    p="$(command -v "$p" 2>/dev/null)" || continue
    # Apple'ın /usr/bin/python3'ü, geliştirici araçları kurulu değilken yalnız kurulum penceresi açar
    if [ "$p" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if uygun "$p"; then echo "$p"; return 0; fi
  done
  return 1
}

if ! { [ -x .venv/bin/python ] && uygun .venv/bin/python; }; then
  PY="$(python_bul)" || dur "Python 3.11 ya da daha yenisi bulunamadı.
https://www.python.org/downloads/ adresinden Python'u indirip kur, sonra bu dosyayı tekrar aç."
  echo "İlk kurulum: $PY"
  "$PY" -m venv --clear .venv || dur "Sanal ortam kurulamadı."
fi

if ! cmp -s requirements.txt .venv/kurulu.txt; then
  echo "Gerekli paketler kuruluyor (ilk seferde birkaç dakika sürer)..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
    || dur "Paketler kurulamadı. İnternet bağlantını kontrol edip tekrar dene."
  cp requirements.txt .venv/kurulu.txt
fi

.venv/bin/python -m metal || dur "Panel kapandı (yukarıdaki satırlara bak)."
