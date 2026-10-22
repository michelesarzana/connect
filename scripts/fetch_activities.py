"""Scarica le attivita Garmin degli ultimi 180 giorni (Personal API). Chiave: GARMIN_PERSONAL_KEY."""
import requests, json, csv, datetime as dt
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')              # CSV e JSON grezzi (non versionati)
DOCS = os.path.join(ROOT, 'docs')              # sito servito da GitHub Pages
SCRIPTS = os.path.join(ROOT, 'scripts')
os.makedirs(DATA, exist_ok=True)

key = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
if not key:
    print('Chiave Garmin non trovata (variabile GARMIN_PERSONAL_KEY)')
    sys.exit(1)

base = 'https://personal.connectapi.garmin.com'
r = requests.post(base + '/personalapitoken-service/personal-api/personal-api-key/token',
                  headers={'Authorization': 'ApiKey ' + key}, timeout=20)
print('token status', r.status_code)
LIVE = r.status_code == 200
tok = r.text.strip().strip('"') if LIVE else ''
H = {'Authorization': 'Bearer ' + tok}

end = dt.date.today()
start = end - dt.timedelta(days=180)
acts = []
errors = []
offset = 0
limit = 30
while LIVE:
    url = base + '/activitylist-service/activities/search/activities'
    # endDate fa rispondere 500 sulla Personal API: si usa solo startDate
    params = {'start': offset, 'limit': limit, 'startDate': start.isoformat()}
    rr = requests.get(url, headers=H, params=params, timeout=30)
    print('page', offset, 'status', rr.status_code)
    if rr.status_code != 200:
        errors.append((offset, rr.status_code, rr.text[:200].replace(key, '***')))
        break
    batch = rr.json()
    if not isinstance(batch, list) or not batch:
        break
    acts.extend(batch)
    if len(batch) < limit or (batch[-1].get('startTimeLocal') or '9')[:10] < start.isoformat():
        break
    offset += limit

if LIVE:
    seen = set()
    uniq = []
    for a in acts:
        if a.get('activityId') in seen:
            continue
        seen.add(a.get('activityId'))
        if (a.get('startTimeLocal') or '')[:10] >= start.isoformat():
            uniq.append(a)
    acts = uniq

source = 'LIVE'
if not acts:
    print('Nessuna attivita scaricata: interrompo senza toccare i dati esistenti')
    sys.exit(1)
open(os.path.join(DATA, 'activities_source.txt'), 'w').write(source + '\n')
print('source', source)
json.dump(acts, open(os.path.join(DATA, 'activities_raw.json'), 'w'), ensure_ascii=False, indent=1)
print('n acts', len(acts), 'errors', errors)

def g(a, k):
    v = a.get(k)
    return v

rows = []
for a in acts:
    t = (a.get('activityType') or {}).get('typeKey', '')
    dur = a.get('duration')
    dist = a.get('distance')
    pace = ''
    if 'running' in t and dist and dur and dist > 0:
        p = (dur / 60.0) / (dist / 1000.0)
        pace = round(p, 2)
    rows.append({
        'data': (a.get('startTimeLocal') or '')[:19],
        'tipo_attivita': t,
        'nome': a.get('activityName') or '',
        'durata_min': round(dur / 60.0, 1) if dur is not None else '',
        'distanza_km': round(dist / 1000.0, 2) if dist is not None else '',
        'dislivello_pos_m': round(a['elevationGain']) if a.get('elevationGain') is not None else '',
        'passo_medio_min_km': pace,
        'fc_media': round(a['averageHR']) if a.get('averageHR') is not None else '',
        'fc_max': round(a['maxHR']) if a.get('maxHR') is not None else '',
        'calorie': round(a['calories']) if a.get('calories') is not None else '',
        'training_effect_aerobico': a.get('aerobicTrainingEffect') if a.get('aerobicTrainingEffect') is not None else '',
    })
rows.sort(key=lambda x: x['data'])
cols = list(rows[0].keys()) if rows else ['data','tipo_attivita','nome','durata_min','distanza_km','dislivello_pos_m','passo_medio_min_km','fc_media','fc_max','calorie','training_effect_aerobico']
with open(os.path.join(DATA, 'activities.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

from collections import Counter
print('range', rows[0]['data'] if rows else None, rows[-1]['data'] if rows else None)
print(Counter(r['tipo_attivita'] for r in rows))
for c in cols:
    miss = sum(1 for r in rows if r[c] == '')
    print(c, 'missing', miss)
