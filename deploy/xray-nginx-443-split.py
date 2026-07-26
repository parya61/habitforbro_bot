#!/usr/bin/env python3
"""Возвращает VPN на порт 443, не отнимая его у сайта.

Nginx встаёт на 443 и по имени домена в TLS-запросе решает, куда отдать
соединение целиком, не расшифровывая его:
  sovanisova.ru / www  -> сайт (127.0.0.1:8445)
  всё остальное        -> xray (127.0.0.1:8444)

Так возвращаются VPN-конфиги на 443, подписки Happ и прокси Telegram.
"""
import json, shutil, subprocess, sys, datetime, os, re

STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
XCFG = '/usr/local/etc/xray/config.json'
NCFG = '/etc/nginx/nginx.conf'
BAK_X = f'/root/restore-xray.bak-{STAMP}'
BAK_N = f'/root/restore-nginx.bak-{STAMP}'


def die(msg, rollback=()):
    for src, dst in rollback:
        shutil.copy2(src, dst)
    sys.exit('ОШИБКА: ' + msg)


# ---------- 1. xray: вернуть инбаунд 443 на внутренний порт 8444 ----------
shutil.copy2(XCFG, BAK_X)
cfg = json.load(open(XCFG))

src_bak = sorted([p for p in os.listdir('/root') if p.startswith('xray-config.bak-')])
if not src_bak:
    die('не нашёл резервную копию с инбаундом 443')
old = json.load(open('/root/' + src_bak[-1]))
orig = next((i for i in old['inbounds'] if i.get('port') == 443), None)
if orig is None:
    die('в резервной копии нет инбаунда 443')

if not any(i.get('port') == 8444 for i in cfg['inbounds']):
    inb = json.loads(json.dumps(orig))
    inb['port'] = 8444
    inb['listen'] = '127.0.0.1'
    inb['tag'] = 'vsRAWrtyVISION'
    cfg['inbounds'].append(inb)
    json.dump(cfg, open(XCFG, 'w'), indent=2, ensure_ascii=False)
    print('xray: инбаунд восстановлен на 127.0.0.1:8444')
else:
    print('xray: инбаунд 8444 уже есть')

r = subprocess.run(['xray', 'run', '-test', '-c', XCFG], capture_output=True, text=True)
if r.returncode != 0:
    die('конфиг xray не прошёл проверку:\n' + (r.stderr or r.stdout)[-600:], [(BAK_X, XCFG)])
subprocess.run(['systemctl', 'restart', 'xray'], check=True)
print('xray: перезапущен')

# ---------- 2. сайт переезжает с 443 на внутренний 8445 ----------
TLS = '/etc/nginx/sites-enabled/sovanisova-tls'
t = open(TLS).read()
t = re.sub(r'listen [\d.:]*443 ssl http2;', 'listen 127.0.0.1:8445 ssl http2;', t)
open(TLS, 'w').write(t)
print('сайт: слушает 127.0.0.1:8445')

# ---------- 3. nginx: включить модуль разделения и настроить его ----------
shutil.copy2(NCFG, BAK_N)
n = open(NCFG).read()
if 'ngx_stream_module.so' not in n:
    n = 'load_module modules/ngx_stream_module.so;\n' + n
if 'streams-enabled' not in n:
    n = n.rstrip() + '\n\nstream {\n    include /etc/nginx/streams-enabled/*.conf;\n}\n'
open(NCFG, 'w').write(n)

os.makedirs('/etc/nginx/streams-enabled', exist_ok=True)
open('/etc/nginx/streams-enabled/443-split.conf', 'w').write('''# Разделение порта 443 по имени домена без расшифровки трафика.
map $ssl_preread_server_name $backend443 {
    sovanisova.ru       site;
    www.sovanisova.ru   site;
    default             vpn;
}

upstream site { server 127.0.0.1:8445; }
upstream vpn  { server 127.0.0.1:8444; }

server {
    listen 443;
    listen [::]:443;
    ssl_preread on;
    proxy_pass $backend443;
    proxy_protocol off;
    proxy_timeout 300s;
}
''')

r = subprocess.run(['nginx', '-t'], capture_output=True, text=True)
if r.returncode != 0:
    die('nginx не принял конфиг:\n' + r.stderr[-600:], [(BAK_N, NCFG)])
subprocess.run(['systemctl', 'restart', 'nginx'], check=True)
print('nginx: перезапущен с разделением порта')
print(f'резервные копии: {BAK_X} , {BAK_N}')
