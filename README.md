# Connect: dashboard Garmin

Dashboard personale con allenamento e recupero, costruita a partire dai dati del mio account Garmin Connect.

Sito: https://michelesarzana.github.io/connect/

## Cosa mostra

- Chilometri, dislivello, ore e uscite degli ultimi 7 e 30 giorni, con il confronto rispetto al periodo precedente.
- Andamento settimanale delle ultime 26 settimane.
- Rapporto fra carico acuto (7 giorni) e cronico (28 giorni), con una lettura orientativa.
- Recupero: sonno (durata, fasi e punteggio), HRV, battito a riposo, SpO2, Body Battery, stress, passi e peso.
- Ultime attività e ripartizione per tipo.

Sono dati descrittivi. Non sono un parere medico o di allenamento.

## Come funziona

1. `scripts/fetch_activities.py` scarica le attività degli ultimi 180 giorni dalla Garmin Personal API.
2. `scripts/fetch_wellness.py` scarica sonno, FC a riposo, SpO2, HRV, stress, Body Battery, passi e peso degli ultimi 90 giorni.
3. `scripts/compute_metrics.py` calcola KPI, serie settimanali, carico e osservazioni e scrive `docs/data/metrics.json`.
4. `scripts/build_dashboard.py` inserisce i dati nel modello `scripts/template.html` e genera `docs/index.html`.

I file grezzi (CSV e JSON scaricati) finiscono nella cartella `data/`, che non viene versionata.

GitHub Pages pubblica la cartella `docs/` del branch `main`.

## Aggiornamento automatico

Il workflow `.github/workflows/update.yml` si avvia:

- ogni giorno alle 05:30 UTC (pianificazione);
- a mano dalla scheda Actions (`workflow_dispatch`);
- a ogni push su `main` che modifica `scripts/` o il workflow stesso.

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

Il repository è pubblico e i dati sono pubblici per scelta: nella dashboard e in `docs/data/metrics.json` compaiono anche i nomi delle attività, i dati di salute (sonno, battito, SpO2, HRV) e il peso. Chi conosce l'indirizzo può leggerli.
