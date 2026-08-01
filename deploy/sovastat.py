#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сводка по сайту sovanisova.ru и инфраструктуре.

Пишет /var/www/sovanisova/_stats/summary.json — его читает Керя.
Запускается по расписанию; накапливает историю по дням.
"""
import json, os, re, socket, subprocess, ssl, gzip
from datetime import datetime, timedelta, timezone

OUT_DIR = '/var/www/sovanisova/_stats'
SUMMARY = os.path.join(OUT_DIR, 'summary.json')
HISTORY = os.path.join(OUT_DIR, 'history.json')
LOGS = ['/var/log/nginx/sovanisova.access.log', '/var/log/nginx/sovanisova.access.log.1']

MSK = timezone(timedelta(hours=3))
now = datetime.now(MSK)

# ---- что считаем ботом ----
BOT = re.compile(r'bot|crawl|spider|slurp|curl|wget|python|scan|nmap|masscan|zgrab|semrush|ahrefs|petal|yandexbot|googlebot|bingbot|facebookexternalhit|headless', re.I)
# служебные запросы, которые не считаем просмотром
ASSET = re.compile(r'\.(mp4|jpg|jpeg|png|gif|ico|css|js|webp|woff2?|svg|map)(\?|$)', re.I)
LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<code>\d{3}) (?P<size>\S+) "(?P<ref>[^"]*)" "(?P<ua>[^"]*)"')


def read_lines():
    for p in LOGS:
        if not os.path.exists(p):
            continue
        op = gzip.open if p.endswith('.gz') else open
        try:
            with op(p, 'rt', errors='replace') as f:
                for ln in f:
                    yield ln
        except Exception:
            pass


def parse():
    visits = {}          # ip -> {first,last,pages,ua,refs}
    for ln in read_lines():
        m = LINE.match(ln)
        if not m:
            continue
        d = m.groupdict()
        ua, path, ip = d['ua'], d['path'], d['ip']
        if BOT.search(ua) or ua in ('-', ''):
            continue
        if ip.startswith('127.'):
            continue
        try:
            ts = datetime.strptime(d['ts'].split()[0], '%d/%b/%Y:%H:%M:%S').replace(tzinfo=timezone.utc).astimezone(MSK)
        except Exception:
            continue
        v = visits.setdefault(ip, {'first': ts, 'last': ts, 'pages': 0, 'assets': 0, 'ua': ua, 'refs': set()})
        v['last'] = max(v['last'], ts)
        v['first'] = min(v['first'], ts)
        if ASSET.search(path):
            v['assets'] += 1
        elif d['code'] in ('200', '304'):
            v['pages'] += 1
        r = d['ref']
        if r and r != '-' and 'sovanisova.ru' not in r:
            v['refs'].add(r[:120])
    return visits


def window(visits, hours):
    edge = now - timedelta(hours=hours)
    return {ip: v for ip, v in visits.items() if v['last'] >= edge}


def device(ua):
    u = ua.lower()
    if 'iphone' in u or 'ipad' in u: return 'iOS'
    if 'android' in u: return 'Android'
    if 'windows' in u: return 'Windows'
    if 'mac os' in u or 'macintosh' in u: return 'Mac'
    if 'linux' in u: return 'Linux'
    return 'другое'


def svc(name):
    try:
        return subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return 'unknown'


def cert_days(host, port=443, sni=None):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=8) as s:
            with ctx.wrap_socket(s, server_hostname=sni or host) as ss:
                exp = datetime.strptime(ss.getpeercert()['notAfter'], '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
                return (exp - datetime.now(timezone.utc)).days
    except Exception:
        return None


def reachable(host, port, timeout=6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


visits = parse()
d1, d7 = window(visits, 24), window(visits, 24 * 7)

# реальные посетители: те, кто открыл страницу
real1 = {ip: v for ip, v in d1.items() if v['pages'] > 0}
real7 = {ip: v for ip, v in d7.items() if v['pages'] > 0}

devs = {}
for v in real7.values():
    devs[device(v['ua'])] = devs.get(device(v['ua']), 0) + 1

refs = {}
for v in real7.values():
    for r in v['refs']:
        dom = re.sub(r'^https?://([^/]+).*', r'\1', r)
        refs[dom] = refs.get(dom, 0) + 1

# кто смотрел работы (открывал видео) — признак заинтересованности
engaged = [ip for ip, v in real7.items() if v['assets'] >= 3]

try:
    disk = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10).stdout.split('\n')[1].split()
    disk_used, disk_pct = disk[2], disk[4]
except Exception:
    disk_used = disk_pct = '?'

summary = {
    'обновлено': now.strftime('%Y-%m-%d %H:%M МСК'),
    'сайт': {
        'адрес': 'https://sovanisova.ru',
        'доступен': reachable('127.0.0.1', 443),
        'сертификат_дней_осталось': cert_days('127.0.0.1', 443, 'sovanisova.ru'),
    },
    'посещения': {
        'за_сутки': len(real1),
        'за_неделю': len(real7),
        'смотрели_работы_за_неделю': len(engaged),
        'устройства_за_неделю': devs,
        'откуда_приходили': dict(sorted(refs.items(), key=lambda x: -x[1])[:8]) or {'прямые заходы': len(real7)},
        'последние_визиты': [
            {'время': v['last'].strftime('%d.%m %H:%M'), 'устройство': device(v['ua']),
             'страниц': v['pages'], 'открыл_видео': v['assets']}
            for v in sorted(real7.values(), key=lambda x: -x['last'].timestamp())[:8]
        ],
    },
    'сервисы': {n: svc(n) for n in ('nginx', 'xray', 'telemt', 'habits-bot')},
    'сервер_финляндия': {'диск_занято': disk_used, 'диск_процент': disk_pct},
    'сервер_москва': {
        'ip': '45.9.73.192',
        'доступен': reachable('45.9.73.192', 443, 5) or reachable('45.9.73.192', 22, 5),
    },
    'платежи': [
        {'что': 'Сервер Финляндия (first.by #4436644)', 'сколько': '~300-500 ₽', 'когда': 'ежемесячно',
         'критично': 'без него не работает ни сайт, ни VPN'},
        {'что': 'Сервер Москва (first.by #4447968)', 'сколько': '189 ₽', 'когда': 'ежемесячно',
         'критично': 'мост для мобильного интернета'},
        {'что': 'Домен kalmykov-dev.ru (Reg.ru)', 'сколько': '~200-300 ₽', 'когда': 'до 01.07.2027',
         'критично': 'адреса подписок VPN'},
        {'что': 'Домен sovanisova.ru', 'сколько': 'уточнить у регистратора', 'когда': 'уточнить',
         'критично': 'без него сайт недоступен'},
        {'что': 'Старый сервер #4384056', 'сколько': '259 ₽', 'когда': 'ОТМЕНИТЬ',
         'критично': 'не используется с 28.06.2026, деньги на ветер'},
    ],
}

os.makedirs(OUT_DIR, exist_ok=True)
json.dump(summary, open(SUMMARY, 'w'), ensure_ascii=False, indent=2)

# история по дням
hist = []
if os.path.exists(HISTORY):
    try:
        hist = json.load(open(HISTORY))
    except Exception:
        hist = []
today = now.strftime('%Y-%m-%d')
hist = [h for h in hist if h.get('дата') != today]
hist.append({'дата': today, 'посетителей': len(real1), 'смотрели_работы': len([1 for v in real1.values() if v['assets'] >= 3])})
json.dump(hist[-90:], open(HISTORY, 'w'), ensure_ascii=False, indent=2)

os.chmod(SUMMARY, 0o644)
os.chmod(HISTORY, 0o644)
print(f"за сутки: {len(real1)}, за неделю: {len(real7)}, смотрели работы: {len(engaged)}")
