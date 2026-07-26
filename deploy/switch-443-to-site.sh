#!/bin/bash
# Освобождает порт 443 у VPN и отдаёт его сайту.
# VPN продолжает работать на порту 2053 (добавлен заранее, ключи те же).
set -u
STAMP=$(date +%Y%m%d-%H%M%S)

echo "== 1. снимаю инбаунд VPN с порта 443 (2053 остаётся) =="
cp /usr/local/etc/xray/config.json /root/xray-config.bak-$STAMP
python3 - <<'PY'
import json, sys
CFG='/usr/local/etc/xray/config.json'
c=json.load(open(CFG))
before=len(c['inbounds'])
c['inbounds']=[i for i in c['inbounds'] if i.get('port')!=443]
if len(c['inbounds'])==before:
    print('   инбаунда на 443 нет — пропускаю')
else:
    json.dump(c, open(CFG,'w'), indent=2, ensure_ascii=False)
    print('   удалён, осталось инбаундов:', len(c['inbounds']))
PY

if ! xray run -test -c /usr/local/etc/xray/config.json >/tmp/xraytest 2>&1; then
  echo "   ОШИБКА конфига, откат"; cp /root/xray-config.bak-$STAMP /usr/local/etc/xray/config.json
  tail -5 /tmp/xraytest; exit 1
fi
systemctl restart xray
sleep 2
systemctl is-active xray | sed 's/^/   xray: /'
ss -ltn | grep -q ':2053' && echo "   VPN слушает 2053: да" || echo "   VPN на 2053: НЕТ"
ss -ltn | grep -q ':443 ' && echo "   443 всё ещё занят!" || echo "   443 свободен"

echo "== 2. перевожу сайт с 9443 на 443 =="
sed -i 's/listen 9443 ssl http2;/listen 443 ssl http2;/' /etc/nginx/sites-available/sovanisova-tls
if nginx -t >/tmp/ngxtest 2>&1; then
  systemctl reload nginx
  echo "   nginx перезагружен"
else
  echo "   ОШИБКА nginx, возвращаю 9443"; sed -i 's/listen 443 ssl http2;/listen 9443 ssl http2;/' /etc/nginx/sites-available/sovanisova-tls
  tail -3 /tmp/ngxtest; exit 1
fi

sleep 1
echo "== 3. проверка =="
curl -s -o /dev/null -w '   https локально: %{http_code}\n' --resolve sovanisova.ru:443:127.0.0.1 https://sovanisova.ru/
curl -s -o /dev/null -w '   http  локально: %{http_code}\n' -H 'Host: sovanisova.ru' http://127.0.0.1/
echo -n '   сертификат: '; echo | openssl s_client -connect 127.0.0.1:443 -servername sovanisova.ru 2>/dev/null | openssl x509 -noout -subject | sed 's/subject=//'
echo "== готово. бэкап конфига VPN: /root/xray-config.bak-$STAMP =="
