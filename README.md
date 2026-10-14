# Frekno

Site screening for outdoor events in Czechia. For every candidate site on a 250 m grid, Frekno estimates how loud an event's sound system would be at night at the nearest homes, cottages, campsites, hospitals, care homes and recreation areas, using open data from ČÚZK.

Česky: Frekno hledá místa pro venkovní akce v Česku a odhaduje, jak hlasitá bude hudba v noci u nejbližších obydlí a dalších citlivých míst. Vychází z otevřených dat ČÚZK.

## Status

- Work in progress: this repository holds the data pipeline and the website (`web/`). The website runs on the test region's data and is not published yet.
- The model has been checked on one region (Středočeský kraj, 68,853 candidate sites) against NoiseModelling (CNOSSOS-EU). For 80 % of source-receptor pairs the two differ by -0.3 to +3.2 dB(A) (10th to 90th percentile).
- Not yet calibrated with field measurements. Levels are screening estimates, not predictions for a permit or a complaint.

## How it works

- Candidate sites: a 250 m grid without water, buildings, built-up areas and anything within 500 m of a home.
- Receptors in five layers that can be switched off one by one: homes and cottages (RÚIAN building use), campsites, hospitals and care homes, and recreation areas (ZABAGED purpose-built areas).
- Propagation in octave bands from 31.5 Hz to 8 kHz under favourable conditions (downwind or night-time inversion), following the CNOSSOS-EU method (Directive (EU) 2015/996): geometric spreading, air absorption (ISO 9613-1), ground effect, and diffraction over terrain from the DMR 4G terrain model.
- The result per site is the attenuation to its loudest receptors in each layer. It does not depend on the sound system, so rig class, sound character and strictness are applied afterwards.
- Details per site: flat ground within 100 m, distances to forest, roads and tracks, and protected areas (AOPK ČR).
- The website applies the sound system, strictness and filters in the browser. Data comes per 20 km tile in a compact binary format (`pipeline/pack.py`); the model in `web/js/model.js` is checked against a Python reference (`tests/make_web_fixtures.py`). Cardioid subwoofers are an estimate: up to 10 dB less to the rear in the 31.5 and 63 Hz bands.
- Owner lookup: a link opens the parcel at the site in the cadastre (Nahlížení do katastru nemovitostí). German owner data are not public, so sites in the Leipzig area have no such link.

## What it is not

- Not a permit, a measurement or legal advice. The Czech night-quiet rules (Act 251/2016, s. 5) set no dB threshold.
- Not a permission to use a site: every site needs its owner's consent. Owner data is not collected or stored.

## Repository

- `pipeline/`: Python modules for data preparation, receptors, screening and the NoiseModelling comparison
- `config/`: acoustic constants (`acoustics.json`) and run settings (`spike.toml`)
- `tests/`: pytest suite; `tests/known_answers/` holds values from `docs/acoustic_sanity_check.xlsx` that the code must reproduce
- `docs/`: test-region plan and the acoustic sanity-check spreadsheet
- `web/`: the static website without a build step (`index.html`, `js/`, `css/`); node tests in `web/tests/`
- `.github/workflows/`: tests on every push; the national run and the website deploy, all started by hand

## Running the tests

Python 3.13:

```
python -m pip install --only-binary=:all: -r requirements.txt
python -m pytest -q
```

Node 22 for the website tests:

```
node --test "web/tests/*.test.mjs"
```

Data paths for the pipeline runs are set in `config/spike.toml`. To preview the website, pack the data into a folder's `data/` subfolder (`python -m pipeline.cli pack --site-dir <folder>/data`), copy the contents of `web/` into the folder and serve it, for example with `python -m http.server`.

## National run

Three GitHub Actions workflows:

- `national inputs` downloads RÚIAN, ZABAGED, DMR 4G and the AOPK protected areas, prepares receptors, facilities, a smaller ZABAGED file and 10 m terrain per tile (`pipeline/national.py`), and publishes them as a prerelease `inputs-<date>`.
- `national tiles` takes that tag, screens the tiles in groups, adds the spot details, packs the website data and publishes `site-<date>` with `site-data.tar.gz`.
- `site` publishes `web/` with a `site-<date>` release (the newest when no tag is given) on GitHub Pages, together with the public transport stops for the coming weekend (`pipeline/transit.py`, from the JrUtil GTFS files and, for the Leipzig area, the DELFI timetables from gtfs.de). It runs by hand and every Thursday.
- `germany inputs` prepares the same input files for the area within 100 km of Leipzig (in Saxony, Saxony-Anhalt, Thuringia and Brandenburg) from German open data (`pipeline/germany.py`) and publishes `inputs-de-leipzig-<date>`. `national tiles` with the tag prefix `site-de-leipzig` turns it into `site-de-leipzig-<date>`, and `site` adds the newest one to the Czech website data (`pipeline/sites.py`).

`national inputs`, `germany inputs` and `national tiles` are started by hand.

Sites within 10 km of the state border, and in the Leipzig area within 10 km of the area's edge, are left out of the website data and the site says so: homes beyond are not in the receptor data, so estimates there are imprecise. The four military training areas (Boletice, Březina, Hradiště, Libavá) are left out as well, because access to them is restricted by the Ministry of Defence, and so are the military training grounds in the Leipzig area. The same steps run locally with `python -m pipeline.national` and `python -m pipeline.cli`.

## Licences and data

- Code: MIT licence (`LICENSE`).
- Input data: ČÚZK (RÚIAN, ZABAGED, DMR 4G) and AOPK ČR (protected areas), CC BY 4.0. Data published by this project is also CC BY 4.0, with attribution to ČÚZK and AOPK ČR. Base maps on the website: © ČÚZK.
- Leipzig area: © GeoBasis-DE / BKG (VG250, basemap.de with the Basis-DLM of the states, TopPlusOpen base map), © GeoSN, © GeoBasis-DE / LVermGeo ST, © GDI-Th, © GeoBasis-DE/LGB (building outlines, terrain models, orthophotos), [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0); Thuringia's building outlines CC BY 4.0; EEA (Natura 2000, nationally designated areas), CC BY 4.0; timetables DELFI e.V. via [gtfs.de](https://gtfs.de/), CC BY 4.0. Data published by this project for the Leipzig area carries these attributions.
- Public transport: [JrUtil](https://data.jr.ggu.cz/), timetables from CIS JŘ. Stop positions: OpenStreetMap contributors (ODbL); open data of Ostrava (datový podklad © Statutární město Ostrava), Most and the Liberec Region (CC BY-SA 4.0); open data of the Moravian-Silesian Region, Brno and PID (CC BY 4.0); open data of the South Bohemian Region (CC0); further sources collected in jrunify-ext-geodata. The website's stops file (`data/stops.json`) is kept apart from the CC BY 4.0 data and is shared under the terms of these sources (ODbL 1.0 and CC BY-SA 4.0).
- The website loads MapLibre GL JS (BSD-3-Clause) from unpkg.
- NoiseModelling (GPL v3) is used only as a separate program for comparison runs and is not part of this repository.
