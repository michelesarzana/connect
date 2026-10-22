"""Scarica le tracce GPS delle attivita (Personal API) per la mappa dei percorsi.

Archivio incrementale in docs/data/tracce.json: per ogni attivita una polyline codificata
(formato Google, precisione 5) semplificata a circa 10 m. Ogni esecuzione scarica al massimo
MAX_PER_GIRO tracce nuove, dalle piu recenti, cosi lo storico si completa in qualche ora.
Non fa mai fallire il workflow: in caso di problemi stampa il motivo ed esce con 0.
"""
import json, math, os, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs', 'data')
ATT = os.path.join(DOCS, 'attivita.json')
OUT = os.path.join(DOCS, 'tracce.json')
MAX_PER_GIRO = int(os.environ.get('TRACCE_MAX', '500'))
TOLL_M = 10.0
SENZA_GPS = {'hiit', 'strength_training', 'indoor_cycling', 'lap_swimming', 'indoor_cardio', 'yoga', 'pilates',
             'treadmill_running', 'indoor_rowing', 'fitness_equipment', 'virtual_ride', 'breathwork', 'meditation',
             'indoor_running', 'elliptical', 'stair_climbing', 'floor_climbing', 'indoor_climbing', 'bouldering'}
BASE = 'https://personal.connectapi.garmin.com'


def esci(msg):
    print('tracce:', msg)
    sys.exit(0)


key = os.environ.get('GARMIN_PERSONAL_KEY', '').strip()
if not key:
    esci('chiave assente, salto')
try:
    righe = json.load(open(ATT, encoding='utf-8'))['righe']
except Exception as e:
    esci('archivio attivita assente (%s), salto' % type(e).__name__)
try:
    arch = json.load(open(OUT, encoding='utf-8'))
except Exception:
    arch = {}
tracce = arch.get('tracce', {})
senza = set(arch.get('senza', []))

da_fare = [r for r in sorted(righe, key=lambda r: r[1], reverse=True)
           if str(r[0]) not in tracce and str(r[0]) not in senza and r[2] not in SENZA_GPS]
print('tracce in archivio', len(tracce), '| senza gps', len(senza), '| da scaricare', len(da_fare))
if not da_fare:
    esci('niente di nuovo')

r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                  headers={'Authorization': 'ApiKey ' + key}, timeout=20)
if r.status_code != 200:
    esci('token HTTP %s, salto' % r.status_code)
H = {'Authorization': 'Bearer ' + r.text.strip().strip('"')}


def punti_da(j):
    """Estrae [(lat, lon)] dalle forme note delle risposte Garmin."""
    if not isinstance(j, dict):
        return []
    cand = None
    g = j.get('geoPolylineDTO') or {}
    if isinstance(g, dict) and g.get('polyline'):
        cand = g['polyline']
    elif isinstance(j.get('polyline'), list):
        cand = j['polyline']
    if cand:
        out = []
        for p in cand:
            la, lo = p.get('lat'), p.get('lon')
            if la is not None and lo is not None and (la or lo):
                out.append((float(la), float(lo)))
        return out
    # fallback: metriche dettagliate con colonne lat/lon
    desc = j.get('metricDescriptors') or []
    det = j.get('activityDetailMetrics') or []
    ix = {d.get('key'): d.get('metricsIndex') for d in desc if isinstance(d, dict)}
    a, b = ix.get('directLatitude'), ix.get('directLongitude')
    if a is None or b is None:
        return []
    out = []
    for m in det:
        v = m.get('metrics') or []
        if len(v) > max(a, b) and v[a] is not None and v[b] is not None:
            out.append((float(v[a]), float(v[b])))
    return out


ENDPOINTS = [
    ('details', '/activity-service/activity/%s/details', {'maxChartSize': 2000, 'maxPolylineSize': 4000}),
    ('polyline', '/activity-service/activity/%s/polyline/full-resolution/', None),
]


def scarica(aid, stato):
    """Punti GPS, [] se gli endpoint rispondono senza coordinate, None se errore temporaneo."""
    ok200 = False
    for nome, path, params in ENDPOINTS:
        if nome in stato['morti']:
            continue
        for tentativo in range(3):
            try:
                x = requests.get(BASE + path % aid, headers=H, params=params, timeout=30)
            except Exception:
                time.sleep(1.5)
                continue
            if x.status_code == 429 or x.status_code >= 500:
                time.sleep(3 + 3 * tentativo)
                continue
            break
        else:
            continue
        stato['codici'].setdefault(nome, {}).setdefault(x.status_code, 0)
        stato['codici'][nome][x.status_code] += 1
        if x.status_code in (401, 403):
            stato['morti'].add(nome)
            continue
        if x.status_code != 200:
            continue
        try:
            pts = punti_da(x.json())
        except Exception:
            pts = []
        if pts:
            return pts
        ok200 = True
    return [] if ok200 else None


def m_tra(p, q):
    la = math.radians((p[0] + q[0]) / 2)
    return math.hypot((q[0] - p[0]) * 111320.0, (q[1] - p[1]) * 111320.0 * math.cos(la))


def semplifica(pts, toll):
    if len(pts) < 3:
        return pts
    # Douglas-Peucker iterativo, distanze in metri su proiezione locale
    la0 = math.radians(pts[0][0])
    xy = [(p[1] * 111320.0 * math.cos(la0), p[0] * 111320.0) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    pila = [(0, len(pts) - 1)]
    while pila:
        i, j = pila.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            x0, y0 = xy[k]
            if L2 == 0:
                d = math.hypot(x0 - x1, y0 - y1)
            else:
                t = max(0.0, min(1.0, ((x0 - x1) * dx + (y0 - y1) * dy) / L2))
                d = math.hypot(x0 - (x1 + t * dx), y0 - (y1 + t * dy))
            if d > best:
                best, bi = d, k
        if best > toll:
            keep[bi] = True
            pila += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keep) if k]


def codifica(pts):
    out, pla, plo = [], 0, 0
    for la, lo in pts:
        a, b = int(round(la * 1e5)), int(round(lo * 1e5))
        for v in (a - pla, b - plo):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        pla, plo = a, b
    return ''.join(out)


stato = {'codici': {}, 'morti': set()}
vuote_ids = []
nuove, vuote, t0 = 0, 0, time.time()
for n, r_ in enumerate(da_fare[:MAX_PER_GIRO]):
    if len(stato['morti']) == len(ENDPOINTS):
        print('tracce: nessun endpoint accessibile con questa chiave', stato['codici'])
        break
    pts = scarica(r_[0], stato)
    if pts is None:
        continue                      # errore temporaneo: riprova al prossimo giro
    # scarta punti spuri (0,0) e salti oltre 50 km
    pul = []
    for p in pts:
        if pul and m_tra(pul[-1], p) > 50000:
            continue
        pul.append(p)
    if len(pul) < 2:
        vuote_ids.append(str(r_[0])); vuote += 1
    else:
        tracce[str(r_[0])] = codifica(semplifica(pul, TOLL_M)); nuove += 1
    if n < 3:
        print('esempio', r_[1], r_[2], len(pts), 'punti ->', len(tracce.get(str(r_[0]), '')), 'caratteri')
    time.sleep(0.25)
    if (n + 1) % 50 == 0:
        json.dump({'v': 1, 'tracce': tracce, 'senza': sorted(senza)}, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))

# se nessuna attivita del giro ha coordinate e' piu probabile un formato inatteso: non le segno come senza GPS
if nuove > 0 or vuote < 20:
    senza.update(vuote_ids)
else:
    print('tracce: nessuna coordinata in %d risposte, non le archivio come senza GPS' % vuote)
json.dump({'v': 1, 'tracce': tracce, 'senza': sorted(senza)}, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
print('tracce: +%d nuove, %d senza gps, totale %d, %.0f s, codici %s'
      % (nuove, vuote, len(tracce), time.time() - t0, stato['codici']))
