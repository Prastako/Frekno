# Frekno

Site screening for outdoor events in Czechia. For every candidate site on a 250 m grid, Frekno estimates how loud an event's sound system would be at night at the nearest homes, cottages, campsites, hospitals, care homes and recreation areas, using open data from ČÚZK.

Česky: Frekno hledá místa pro venkovní akce v Česku a odhaduje, jak hlasitá bude hudba v noci u nejbližších obydlí a dalších citlivých míst. Vychází z otevřených dat ČÚZK.

## Status

- Work in progress: this repository holds the data pipeline; the website is not built yet.
- The model has been checked on one region (Středočeský kraj, 68,853 candidate sites) against NoiseModelling (CNOSSOS-EU). For 80 % of source-receptor pairs the two differ by -0.3 to +3.2 dB(A) (10th to 90th percentile).
- Not yet calibrated with field measurements. Levels are screening estimates, not predictions for a permit or a complaint.

## How it works

- Candidate sites: a 250 m grid without water, buildings, built-up areas and anything within 500 m of a home.
- Receptors in five layers that can be switched off one by one: homes and cottages (RÚIAN building use), campsites, hospitals and care homes, and recreation areas (ZABAGED purpose-built areas).
- Propagation in octave bands from 31.5 Hz to 8 kHz under favourable conditions (downwind or night-time inversion), following the CNOSSOS-EU method (Directive (EU) 2015/996): geometric spreading, air absorption (ISO 9613-1), ground effect, and diffraction over terrain from the DMR 4G terrain model.
- The result per site is the attenuation to its loudest receptors in each layer. It does not depend on the sound system, so rig class, sound character and strictness are applied afterwards.

## What it is not

- Not a permit, a measurement or legal advice. The Czech night-quiet rules (Act 251/2016, s. 5) set no dB threshold.
- Not a permission to use a site: every site needs its owner's consent. Owner data is not collected or stored.

## Repository

- `pipeline/`: Python modules for data preparation, receptors, screening and the NoiseModelling comparison
- `config/`: acoustic constants (`acoustics.json`) and run settings (`spike.toml`)
- `tests/`: pytest suite; `tests/known_answers/` holds values from `docs/acoustic_sanity_check.xlsx` that the code must reproduce
- `docs/`: test-region plan and the acoustic sanity-check spreadsheet

## Running the tests

Python 3.13:

```
python -m pip install --only-binary=:all: -r requirements.txt
python -m pytest -q
```

Data paths for the pipeline runs are set in `config/spike.toml`.

## Licences and data

- Code: MIT licence (`LICENSE`).
- Input data: ČÚZK (RÚIAN, ZABAGED, DMR 4G), CC BY 4.0. Data published by this project is also CC BY 4.0, with attribution to ČÚZK.
- NoiseModelling (GPL v3) is used only as a separate program for comparison runs and is not part of this repository.
