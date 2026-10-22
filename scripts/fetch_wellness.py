"""Scarica in sola lettura i dati benessere Garmin degli ultimi 90 giorni (Personal API key).

Endpoint usati (base personal.connectapi.garmin.com):
- sonno:        /sleep-service/sleep/dailySleepSummariesByDate (durata, fasi, punteggio)
                fallback per giorno: /sleep-service/sleep/dailySleep
- FC riposo e SpO2: /usersummary-service/v2/dailysummaries (heartRate.restingValue, pulseOx.avgValue)
                fallback per giorno: /wellness-service/wellness/dailyHeartRate e .../daily/spo2acclimation/D
- passi, stress: /usersummary-service/stats/{steps,stress}/daily/{a}/{b} (max 28 giorni)
- Body Battery: /wellness-service/wellness/bodyBattery/reports/daily
- HRV:          /hrv-service/hrv/D
- peso:         /weight-service/weight/range/{a}/{b}

Uso: python3 fetch_wellness.py [--out CARTELLA, default data/] [--days 90]
La chiave si legge solo dalla variabile d'ambiente GARMIN_PERSONAL_KEY.
Non viene mai stampata ne' scritta su file.
Il displayName non serve: gli endpoint usati sono legati al token.
"""
import argparse, csv, datetime as dt, json, os, sys, time
import requests

BASE = 'https://personal.connectapi.garmin.com'
COLS = ['data', 'sonno_ore', 'sonno_profondo_min', 'sonno_rem_min', 'sonno_leggero_min',
        'sonno_sveglio_min', 'sonno_punteggio', 'fc_riposo', 'hrv_notte_ms', 'hrv_stato',
        'hrv_media_7gg_ms', 'stress_medio', 'passi', 'body_battery_max', 'body_battery_min',
        'peso_kg', 'spo2_medio']

ap = argparse.ArgumentParser()
ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
ap.add_argument('--days', type=int, default=90)
args = ap.parse_args()
OUT = os.path.abspath(args.out)
DAYS = args.days
os.makedirs(OUT, exist_ok=True)


def read_key():
    k = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
    if k:
        return k
    return None


key = read_key()
if not key:
    print('Chiave Garmin non trovata (GARMIN_PERSONAL_KEY)')
    sys.exit(1)

status = {'errors': {}, 'ok': {}}
r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                  headers={'Authorization': 'ApiKey ' + key}, timeout=20)
status['token_status'] = r.status_code
print('token status', r.status_code)
today = dt.date.today()
dates = [(today - dt.timedelta(days=i)).isoformat() for i in range(DAYS - 1, -1, -1)]
rows = {d: {c: '' for c in COLS} for d in dates}
for d in dates:
    rows[d]['data'] = d
raw = {'meta': {'generated': dt.datetime.now().isoformat(timespec='seconds'), 'days': DAYS}, 'data': {}}


def mins(sec):
    return round(sec / 60.0) if isinstance(sec, (int, float)) else ''


if r.status_code == 200:
    H = {'Authorization': 'Bearer ' + r.text.strip().strip('"')}

    def get(name, path, params=None):
        time.sleep(0.2)
        for attempt in range(3):
            try:
                x = requests.get(BASE + path, headers=H, params=params, timeout=30)
            except Exception as e:
                status['errors'].setdefault(name, []).append(type(e).__name__)
                time.sleep(1)
                continue
            if x.status_code == 200:
                status['ok'][name] = status['ok'].get(name, 0) + 1
                try:
                    return x.json()
                except Exception:
                    return None
            if x.status_code in (429, 500, 502, 503):
                time.sleep(2)
                continue
            status['errors'].setdefault(name, []).append(x.status_code)
            return None
        return None

    def chunks(n=28):
        ds = [dt.date.fromisoformat(d) for d in dates]
        for i in range(0, len(ds), n):
            yield ds[i].isoformat(), ds[min(i + n, len(ds)) - 1].isoformat()

    D = raw['data']
    D['steps'], D['stress'], D['bodyBattery'] = [], [], []
    D['sleep'], D['dailysummaries'] = [], []
    for a, b in chunks():
        D['steps'] += get('steps', '/usersummary-service/stats/steps/daily/%s/%s' % (a, b)) or []
        D['stress'] += get('stress', '/usersummary-service/stats/stress/daily/%s/%s' % (a, b)) or []
        D['bodyBattery'] += get('bodyBattery', '/wellness-service/wellness/bodyBattery/reports/daily',
                                {'startDate': a, 'endDate': b}) or []
        s = get('sleepSummaries', '/sleep-service/sleep/dailySleepSummariesByDate',
                {'startDate': a, 'endDate': b})
        if isinstance(s, dict):
            s = s.get('data') or s.get('dailySleepDTOs') or []
        D['sleep'] += s or []
        s = get('dailysummaries', '/usersummary-service/v2/dailysummaries',
                {'startDate': a, 'endDate': b})
        D['dailysummaries'] += ((s or {}).get('data') if isinstance(s, dict) else s) or []
    wt = get('weight', '/weight-service/weight/range/%s/%s' % (dates[0], dates[-1]), {'includeAll': True})
    D['weight'] = wt
    D['hrv'] = {}
    for d in dates:
        h = get('hrv', '/hrv-service/hrv/%s' % d)
        if h:
            h.pop('hrvReadings', None)
            D['hrv'][d] = h

    # ---- vecchi endpoint ----
    for it in D['steps']:
        d = it.get('calendarDate')
        if d in rows and it.get('totalSteps') is not None:
            rows[d]['passi'] = it['totalSteps']
    for it in D['stress']:
        d = it.get('calendarDate')
        v = (it.get('values') or {}).get('overallStressLevel')
        if d in rows and v is not None and v >= 0:
            rows[d]['stress_medio'] = v
    for it in D['bodyBattery']:
        d = it.get('date')
        if d in rows:
            vals = [v[1] for v in (it.get('bodyBatteryValuesArray') or [])
                    if isinstance(v, list) and len(v) > 1 and v[1] is not None]
            if vals:
                rows[d]['body_battery_max'] = max(vals)
                rows[d]['body_battery_min'] = min(vals)
    for it in ((wt or {}).get('dailyWeightSummaries') or []):
        d = it.get('summaryDate')
        w = (it.get('latestWeight') or {}).get('weight')
        if d in rows and w:
            rows[d]['peso_kg'] = round(w / 1000.0, 1)
    for d, h in D['hrv'].items():
        hs = h.get('hrvSummary') or {}
        row = rows[d]
        if hs.get('lastNightAvg') is not None:
            row['hrv_notte_ms'] = hs['lastNightAvg']
        if hs.get('status'):
            row['hrv_stato'] = hs['status']
        if hs.get('weeklyAvg') is not None:
            row['hrv_media_7gg_ms'] = hs['weeklyAvg']

    # ---- sonno ----
    def apply_sleep(it):
        d = it.get('calendarDate')
        if d not in rows or not it.get('sleepTimeSeconds'):
            return False
        row = rows[d]
        row['sonno_ore'] = round(it['sleepTimeSeconds'] / 3600.0, 2)
        row['sonno_profondo_min'] = mins(it.get('deepSleepSeconds'))
        row['sonno_rem_min'] = mins(it.get('remSleepSeconds'))
        row['sonno_leggero_min'] = mins(it.get('lightSleepSeconds'))
        row['sonno_sveglio_min'] = mins(it.get('awakeSleepSeconds'))
        sc = ((it.get('sleepScores') or {}).get('overall') or {}).get('value')
        if sc is not None:
            row['sonno_punteggio'] = sc
        return True

    got_sleep = set()
    for it in D['sleep']:
        if apply_sleep(it):
            got_sleep.add(it['calendarDate'])
    # fallback per giorno se il range ha lasciato buchi (solo ultimi 14 giorni, per limitare le chiamate)
    D['sleep_fallback'] = {}
    for d in dates[-14:]:
        if d not in got_sleep:
            s = get('sleepDaily', '/sleep-service/sleep/dailySleep', {'date': d})
            if isinstance(s, dict) and s.get('dailySleepDTO'):
                s = s['dailySleepDTO']
            if isinstance(s, dict) and apply_sleep(s):
                D['sleep_fallback'][d] = True
    # Se manca del tutto il sonno vero, stima dalla finestra HRV (inizio-fine sonno)
    for d, h in D['hrv'].items():
        if rows[d]['sonno_ore'] == '':
            try:
                a = dt.datetime.fromisoformat(h['sleepStartTimestampLocal'].split('.')[0])
                b = dt.datetime.fromisoformat(h['sleepEndTimestampLocal'].split('.')[0])
                hrs = (b - a).total_seconds() / 3600.0
                if 1 <= hrs <= 16:
                    rows[d]['sonno_ore'] = round(hrs, 2)
            except Exception:
                pass

    # ---- FC a riposo e SpO2 ----
    for it in D['dailysummaries']:
        d = it.get('calendarDate')
        if d not in rows:
            continue
        rv = (it.get('heartRate') or {}).get('restingValue')
        if rv is not None:
            rows[d]['fc_riposo'] = rv
        sp = (it.get('pulseOx') or {}).get('avgValue')
        if sp is not None:
            rows[d]['spo2_medio'] = sp
    D['hr_spo2_fallback'] = {}
    for d in dates[-14:]:
        if rows[d]['fc_riposo'] == '':
            h = get('dailyHeartRate', '/wellness-service/wellness/dailyHeartRate', {'date': d})
            v = (h or {}).get('restingHeartRate')
            if v is not None:
                rows[d]['fc_riposo'] = v
                D['hr_spo2_fallback'][d + ':hr'] = True
        if rows[d]['spo2_medio'] == '':
            s = get('spo2', '/wellness-service/wellness/daily/spo2acclimation/%s' % d)
            v = (s or {}).get('averageSpO2')
            if v is not None:
                rows[d]['spo2_medio'] = v
                D['hr_spo2_fallback'][d + ':spo2'] = True

    D.pop('dailysummaries', None)  # voluminoso e non serve nel raw
    D['sleep'] = [{k: v for k, v in s.items() if k in (
        'calendarDate', 'sleepTimeSeconds', 'deepSleepSeconds', 'lightSleepSeconds',
        'remSleepSeconds', 'awakeSleepSeconds', 'averageSpO2Value', 'avgHeartRate')} |
        {'score': ((s.get('sleepScores') or {}).get('overall') or {}).get('value')}
        for s in D['sleep']]

json.dump({'status': status, 'raw': raw}, open(os.path.join(OUT, 'wellness_raw.json'), 'w'),
          ensure_ascii=False, indent=1, default=str)
with open(os.path.join(OUT, 'wellness.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows[d] for d in dates)

cnt = {c: sum(1 for d in dates if rows[d][c] != '') for c in COLS[1:]}
avail = [c for c in COLS[1:] if cnt[c] > 0]
missing = [c for c in COLS[1:] if cnt[c] == 0]
if r.status_code == 200:
    txt = ('Dati reali Garmin (Personal API key), scaricati il %s, intervallo %s -> %s (%d giorni).\n'
           'Disponibili: %s.\nNon disponibili con questa chiave: %s.\n'
           'Sonno da dailySleepSummariesByDate (ore = profondo + REM + leggero, senza sveglio); '
           'FC a riposo e SpO2 da dailysummaries.\n'
           % (dt.date.today().isoformat(), dates[0], dates[-1], DAYS,
              ', '.join(avail), ', '.join(missing) or 'nessuna'))
else:
    txt = 'NESSUN DATO: token HTTP %s. CSV con sola intestazione.\n' % r.status_code
open(os.path.join(OUT, 'wellness_source.txt'), 'w').write(txt)
print('righe', len(rows))
for c in COLS[1:]:
    print(c, cnt[c])
print('errori', {k: sorted(set(map(str, v))) for k, v in status['errors'].items()})
