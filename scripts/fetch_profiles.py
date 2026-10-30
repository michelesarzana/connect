"""Scarica il profilo altimetrico e il battito delle attivita recenti (Personal API).

Archivio in docs/data/profili.json: per ogni attivita con GPS una lista di punti
[km, quota_m, fc] campionata a circa MAX_PUNTI punti. Tiene solo le ultime TIENI attivita.
Non fa mai fallire il workflow: in caso di problemi stampa il motivo ed esce con 0.
"""
import json, os, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs', 'data')
ATT = os.path.join(DOCS, 'attivita.json')
OUT = os.path.join(DOCS, 'profili.json')
BASE = 'https://personal.connectapi.garmin.com'
TIENI = 60
PER_GIRO = 30
MAX_PUNTI = 240
SENZA_GPS = {'hiit', 'strength_training', 'indoor_cycling', 'lap_swimming', 'indoor_cardio', 'yoga', 'pilates',
             'treadmill_running', 'indoor_rowing', 'fitness_equipment', 'virtual_ride', 'breathwork', 'meditation',
             'indoor_running', 'elliptical', 'stair_climbing', 'floor_climbing', 'indoor_climbing', 'bouldering'}


def esci(msg):
    print('profili:', msg)
    sys.exit(0)


key = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
if not key:
    esci('chiave assente, salto')
try:
    righe = json.load(open(ATT, encoding='utf-8'))['righe']
except Exception as e:
    esci('archivio attivita assente (%s), salto' % type(e).__name__)
try:
    arch = json.load(open(OUT, encoding='utf-8')).get('profili', {})
except Exception:
    arch = {}

recenti = [r for r in sorted(righe, key=lambda r: r[1], reverse=True) if r[2] not in SENZA_GPS][:TIENI]
ids = [str(r[0]) for r in recenti]
da_fare = [i for i in ids if i not in arch][:PER_GIRO]
print('profili in archivio', len(arch), '| da scaricare', len(da_fare))

if da_fare:
    r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                      headers={'Authorization': 'ApiKey ' + key}, timeout=20)
    if r.status_code != 200:
        esci('token HTTP %s, salto' % r.status_code)
    H = {'Authorization': 'Bearer ' + r.text.strip().strip('"')}
    codici = {}
    for aid in da_fare:
        try:
            x = requests.get(BASE + '/activity-service/activity/%s/details' % aid, headers=H,
                             params={'maxChartSize': 2000, 'maxPolylineSize': 0}, timeout=30)
        except Exception:
            continue
        codici[x.status_code] = codici.get(x.status_code, 0) + 1
        if x.status_code in (401, 403):
            print('profili: endpoint non accessibile con questa chiave')
            break
        if x.status_code != 200:
            continue
        try:
            j = x.json()
        except Exception:
            continue
        ix = {d.get('key'): d.get('metricsIndex') for d in (j.get('metricDescriptors') or []) if isinstance(d, dict)}
        a, b, c = ix.get('sumDistance'), ix.get('directElevation'), ix.get('directHeartRate')
        if a is None or b is None:
            arch[aid] = []                 # nessuna quota: non riprovare
            continue
        pts = []
        for m in j.get('activityDetailMetrics') or []:
            v = m.get('metrics') or []
            if len(v) <= max(a, b) or v[a] is None or v[b] is None:
                continue
            fc = v[c] if c is not None and len(v) > c else None
            pts.append([round(v[a] / 1000.0, 3), round(v[b], 1), round(fc) if fc else None])
        pts.sort(key=lambda p: p[0])
        if len(pts) > MAX_PUNTI:
            passo = len(pts) / MAX_PUNTI
            pts = [pts[int(i * passo)] for i in range(MAX_PUNTI)] + [pts[-1]]
        arch[aid] = pts
        time.sleep(0.25)
    print('profili: codici', codici)

arch = {i: arch[i] for i in ids if i in arch}
json.dump({'v': 1, 'campi': ['km', 'quota_m', 'fc'], 'profili': arch}, open(OUT, 'w', encoding='utf-8'),
          separators=(',', ':'))
print('profili: totale', len(arch), 'di cui con quota', sum(1 for v in arch.values() if v))
