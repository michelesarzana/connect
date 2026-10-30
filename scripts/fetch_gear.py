"""Scarica le scarpe da Garmin (Personal API) e i km percorsi con ciascuna.

Scrive docs/data/scarpe.json. Se gli endpoint dell'attrezzatura non rispondono lascia il file
com'e' (puo' contenere un elenco iniziale copiato a mano, con fonte e data). Non fa mai fallire
il workflow: in caso di problemi stampa il motivo ed esce con 0.
"""
import datetime as dt
import json, os, sys
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'data', 'scarpe.json')
BASE = 'https://personal.connectapi.garmin.com'
LIMITE_KM = 800          # soglia di sostituzione se Garmin non ne indica una


def esci(msg):
    print('scarpe:', msg)
    sys.exit(0)


key = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
if not key:
    esci('chiave assente, salto')
r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                  headers={'Authorization': 'ApiKey ' + key}, timeout=20)
if r.status_code != 200:
    esci('token HTTP %s, salto' % r.status_code)
H = {'Authorization': 'Bearer ' + r.text.strip().strip('"')}


def get(path, **params):
    try:
        x = requests.get(BASE + path, headers=H, params=params or None, timeout=30)
    except Exception as e:
        print('scarpe:', path, type(e).__name__)
        return None
    print('scarpe:', path.split('?')[0], x.status_code)
    if x.status_code != 200:
        return None
    try:
        return x.json()
    except Exception:
        return None


prof = get('/userprofile-service/socialProfile') or {}
pk = prof.get('userProfileNumber') or prof.get('profileId') or prof.get('id')
if not pk:
    esci('profilo non disponibile con questa chiave')
gear = get('/gear-service/gear/filterGear', userProfilePk=pk)
if not isinstance(gear, list):
    esci('elenco attrezzatura non disponibile con questa chiave')

scarpe = []
for g in gear:
    if (g.get('gearTypeName') or '').lower() not in ('shoes', 'shoe'):
        continue
    st = get('/gear-service/gear/stats/%s' % g.get('uuid')) or {}
    km = (st.get('totalDistance') or 0) / 1000.0
    lim = (g.get('maximumMeters') or 0) / 1000.0 or LIMITE_KM
    scarpe.append({
        'nome': g.get('displayName') or g.get('customMakeModel') or 'Scarpa',
        'modello': g.get('customMakeModel') or '',
        'km': round(km, 1),
        'limite_km': round(lim),
        'attiva': (g.get('gearStatusName') or 'active').lower() == 'active',
        'dal': (g.get('dateBegin') or '')[:10] or None,
    })
if not scarpe:
    esci('nessuna scarpa registrata su Garmin, lascio il file com\'e\'')
scarpe.sort(key=lambda s: (not s['attiva'], -s['km']))
oggi = dt.date.today().isoformat()
json.dump({'fonte': 'Garmin Connect', 'aggiornato': oggi, 'scarpe': scarpe},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('scarpe: %d scarpe, %d attive' % (len(scarpe), sum(s['attiva'] for s in scarpe)))
