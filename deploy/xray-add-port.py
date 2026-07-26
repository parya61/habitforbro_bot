#!/usr/bin/env python3
"""Добавляет второй порт для VPN-инбаунда, не трогая существующий.
Клиенты продолжают работать на 443, пока владелец не переключится на новый порт."""
import json, shutil, subprocess, sys, datetime

CFG = '/usr/local/etc/xray/config.json'
NEW_PORT = 2053
NEW_TAG = 'vsRAWrtyVISION-alt'

bak = CFG + '.bak-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(CFG, bak)
print('бэкап:', bak)

cfg = json.load(open(CFG))
src = next((i for i in cfg['inbounds'] if i.get('port') == 443), None)
if src is None:
    sys.exit('инбаунд на 443 не найден')

if any(i.get('port') == NEW_PORT for i in cfg['inbounds']):
    print('порт', NEW_PORT, 'уже настроен — пропускаю')
else:
    clone = json.loads(json.dumps(src))     # глубокая копия
    clone['port'] = NEW_PORT
    clone['tag'] = NEW_TAG
    cfg['inbounds'].append(clone)
    json.dump(cfg, open(CFG, 'w'), indent=2, ensure_ascii=False)
    print('добавлен инбаунд на порт', NEW_PORT, 'с теми же ключами и пользователями')

# проверяем конфиг до перезапуска
r = subprocess.run(['xray', 'test', '-c', CFG], capture_output=True, text=True)
if r.returncode != 0:
    shutil.copy2(bak, CFG)
    sys.exit('конфиг не прошёл проверку, откатил:\n' + (r.stderr or r.stdout)[-800:])
print('конфиг корректен')

subprocess.run(['systemctl', 'restart', 'xray'], check=True)
print('xray перезапущен')
