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


# (6) osservazioni
k7 = kpis(act, anchor, 7); k30 = kpis(act, anchor, 30)

def it(x, n=1):
    return f"{x:.{n}f}".replace(".", ",")

obs = []
d30 = k30["variazione_pct"]["ore"]
if d30 is not None:
    verso = "in aumento" if d30 > 0 else "in calo"
    obs.append(f"Negli ultimi 30 giorni (fino al {anchor.strftime('%d/%m/%Y')}) il tempo di allenamento è {verso} {'dell' + chr(39) if round(abs(d30)) in (8, 11, 18) or 80 <= round(abs(d30)) < 90 else 'del '}{abs(d30):.0f}% rispetto ai 30 giorni precedenti: {it(k30['corrente']['ore'])} ore contro {it(k30['precedente']['ore'])}.")
if cur_ratio is not None:
    pk_txt = f" Il picco degli ultimi 90 giorni è {it(peak['rapporto'], 2)} il {peak['data'][8:10]}/{peak['data'][5:7]}." if peak else ""
    obs.append(f"Il rapporto fra carico acuto e cronico è {it(cur_ratio, 2)} ({light(cur_ratio)}, soglie orientative 0,8 e 1,3).{pk_txt} Un valore alto indica solo che il carico recente è salito più in fretta della media abituale.")

# recupero (sonno stimato, HRV, Body Battery, stress)
S = wellness.get("sintesi", {}) if wellness["disponibile"] else {}
def cmp_txt(nome, k, unita, n=1):
    s = S.get(k) or {}
    a, b = s.get("media_7gg"), s.get("media_28gg_prec")
    if a is None:
        return None
    if b is None:
        return f"{nome} {it(a, n)} {unita} (media 7 giorni)"
    return f"{nome} {it(a, n)} {unita} negli ultimi 7 giorni, contro {it(b, n)} nelle 4 settimane prima"
if wellness["disponibile"]:
    parti = [p for p in [cmp_txt("durata del sonno stimata" if wellness.get("sonno_stimato") else "sonno", "sonno_ore", "ore"),
                         cmp_txt("punteggio del sonno", "sonno_punteggio", "su 100", 0),
                         cmp_txt("battito a riposo", "fc_riposo", "bpm", 0), cmp_txt("HRV notturna", "hrv", "ms", 0)] if p]
    hs = wellness.get("hrv_stato_30gg", {})
    nb = hs.get("BALANCED", 0); tot_hs = sum(hs.values())
    hrv_st = f" Garmin classifica l'HRV come equilibrata in {nb} dei {tot_hs} giorni con dato negli ultimi 30." if tot_hs else ""
    obs.append("Recupero: " + "; ".join(parti) + "." + hrv_st + " Sono dati descrittivi: nel rientro dal menisco contano il parere del medico o del fisioterapista e le sensazioni dell'articolazione, più di questi numeri.")
else:
    obs.append("Per sonno, HRV, Body Battery e stress non ci sono dati: per ora non è possibile commentare il recupero. Per il rientro dal menisco valgono le indicazioni del medico o del fisioterapista.")

run = [t for t in tipi if t["tipo"] in RUN]
runkm = sum(t["km"] for t in run); runn = sum(t["uscite"] for t in run)
hiit = next((t for t in tipi if t["tipo"] == "hiit"), None)
w30 = window(act, anchor, 30)
r30 = w30[w30["tipo_attivita"].isin(RUN)]
obs.append(f"Nel periodo disponibile ci sono {len(act)} attività: {runn} di corsa ({runkm:.0f} km) e {hiit['uscite'] if hiit else 0} sedute HIIT. Negli ultimi 30 giorni le uscite di corsa sono {len(r30)} ({it(r30['distanza_km'].sum())} km). Sono dati descrittivi e non sostituiscono il parere di un medico.")

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
print(json.dumps({k: out[k] for k in ["data_riferimento", "dati_aggiornati", "kpi", "osservazioni", "nota_footer"]}, ensure_ascii=False, indent=1))
print(cur_ratio, light(cur_ratio), peak)
print(weekly[-6:])
print(wellness.get("disponibile"), wellness.get("sintesi"), wellness.get("hrv_stato_30gg"))
