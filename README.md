# My Fitness Tracker

Dashboard personale con allenamento e recupero, costruita a partire dai dati del mio account Garmin Connect.

Sito: https://michelesarzana.github.io/connect/

## Cosa mostra

- Panoramica per periodo: ultimi 7 giorni, ultimi 30, tutto lo storico o un intervallo a scelta, confrontati con il periodo precedente o con lo stesso periodo di un anno prima.
- Mappa dei percorsi: tutte le tracce GPS sommate su una mappa scura, filtrabili per tipo e periodo.
- Giorni attivi in una mappa a calendario, filtrabile per tipo di attività e per periodo (6 mesi, 1 anno, sempre).
- Peso con andamento, target di 82 kg e stima di quando arrivarci al ritmo attuale.
- Volume settimanale, ultime attività, recupero (sonno, HRV, battito, stress, Body Battery, SpO2) e carico acuto e cronico.
- Cosa notare: record e serie, abitudini, recupero e carico, proiezioni.

Sono dati descrittivi. Non sono un parere medico o di allenamento.

Il target di peso si cambia in `scripts/compute_metrics.py` (`PESO_TARGET_KG`).

## Come funziona

1. `scripts/fetch_activities.py` tiene l'archivio di tutte le attività in `docs/data/attivita.json`. Al primo giro scarica tutto lo storico, poi solo le ultime settimane e le unisce.
2. `scripts/fetch_tracks.py` scarica le tracce GPS in `docs/data/tracce.json`, semplificate a circa 10 m, al massimo 500 per giro: lo storico si completa in qualche ora. Se qualcosa va storto non blocca l'aggiornamento.
3. `scripts/fetch_wellness.py` scarica sonno, FC a riposo, SpO2, HRV, stress, Body Battery e passi degli ultimi 90 giorni, e il peso degli ultimi 6 anni.
4. `scripts/compute_metrics.py` calcola KPI, serie settimanali, carico e osservazioni e scrive `docs/data/metrics.json`.
5. `scripts/build_dashboard.py` inserisce metriche e archivio nel modello `scripts/template.html` e genera `docs/index.html`.

I file grezzi (CSV e JSON scaricati) finiscono nella cartella `data/`, che non viene versionata.

GitHub Pages pubblica la cartella `docs/` del branch `main`.

## Aggiornamento automatico

Il workflow `.github/workflows/update.yml` si avvia:

- ogni ora, al minuto 17 (pianificazione; GitHub può ritardare le esecuzioni di qualche minuto);
- a mano dalla scheda Actions (`workflow_dispatch`);
- a ogni push su `main` che modifica `scripts/` o il workflow stesso.

- dal tasto aggiorna in alto nella dashboard (vedi sotto).

### Tasto aggiorna

Il tasto con la freccia circolare avvia il workflow tramite l'API di GitHub, segue l'esecuzione e ricarica la pagina quando GitHub Pages ha pubblicato i nuovi dati (di solito 3-5 minuti).

La prima volta chiede una chiave GitHub: un token fine-grained limitato al solo repository `connect`, con il solo permesso Actions in lettura e scrittura. La chiave resta nel `localStorage` di quel browser e non finisce mai nel repository. Si inserisce una volta per dispositivo. Tasto destro (o pressione lunga) sul pulsante riapre il pannello per cambiarla o rimuoverla. Se la chiave scade o viene revocata, il pannello si riapre da solo.

Dopo aver rigenerato la dashboard, fa commit e push solo di `docs/index.html` e `docs/data`, e solo se qualcosa è cambiato.

## Chiave Garmin

La chiave della Garmin Personal API è salvata come segreto di Actions con nome `GARMIN_PERSONAL_KEY` (Settings, Secrets and variables, Actions). Gli script la leggono solo dalla variabile d'ambiente con lo stesso nome. Non compare in nessun file del repository.

Attenzione: la chiave ha una scadenza, scelta quando la si genera (30, 90 o 180 giorni, oppure 1 anno). Alla scadenza il workflow smette di scaricare i dati e fallisce, e la dashboard resta ferma all'ultimo aggiornamento. Per ripartire basta generare una nuova chiave dal profilo Garmin e sostituire il valore del segreto.

## Esecuzione in locale

```
pip install pandas requests
export GARMIN_PERSONAL_KEY=...   # la propria chiave
python scripts/fetch_activities.py
python scripts/fetch_wellness.py
python scripts/compute_metrics.py
python scripts/build_dashboard.py
```

Il risultato è in `docs/index.html`.

## Privacy

Il repository è pubblico e i dati sono pubblici per scelta: nella dashboard e in `docs/data/metrics.json` compaiono i nomi delle ultime attività, i dati di salute (sonno, battito, SpO2, HRV) e il peso. L'archivio `docs/data/attivita.json` contiene data, tipo, distanza, durata, dislivello e FC media di ogni attività, senza nomi. `docs/data/tracce.json` contiene le tracce GPS complete, compresi i punti di partenza e di arrivo: per scelta non sono filtrate. Chi conosce l'indirizzo può leggerli.
