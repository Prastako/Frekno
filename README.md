# Frekno (working title)

Search tool for outdoor event spots in Czechia where the sound will not disturb people living nearby. This repository currently holds the test-region spike: data preparation, screening and NoiseModelling runs for Středočeský kraj, with time and disk measurements against GitHub Actions limits.

- `pipeline/`: Python modules
- `config/`: acoustic constants and spike settings
- `tests/known_answers/`: values from `docs/acoustic_sanity_check.xlsx` that the code must reproduce
- `docs/spike-plan.md`: what the spike measures and why

Data sources (CC BY 4.0): ČÚZK (DMR 4G, ZABAGED, RÚIAN).
