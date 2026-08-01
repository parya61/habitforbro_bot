#!/usr/bin/env python3
"""Возвращает реальные IP посетителей в логи сайта.

Трафик идёт: интернет -> nginx stream на 443 -> 127.0.0.1:8445.
Из-за проксирования сайт видел всех как 127.0.0.1. Включаем proxy_protocol,
чтобы разделитель передавал исходный адрес, и заводим отдельный лог сайта.
"""
import re, shutil, subprocess, sys, datetime

STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
SPLIT = '/etc/nginx/streams-enabled/443-split.conf'
SITE = '/etc/nginx/sites-enabled/sovanisova-tls'
B1, B2 = f'/root/split.bak-{STAMP}', f'/root/site.bak-{STAMP}'

shutil.copy2(SPLIT, B1)
shutil.copy2(SITE, B2)


def rollback(msg):
    shutil.copy2(B1, SPLIT)
    shutil.copy2(B2, SITE)
    subprocess.run(['nginx', '-t'], capture_output=True)
    sys.exit('ОШИБКА, откатил: ' + msg)


# --- разделитель: передавать исходный адрес только сайту ---
sp = open(SPLIT).read()
if 'proxy_protocol on' not in sp:
    sp = sp.replace('proxy_protocol off;', 'proxy_protocol on;')
    open(SPLIT, 'w').write(sp)
    print('разделитель: передаёт исходный адрес')

# --- сайт: принимать его и писать свой лог ---
st = open(SITE).read()
if 'proxy_protocol' not in st.split('\n')[0:20][0] and 'proxy_protocol;' not in st:
    st = re.sub(r'(listen 127\.0\.0\.1:8445 ssl http2)(;)', r'\1 proxy_protocol\2', st)
if 'set_real_ip_from' not in st:
    st = st.replace('    root /var/www/sovanisova;',
                    '    set_real_ip_from 127.0.0.1;\n'
                    '    real_ip_header proxy_protocol;\n'
                    '    access_log /var/log/nginx/sovanisova.access.log;\n\n'
                    '    root /var/www/sovanisova;')
open(SITE, 'w').write(st)
print('сайт: принимает исходный адрес, пишет /var/log/nginx/sovanisova.access.log')

r = subprocess.run(['nginx', '-t'], capture_output=True, text=True)
if r.returncode != 0:
    rollback(r.stderr[-500:])

subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
print('nginx перезагружен')
print(f'копии: {B1} , {B2}')
