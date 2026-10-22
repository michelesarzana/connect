"""Scarica le attivita Garmin (Personal API). Chiave: GARMIN_PERSONAL_KEY.

Storico incrementale: docs/data/attivita.json e' l'archivio di tutte le attivita, con i soli campi
essenziali (niente nomi). Se l'archivio manca scarica tutto lo storico; altrimenti riscarica solo
gli ultimi RIFRESCA giorni prima dell'ultima attivita archiviata e li unisce.
"""
import requests, json, csv, datetime as dt
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')              # CSV e JSON grezzi (non versionati)
DOCS = os.path.join(ROOT, 'docs')              # sito servito da GitHub Pages
ARCHIVIO = os.path.join(DOCS, 'data', 'attivita.json')
RIFRESCA = 30
MAX_PAGINE = 500
os.makedirs(DATA, exist_ok=True)

key = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
if not key:
    print('Chiave Garmin non trovata (variabile GARMIN_PERSONAL_KEY)')
    sys.exit(1)

base = 'https://personal.connectapi.garmin.com'
r = requests.post(base + '/personalapitoken-service/personal-api/personal-api-key/token',
                  headers={'Authorization': 'ApiKey ' + key}, timeout=20)
print('token status', r.status_code)
if r.status_code != 200:
    print('Token non valido: interrompo senza toccare i dati esistenti')
    sys.exit(1)
H = {'Authorization': 'Bearer ' + r.text.strip().strip('"')}

try:
    archivio = json.load(open(ARCHIVIO, encoding='utf-8')).get('righe', [])
except Exception:
    archivio = []
if archivio:
    start = dt.date.fromisoformat(max(x[1] for x in archivio)[:10]) - dt.timedelta(days=RIFRESCA)
else:
    start = dt.date(2000, 1, 1)
print('archivio', len(archivio), 'attivita; scarico da', start)

acts, errors, offset, limit = [], [], 0, 30
while True:
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
    if offset >= limit * MAX_PAGINE:
        break

if errors and not acts:
    print('Download fallito:', errors)
    sys.exit(1)

seen, uniq = set(), []
for a in acts:
    if a.get('activityId') in seen:
        continue
    seen.add(a.get('activityId'))
    if (a.get('startTimeLocal') or '')[:10] >= start.isoformat():
        uniq.append(a)
acts = uniq


def compatta(a):
    t = (a.get('activityType') or {}).get('typeKey', '')
    dur, dist, eg, hr = a.get('duration'), a.get('distance'), a.get('elevationGain'), a.get('averageHR')
    return [a.get('activityId'), (a.get('startTimeLocal') or '')[:16].replace(' ', 'T'), t,
            round(dist / 1000.0, 2) if dist else None, round(dur / 60.0, 1) if dur is not None else None,
            round(eg) if eg is not None else None, round(hr) if hr is not None else None]


# unione: dell'archivio restano le righe prima di start, da start in poi valgono quelle fresche
nuove = [compatta(a) for a in acts]
ids_nuovi = {x[0] for x in nuove}
righe = [x for x in archivio if x[1][:10] < start.isoformat() and x[0] not in ids_nuovi] + nuove
righe.sort(key=lambda x: x[1])
if not righe:
    print('Nessuna attivita: interrompo senza toccare i dati esistenti')
    sys.exit(1)
os.makedirs(os.path.dirname(ARCHIVIO), exist_ok=True)
json.dump({'campi': ['id', 'data', 'tipo', 'km', 'min', 'dislivello_m', 'fc_media'], 'righe': righe},
          open(ARCHIVIO, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('archivio aggiornato:', len(righe), 'attivita dal', righe[0][1], 'al', righe[-1][1], '| nuove', len(nuove))

open(os.path.join(DATA, 'activities_source.txt'), 'w').write('LIVE\n')
json.dump(acts, open(os.path.join(DATA, 'activities_raw.json'), 'w'), ensure_ascii=False, indent=1)

# CSV per compute_metrics: righe fresche complete (con nome), righe d'archivio con i soli campi essenziali
rows = []
for a in acts:
    t = (a.get('activityType') or {}).get('typeKey', '')
    dur, dist = a.get('duration'), a.get('distance')
    pace = ''
    if 'running' in t and dist and dur and dist > 0:
        pace = round((dur / 60.0) / (dist / 1000.0), 2)
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
for x in righe:
    if x[0] in ids_nuovi:
        continue
    pace = round(x[4] / x[3], 2) if ('running' in x[2] and x[3] and x[4]) else ''
    rows.append({'data': x[1].replace('T', ' ') + ':00', 'tipo_attivita': x[2], 'nome': '',
                 'durata_min': '' if x[4] is None else x[4], 'distanza_km': '' if x[3] is None else x[3],
                 'dislivello_pos_m': '' if x[5] is None else x[5], 'passo_medio_min_km': pace,
                 'fc_media': '' if x[6] is None else x[6], 'fc_max': '', 'calorie': '', 'training_effect_aerobico': ''})
rows.sort(key=lambda x: x['data'])
cols = ['data', 'tipo_attivita', 'nome', 'durata_min', 'distanza_km', 'dislivello_pos_m', 'passo_medio_min_km',
        'fc_media', 'fc_max', 'calorie', 'training_effect_aerobico']
with open(os.path.join(DATA, 'activities.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

from collections import Counter
print('csv', len(rows), 'righe; errori', errors)
print(Counter(x['tipo_attivita'] for x in rows).most_common(12))
