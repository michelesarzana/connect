import json, os, sys, argparse, datetime as _dt
import pandas as pd
import numpy as np

_ap = argparse.ArgumentParser()
_ap.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
_ap.add_argument("--today", default=None, help="YYYY-MM-DD, default oggi (Europe/Rome)")
_args, _ = _ap.parse_known_args()
D = os.path.join(_args.dir, "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "data")      # metrics.json pubblicato
os.makedirs(OUT_DIR, exist_ok=True)
act = pd.read_csv(D + "activities.csv")
try:
    wel = pd.read_csv(D + "wellness.csv")
except Exception:
    wel = pd.DataFrame()
src = open(D + "activities_source.txt").read().strip()
try:
    wsrc = open(D + "wellness_source.txt", encoding="utf-8").read()
except Exception:
    wsrc = ""

act["data"] = pd.to_datetime(act["data"])
act["day"] = act["data"].dt.normalize()
act = act.sort_values("data").reset_index(drop=True)
for c in ["durata_min", "distanza_km", "dislivello_pos_m", "passo_medio_min_km"]:
    act[c] = pd.to_numeric(act[c], errors="coerce")

def _today():
    if _args.today:
        return pd.Timestamp(_args.today)
    try:
        from zoneinfo import ZoneInfo
        return pd.Timestamp(_dt.datetime.now(ZoneInfo("Europe/Rome")).date())
    except Exception:
        return pd.Timestamp(_dt.date.today())
today = _today()
last_act = act["day"].max()  # ultimo giorno con attivita'
FRESH_DAYS = 3
live = "CACHE" not in src.upper()
fresh = live and (today - last_act).days <= FRESH_DAYS
# finestre ancorate a oggi se i dati sono aggiornati, altrimenti all'ultimo giorno con dati
anchor = today if fresh else last_act
RUN = ["running", "trail_running"]
PESO_TARGET_KG = 82.0   # target di peso, senza data
FOOT = ["running", "trail_running", "hiking"]

def r(x, n=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), n)

def window(df, end, days):
    start = end - pd.Timedelta(days=days - 1)
    return df[(df["day"] >= start) & (df["day"] <= end)]

def kpis(df, end, days):
    cur = window(df, end, days)
    prev = window(df, end - pd.Timedelta(days=days), days)
    def agg(w):
        runs = w[w["tipo_attivita"].isin(RUN) & w["passo_medio_min_km"].notna() & (w["distanza_km"] > 0)]
        pace = None
        if len(runs) and runs["distanza_km"].sum() > 0:
            pace = runs["durata_min"].sum() / runs["distanza_km"].sum()
        return {
            "km": r(w["distanza_km"].sum()),
            "dislivello_m": r(w["dislivello_pos_m"].sum(), 0),
            "ore": r(w["durata_min"].sum() / 60, 2),
            "uscite": int(len(w)),
            "passo_corsa_min_km": r(pace, 2),
            "uscite_corsa": int(len(runs)),
        }
    c, p = agg(cur), agg(prev)
    delta = {}
    for k in ["km", "dislivello_m", "ore", "uscite", "passo_corsa_min_km"]:
        if c[k] is not None and p[k] not in (None, 0):
            delta[k] = r((c[k] - p[k]) / p[k] * 100, 1)
        else:
            delta[k] = None
    return {"periodo": [str((end - pd.Timedelta(days=days - 1)).date()), str(end.date())],
            "periodo_precedente": [str((end - pd.Timedelta(days=2 * days - 1)).date()), str((end - pd.Timedelta(days=days)).date())],
            "corrente": c, "precedente": p, "variazione_pct": delta}

# (2) serie settimanale, 26 settimane (lun-dom) che terminano nella settimana dell'ultimo dato
wk_end = anchor.to_period("W-SUN").start_time
weeks = [wk_end - pd.Timedelta(weeks=i) for i in range(25, -1, -1)]
weekly = []
for w in weeks:
    sub = act[(act["day"] >= w) & (act["day"] < w + pd.Timedelta(days=7))]
    weekly.append({"settimana": str(w.date()), "km": r(sub["distanza_km"].sum()),
                   "dislivello_m": r(sub["dislivello_pos_m"].sum(), 0),
                   "ore": r(sub["durata_min"].sum() / 60, 2), "uscite": int(len(sub))})

# (3) carico acuto/cronico in minuti (media giornaliera 7gg / media giornaliera 28gg)
idx = pd.date_range(anchor - pd.Timedelta(days=120), anchor)
daily_min = act.groupby("day")["durata_min"].sum().reindex(idx, fill_value=0)
acute = daily_min.rolling(7).sum() / 7
chronic = daily_min.rolling(28).sum() / 28
ratio = (acute / chronic).replace([np.inf, -np.inf], np.nan)
def light(v):
    if v is None: return None
    return "basso" if v < 0.8 else ("ottimale" if v <= 1.3 else "alto")
cur_ratio = r(ratio.iloc[-1], 2)
load_series = [{"data": str(d.date()), "acuto_min_die": r(acute[d]), "cronico_min_die": r(chronic[d]),
                "rapporto": r(ratio[d], 2)} for d in idx[-90:] if not np.isnan(ratio[d])]
carico = {"unita": "minuti di allenamento al giorno (media 7 gg / media 28 gg)",
          "data_riferimento": str(anchor.date()),
          "acuto_min_die": r(acute.iloc[-1]), "cronico_min_die": r(chronic.iloc[-1]),
          "rapporto": cur_ratio, "semaforo": light(cur_ratio),
          "soglie": {"basso": "<0.8", "ottimale": "0.8-1.3", "alto": ">1.3"},
          "nota": "Indicazione orientativa, non un parere medico o di allenamento.",
          "serie": load_series}

# picco carico
peak = None
if len(load_series):
    pk = max(load_series, key=lambda x: x["rapporto"])
    peak = pk

# (4) wellness
wellness = {"disponibile": False, "serie": {}, "motivo": None}
if len(wel) > 0:
    wel["data"] = pd.to_datetime(wel["data"])
    wel = wel.sort_values("data")
    mp = {"sonno_ore": "sonno_ore", "sonno_punteggio": "sonno_punteggio", "hrv": "hrv_notte_ms",
          "fc_riposo": "fc_riposo", "body_battery_max": "body_battery_max", "body_battery_min": "body_battery_min",
          "stress": "stress_medio", "passi": "passi", "peso_kg": "peso_kg", "spo2": "spo2_medio",
          "sonno_profondo_min": "sonno_profondo_min", "sonno_rem_min": "sonno_rem_min",
          "sonno_leggero_min": "sonno_leggero_min", "sonno_sveglio_min": "sonno_sveglio_min"}
    for _c in mp.values():
        if _c not in wel.columns:
            wel[_c] = np.nan
    wstart = anchor - pd.Timedelta(days=29)
    for k, c in mp.items():
        s = pd.to_numeric(wel[c], errors="coerce")
        ma = s.rolling(7, min_periods=3).mean()
        wellness["serie"][k] = [{"data": str(d.date()), "valore": r(v, 2), "media_7gg": r(m, 2)}
                                for d, v, m in zip(wel["data"], s, ma) if not np.isnan(v) and d >= wstart and d <= anchor]
    wellness["disponibile"] = any(len(wellness["serie"][k]) for k in ["sonno_ore", "hrv", "fc_riposo", "body_battery_max", "stress"])
    wellness["ultimo_giorno"] = str(wel["data"].max().date())
    wellness["finestra_serie"] = [str(wstart.date()), str(anchor.date())]
    _all = ["sonno_ore", "sonno_punteggio", "hrv", "fc_riposo", "spo2", "body_battery_max", "body_battery_min", "stress", "passi", "peso_kg",
            "sonno_profondo_min", "sonno_rem_min", "sonno_leggero_min", "sonno_sveglio_min"]
    wellness["metriche_disponibili"] = [k for k in _all if len(wellness["serie"][k])]
    wellness["metriche_non_disponibili"] = [k for k in _all if not len(wellness["serie"][k])]
    # il sonno e' una stima solo se la fonte lo dichiara (ripiego sulla finestra HRV) o mancano le fasi
    sonno_stimato = not len(wellness["serie"]["sonno_profondo_min"])
    wellness["sonno_stimato"] = bool(sonno_stimato)
    wellness["note"] = ["L'ultimo giorno è parziale: passi, stress e Body Battery sono quelli accumulati finora. Il sonno è quello della notte appena conclusa."]
    if sonno_stimato:
        wellness["note"].insert(0, "Il sonno è una durata stimata dalla finestra registrata con l'HRV: le fasi e il punteggio non sono disponibili.")
    else:
        wellness["note"].insert(0, "Il sonno è il tempo dormito (profondo, REM e leggero) senza i risvegli; punteggio e fasi sono quelli calcolati da Garmin.")
    # fasi dell'ultima notte con dato e media 7 giorni
    _ph = ["sonno_profondo_min", "sonno_rem_min", "sonno_leggero_min", "sonno_sveglio_min"]
    _wp = wel[wel["data"] <= anchor].dropna(subset=["sonno_profondo_min", "sonno_rem_min", "sonno_leggero_min"])
    if len(_wp):
        _l = _wp.iloc[-1]
        _w7 = _wp[_wp["data"] > anchor - pd.Timedelta(days=7)]
        _f = lambda row: {"profondo": r(row["sonno_profondo_min"], 0), "rem": r(row["sonno_rem_min"], 0),
                          "leggero": r(row["sonno_leggero_min"], 0), "sveglio": r(row["sonno_sveglio_min"], 0) or 0}
        wellness["fasi_sonno"] = {"data": str(_l["data"].date()), "ultima_notte_min": _f(_l),
                                  "media_7gg_min": _f(_w7.mean(numeric_only=True)) if len(_w7) else None,
                                  "giorni_7gg": int(len(_w7))}
    # statistiche di sintesi: ultimi 7 giorni contro i 28 precedenti
    def wstat(c):
        s = pd.Series(pd.to_numeric(wel[c], errors="coerce").values, index=wel["data"].values)
        s = s[(s.index <= anchor)].dropna()
        a = s[s.index > anchor - pd.Timedelta(days=7)]
        b = s[(s.index <= anchor - pd.Timedelta(days=7)) & (s.index > anchor - pd.Timedelta(days=35))]
        return {"media_7gg": r(a.mean(), 2) if len(a) else None, "media_28gg_prec": r(b.mean(), 2) if len(b) else None,
                "giorni_7gg": int(len(a))}
    wellness["sintesi"] = {k: wstat(c) for k, c in [("sonno_ore", "sonno_ore"), ("hrv", "hrv_notte_ms"), ("stress", "stress_medio"),
                                                  ("body_battery_max", "body_battery_max"), ("passi", "passi"),
                                                  ("sonno_punteggio", "sonno_punteggio"), ("fc_riposo", "fc_riposo"), ("spo2", "spo2_medio")]}
    hs = wel[(wel["data"] > anchor - pd.Timedelta(days=30)) & (wel["data"] <= anchor)]["hrv_stato"].dropna()
    wellness["hrv_stato_30gg"] = {str(k): int(v) for k, v in hs.value_counts().items()}
if not wellness["disponibile"]:
    wellness["motivo"] = "Nessun dato benessere scaricato."
    wellness["serie"] = {k: [] for k in ["sonno_ore", "sonno_punteggio", "hrv", "fc_riposo", "spo2", "body_battery_max", "body_battery_min", "stress"]}

# (5) ultime 10 attivita'
last10 = []
for _, x in act.sort_values("data", ascending=False).head(10).iterrows():
    last10.append({"data": x["data"].strftime("%Y-%m-%d %H:%M"), "tipo": x["tipo_attivita"], "nome": x["nome"],
                   "distanza_km": r(x["distanza_km"], 2), "durata_min": r(x["durata_min"]),
                   "dislivello_m": r(x["dislivello_pos_m"], 0), "fc_media": r(x.get("fc_media"), 0)})

# tipi
tipi = act.groupby("tipo_attivita").agg(uscite=("nome", "size"), km=("distanza_km", "sum"), ore=("durata_min", lambda s: s.sum() / 60)).reset_index()
tipi = [{"tipo": t.tipo_attivita, "uscite": int(t.uscite), "km": r(t.km), "ore": r(t.ore, 1)} for t in tipi.itertuples()]
tipi.sort(key=lambda z: -z["ore"])


# (5b) peso: serie lunga, target, trend degli ultimi 30 giorni
peso = {"target": PESO_TARGET_KG, "serie": [], "attuale": None, "data_attuale": None,
        "trend_kg_sett": None, "settimane_al_target": None, "data_stimata": None}
try:
    pw = pd.read_csv(D + "weight.csv")
except Exception:
    pw = pd.DataFrame()
if not len(pw) and len(wel) and "peso_kg" in wel.columns:
    pw = wel[["data", "peso_kg"]].copy()
if len(pw):
    pw["data"] = pd.to_datetime(pw["data"])
    pw["peso_kg"] = pd.to_numeric(pw["peso_kg"], errors="coerce")
    pw = pw.dropna().sort_values("data")
    pw = pw[pw["data"] <= anchor]
if len(pw):
    peso["serie"] = [{"data": str(d.date()), "kg": r(v, 1)} for d, v in zip(pw["data"], pw["peso_kg"])]
    peso["attuale"] = r(pw["peso_kg"].iloc[-1], 1)
    peso["data_attuale"] = str(pw["data"].iloc[-1].date())
    rec = pw[pw["data"] > anchor - pd.Timedelta(days=30)]
    if len(rec) >= 4 and (rec["data"].max() - rec["data"].min()).days >= 10:
        xs = (rec["data"] - rec["data"].min()).dt.days.values.astype(float)
        slope = float(np.polyfit(xs, rec["peso_kg"].values.astype(float), 1)[0]) * 7
        peso["trend_kg_sett"] = r(slope, 2)
        diff = peso["attuale"] - PESO_TARGET_KG
        if diff > 0 and slope < -0.05:
            weeks = diff / -slope
            peso["settimane_al_target"] = r(weeks, 1)
            peso["data_stimata"] = str((anchor + pd.Timedelta(days=round(weeks * 7))).date())


# (6) osservazioni, in quattro famiglie
k7 = kpis(act, anchor, 7); k30 = kpis(act, anchor, 30)

def it(x, n=1):
    return f"{x:.{n}f}".replace(".", ",").replace("-", "−")

MESI_L = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]
GIORNI_L = ["il lunedì", "il martedì", "il mercoledì", "il giovedì", "il venerdì", "il sabato", "la domenica"]
TIPI_L = {"hiit": "HIIT", "running": "corsa", "trail_running": "trail running", "hiking": "escursione",
          "walking": "camminata", "cycling": "bici", "road_biking": "bici su strada", "gravel_cycling": "gravel",
          "indoor_cycling": "bici indoor", "lap_swimming": "nuoto in vasca", "strength_training": "forza",
          "multi_sport": "multisport", "mountain_biking": "mountain bike"}

def quando(d):
    d = pd.Timestamp(d)
    return f"{d.day} {MESI_L[d.month - 1]}" + ("" if d.year == anchor.year else f" {d.year}")

def art(prep, d):
    """'il', 'dal', 'al' + data, con l'elisione giusta: l'8, dall'11, dal 1° maggio."""
    g, q = pd.Timestamp(d).day, quando(d)
    if g in (8, 11):
        return {"il": "l'", "dal": "dall'", "al": "all'"}[prep] + q
    if g == 1:
        q = "1° " + q[2:]
    return prep + " " + q

def verso_data(d):
    d = pd.Timestamp(d)
    fase = "inizio" if d.day <= 10 else ("metà" if d.day <= 20 else "fine")
    return f"{fase} {MESI_L[d.month - 1]}" + ("" if d.year == anchor.year else f" {d.year}")

oss = {"record": [], "abitudini": [], "recupero": [], "proiezioni": []}
past = act[act["day"] <= anchor]
inizio30 = anchor - pd.Timedelta(days=29)

# Record e serie
if len(past):
    wk = past.assign(sett=past["day"] - pd.to_timedelta(past["day"].dt.weekday, unit="D")).groupby("sett")["distanza_km"].sum()
    if len(wk) and wk.max() > 0:
        bw = wk.idxmax()
        if bw >= inizio30 - pd.Timedelta(days=6):
            oss["record"].append(f"Nuovo record: la settimana {art("dal", bw)} è la più lunga di sempre, {it(wk.max())} km.")
        else:
            oss["record"].append(f"Settimana più lunga di sempre: {it(wk.max())} km, {art("dal", bw)}.")
    corse = past[past["tipo_attivita"].isin(RUN) & (past["distanza_km"] > 0)]
    if len(corse):
        lr = corse.loc[corse["distanza_km"].idxmax()]
        dp = f", {it(lr['dislivello_pos_m'], 0)} m di dislivello" if pd.notna(lr["dislivello_pos_m"]) and lr["dislivello_pos_m"] >= 100 else ""
        nuova = " È un nuovo record." if lr["day"] >= inizio30 else ""
        oss["record"].append(f"Corsa più lunga: {it(lr['distanza_km'])} km {art('il', lr['day'])}{dp}.{nuova}")
    giorni = sorted(set(past["day"]))
    best, cur, prev, best_end = 0, 0, None, None
    for d in giorni:
        cur = cur + 1 if prev is not None and (d - prev).days == 1 else 1
        if cur > best:
            best, best_end = cur, d
        prev = d
    in_corso = 0
    if giorni and (anchor - giorni[-1]).days <= 1:
        in_corso, i = 1, len(giorni) - 1
        while i > 0 and (giorni[i] - giorni[i - 1]).days == 1:
            in_corso += 1; i -= 1
    if best >= 3:
        if in_corso == best:
            oss["record"].append(f"Sei sulla tua serie più lunga: {best} giorni attivi di fila.")
        else:
            txt = f"Serie più lunga di giorni attivi consecutivi: {best}, fino {art("al", best_end)}."
            if in_corso >= 3:
                txt += f" Quella in corso è di {in_corso}."
            oss["record"].append(txt)

# Abitudini
cnt = past["tipo_attivita"].value_counts()
if len(cnt):
    t0 = cnt.index[0]
    oss["abitudini"].append(f"L'attività più frequente è {TIPI_L.get(t0, t0.replace('_', ' '))}: {cnt.iloc[0]} uscite su {len(past)}.")
r90 = window(act, anchor, 90)
if len(r90) >= 8:
    wd = r90["data"].dt.weekday.value_counts()
    oss["abitudini"].append(f"Negli ultimi 90 giorni il giorno più attivo è {GIORNI_L[int(wd.index[0])]}: {int(wd.iloc[0])} uscite su {len(r90)}.")
    h = r90["data"].dt.hour
    fasce = {"prima delle 9": (h < 9).mean(), "tra le 9 e le 18": ((h >= 9) & (h < 18)).mean(), "dopo le 18": (h >= 18).mean()}
    f_, v_ = max(fasce.items(), key=lambda x: x[1])
    if v_ >= 0.5:
        oss["abitudini"].append(f"Il {v_ * 100:.0f}% delle uscite parte {f_}.")
lun = anchor - pd.Timedelta(days=anchor.weekday())
n_ok = sum(len(act[(act["day"] >= lun - pd.Timedelta(weeks=i)) & (act["day"] < lun - pd.Timedelta(weeks=i - 1))]) >= 3 for i in range(1, 13))
if len(past) and past["day"].min() <= lun - pd.Timedelta(weeks=12):
    oss["abitudini"].append(f"In {n_ok} delle ultime 12 settimane hai fatto almeno 3 uscite.")
ly = anchor - pd.DateOffset(years=1)
if len(past) and past["day"].min() <= ly - pd.Timedelta(days=29):
    ha = window(act, anchor, 30)["durata_min"].sum() / 60
    hb = window(act, ly, 30)["durata_min"].sum() / 60
    if hb > 0:
        dd = (ha - hb) / hb * 100
        oss["abitudini"].append(f"Rispetto agli stessi 30 giorni del {ly.year}: {it(ha)} ore contro {it(hb)}, {'+' if dd >= 0 else '−'}{abs(dd):.0f}%.")
    elif ha > 0:
        oss["abitudini"].append(f"Negli stessi 30 giorni del {ly.year} non c'erano attività registrate.")

# Recupero e carico
S = wellness.get("sintesi", {}) if wellness["disponibile"] else {}
def verso(k, meglio_se_alto=True, soglia=2.0):
    s = S.get(k) or {}
    a, b = s.get("media_7gg"), s.get("media_28gg_prec")
    if a is None or not b:
        return None
    d = (a - b) / b * 100
    if abs(d) < soglia:
        return 0
    return 1 if (d > 0) == meglio_se_alto else -1
if wellness["disponibile"]:
    voci = [("sonno", verso("sonno_ore")), ("punteggio del sonno", verso("sonno_punteggio")),
            ("battito a riposo", verso("fc_riposo", meglio_se_alto=False)), ("HRV", verso("hrv")),
            ("stress", verso("stress", meglio_se_alto=False))]
    su = [n for n, v in voci if v == 1]; giu = [n for n, v in voci if v == -1]; uguali = [n for n, v in voci if v == 0]
    def elenco(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " e " + xs[-1]
    parti = []
    if su: parti.append(f"meglio {elenco(su)}")
    if giu: parti.append(f"peggio {elenco(giu)}")
    if uguali: parti.append(f"stabili {elenco(uguali)}" if len(uguali) > 1 else f"stabile {uguali[0]}")
    if parti:
        oss["recupero"].append("Rispetto alle 4 settimane prima: " + "; ".join(parti) + ".")
if cur_ratio is not None:
    pk_txt = f" Il picco degli ultimi 90 giorni è stato {it(peak['rapporto'], 2)} {art('il', peak['data'])}." if peak and peak["rapporto"] > 1.3 else ""
    oss["recupero"].append(f"Carico {light(cur_ratio)}, {'in linea con' if light(cur_ratio) == 'ottimale' else ('sopra' if cur_ratio > 1.3 else 'sotto')} l'abituale.{pk_txt}")
if len(wel) and "hrv_notte_ms" in wel.columns:
    hrv = pd.Series(pd.to_numeric(wel["hrv_notte_ms"], errors="coerce").values, index=pd.to_datetime(wel["data"]).values)
    idx_h = pd.date_range(anchor - pd.Timedelta(days=89), anchor - pd.Timedelta(days=1))
    dmin = act.groupby("day")["durata_min"].sum().reindex(idx_h, fill_value=0)
    if (dmin > 0).sum() >= 8:
        soglia = max(75.0, float(dmin[dmin > 0].quantile(0.75)))
        pesanti = set(dmin[dmin >= soglia].index)
        dopo = hrv.reindex([d + pd.Timedelta(days=1) for d in pesanti]).dropna()
        altri = hrv.reindex([d + pd.Timedelta(days=1) for d in idx_h if d not in pesanti]).dropna()
        if len(dopo) >= 4 and len(altri) >= 10:
            a_, b_ = dopo.mean(), altri.mean()
            if abs(a_ - b_) / b_ >= 0.03:
                oss["recupero"].append(f"Dopo i giorni più pesanti (da {soglia:.0f} minuti in su) l'HRV della notte è in media {a_:.0f} ms, contro {b_:.0f} negli altri giorni.")
            else:
                oss["recupero"].append(f"Dopo i giorni più pesanti l'HRV della notte resta simile agli altri ({a_:.0f} contro {b_:.0f} ms): il recupero tiene.")
    hv = hrv[hrv.index <= anchor].dropna()
    if len(hv) >= 8 and (anchor - hv.index[-1]).days <= 1:
        l_, m_ = hv.iloc[-1], hv.iloc[-8:-1].mean()
        if l_ < m_ * 0.9 and (cur_ratio or 0) > 1.3:
            oss["recupero"].append(f"Segnale di scarico: HRV di stanotte {l_:.0f} ms, sotto la media della settimana ({m_:.0f}), con il carico alto.")
        elif l_ < m_ * 0.9:
            oss["recupero"].append(f"HRV di stanotte {l_:.0f} ms, sotto la media della settimana ({m_:.0f}): vale la pena ascoltare come stai.")
oss["recupero"].append("Per il menisco contano più fisioterapista e sensazioni di questi numeri.")

# Proiezioni
if peso["attuale"] is not None:
    if peso["attuale"] <= PESO_TARGET_KG:
        oss["proiezioni"].append(f"Peso {it(peso['attuale'])} kg: target di {it(PESO_TARGET_KG, 0)} kg raggiunto.")
    elif peso["settimane_al_target"] is not None:
        oss["proiezioni"].append(f"Al ritmo degli ultimi 30 giorni ({it(peso['trend_kg_sett'])} kg a settimana) arrivi a {it(PESO_TARGET_KG, 0)} kg in circa {peso['settimane_al_target']:.0f} settimane, verso {verso_data(peso['data_stimata'])}.")
    elif peso["trend_kg_sett"] is not None:
        oss["proiezioni"].append(f"Negli ultimi 30 giorni il peso è stabile o in salita ({'+' if peso['trend_kg_sett'] >= 0 else ''}{it(peso['trend_kg_sett'])} kg a settimana): al ritmo attuale non c'è una data stimata per {it(PESO_TARGET_KG, 0)} kg.")
compl = [w["km"] or 0 for w in weekly[:-1]]
media_sett = sum(compl) / len(compl) if compl else 0
if media_sett > 0:
    km_ora = weekly[-1]["km"] or 0
    if km_ora < media_sett:
        oss["proiezioni"].append(f"Settimana in corso: {it(km_ora)} km. Per la tua media ({it(media_sett)} km) ne mancano {it(media_sett - km_ora)} entro domenica.")
    else:
        oss["proiezioni"].append(f"Settimana in corso: {it(km_ora)} km, già sopra la tua media di {it(media_sett)}.")
m0 = anchor.replace(day=1)
if anchor.day >= 5:
    mtd = act[(act["day"] >= m0) & (act["day"] <= anchor)]["distanza_km"].sum()
    gm = pd.Period(anchor, "M").days_in_month
    pm0 = (m0 - pd.Timedelta(days=1)).replace(day=1)
    prec = act[(act["day"] >= pm0) & (act["day"] < m0)]["distanza_km"].sum()
    oss["proiezioni"].append(f"{MESI_L[anchor.month - 1].capitalize()}: {it(mtd)} km finora, al ritmo attuale circa {mtd / anchor.day * gm:.0f} a fine mese ({MESI_L[pm0.month - 1]}: {prec:.0f}).")
obs = oss

n_act = len(act)
miss_dis = int(act["dislivello_pos_m"].isna().sum())
n_run7 = k7["corrente"]["uscite_corsa"]; n_run30 = k30["corrente"]["uscite_corsa"]
pace30 = k30["corrente"]["passo_corsa_min_km"]

lacune = [f"Dislivello mancante in {miss_dis} attività su {n_act}", "Passo disponibile solo per corsa e trail running"]
if wellness["disponibile"]:
    lacune += ["L'ultimo giorno di benessere è parziale (passi, stress e Body Battery)"]
    lacune += [f"{nm} non disponibile" for k, nm in [("sonno_punteggio", "Punteggio del sonno"), ("fc_riposo", "Battito a riposo"), ("spo2", "SpO2"), ("sonno_profondo_min", "Fasi del sonno")] if k in wellness.get("metriche_non_disponibili", [])]
    if wellness.get("sonno_stimato"):
        lacune.append("La durata del sonno è una stima")
else:
    lacune.append("Dati benessere assenti (sonno, HRV, FC a riposo, Body Battery, stress)")
if not fresh:
    lacune.insert(0, f"Attività ferme al {last_act.strftime('%d/%m/%Y')}")

avv_pace = f"Il passo di corsa si basa su {n_run30} uscite negli ultimi 30 giorni e su {n_run7} negli ultimi 7: da leggere con cautela."
nota_foot = (f"Il dislivello manca in {miss_dis} attività su {n_act}. " + avv_pace)

out = {
    "generato_il": str(today.date()),
    "generato_alle": _dt.datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Rome")).strftime("%H:%M"),
    "peso": peso,
    "data_riferimento": str(anchor.date()),
    "ultima_attivita": str(last_act.date()),
    "fonte_attivita": src,
    "dati_aggiornati": bool(fresh),
    "avviso_dati": (None if fresh else f"Le attività arrivano da una cache o sono ferme al {last_act.strftime('%d/%m/%Y')}; i periodi 7 e 30 giorni sono calcolati a ritroso da quella data, non da oggi ({today.strftime('%d/%m/%Y')})."),
    "attivita_totali": int(n_act),
    "intervallo_attivita": [str(act['day'].min().date()), str(last_act.date())],
    "kpi": {"7g": k7, "30g": k30},
    "settimane": weekly,
    "carico": carico,
    "benessere": wellness,
    "ultime_attivita": last10,
    "per_tipo": tipi,
    "osservazioni": obs,
    "nota_footer": nota_foot,
    "avvertenze_kpi": [f"Il dislivello manca in {miss_dis} attività su {n_act}: le variazioni percentuali del dislivello e i totali possono essere sottostimati.",
                       avv_pace,
                       "Le variazioni percentuali sono null quando il periodo precedente vale zero."],
    "lacune": lacune,
}
json.dump(out, open(os.path.join(OUT_DIR, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ["data_riferimento", "dati_aggiornati", "osservazioni", "peso"]}, ensure_ascii=False, indent=1)[:4000])
print(cur_ratio, light(cur_ratio), peak)
print(weekly[-6:])
print(wellness.get("disponibile"), wellness.get("sintesi"), wellness.get("hrv_stato_30gg"))
