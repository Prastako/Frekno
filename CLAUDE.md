# Frekno pipeline

## What it is
Python pipeline for a public tool that finds outdoor spots in Czechia where event sound will not disturb homes. Per map tile it prepares terrain, building and land-cover data, estimates the sound loss from candidate spots to nearby houses, and records run time and disk use.

## Commands
- Tests: `npm test 2>&1 | tail -15` (pytest on C:\AI-Workspace\tools\python313\python.exe). One file: `npm test -- tests/test_x.py 2>&1 | tail -15`.
- Python for other commands: `C:/AI-Workspace/tools/python313/python.exe`.
- Installed packages: numpy, scipy, rasterio, pyproj, shapely, pyogrio, geopandas, pandas, psutil, pytest, requests. Nothing else. Never install packages; no internet.

## Structure
- `pipeline/`: Python package, one module per job. `pipeline/fetch/`: downloaders.
- `config/`: acoustics.json (bands, weights, spectra, classes), spike.toml (settings), receptor_types.csv.
- `tests/`: test_<module>.py. `tests/known_answers/`: expected values from the acoustic spreadsheet. `tests/fixtures/`: small test data.

## Conventions
- Python 3.13, standard library first, type hints, plain functions (no classes unless the task asks).
- Coordinates: S-JTSK, EPSG:5514, metres. x = easting, y = northing; both are negative in Czechia.
- Octave bands always in this order: 31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000 Hz. Band lists have 9 floats.
- Levels and attenuations in dB as floats. Never round inside functions.
- Paths with pathlib. Repo root from a module in pipeline/: `Path(__file__).resolve().parents[1]`.
- Tests: pytest, plain asserts, floats with `pytest.approx(..., abs=...)`. Temporary files only in pytest's `tmp_path`.
- Keep changes minimal. Do not reformat or rewrite code the task does not mention.
- Code, comments and REPORT.md in English.

## Do not touch
- `config/`, `tests/known_answers/`, `tests/fixtures/`, `docs/`, `package.json`, `pyproject.toml`, `requirements.txt` (maintained by the supervisor), unless the task says so.
