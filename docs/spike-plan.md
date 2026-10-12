# Test-region spike: plan (2026-10-12)

Goal: on Středočeský kraj, measure what a national run costs (time, memory, disk per tile against GitHub Actions limits), how far cheap screening and NoiseModelling disagree, and how reliable RÚIAN building use codes are.

## Decisions (design delegated to Claude by Jan, 2026-10-12)
- Runs on the AI-Workspace PC first (development, whole-region screening, NoiseModelling on 5 sample tiles of different terrain). One measurement on GitHub Actions at the end, in a public test repo, after Jan's yes.
- Internal key `frekno`; repo local until name and licence are decided. Commit identity `Frekno <frekno@localhost>`; switch to Jan's GitHub noreply address before any push.
- Settings: config/spike.toml. Constants: config/acoustics.json (from docs/acoustic_sanity_check.xlsx).
- Terrain DMR 4G (5 m GeoTIFF per SM5 sheet), resampled to 10 m (screening) and 25 m (NoiseModelling); one tile also at 10 m and 50 m.
- Receptors: RÚIAN buildings by use code (config/receptor_types.csv); unclear or missing codes fall back to house-number type (c.p.→home, c.e.→cottage, none→ignore), listed separately in the report. Height 4 m. Source height 2 m.
- Radius 10 km; candidate grid 250 m; tiles 20 km plus 10 km buffer; no candidates on water, buildings or built-up areas or within 500 m of a home.
- Screening: spreading, air absorption (10 C, 70 %), terrain as a barrier (ISO 9613-2 Dz, max 20 dB single, 25 dB double edge), no ground credit; 31.5 Hz with spreading and air absorption only.
- NoiseModelling 6.0.0 (CNOSSOS-EU, bands 63 Hz to 8 kHz): 100 % favourable propagation, ground G from ZABAGED (water, built-up, paved = 0; other = 1) plus an all-hard variant, no forest attenuation, no buildings as obstacles, no reflections. 50 candidates per sample tile spread over the whole screening range; worst 20 receptors per type.
- Report margins against 35 dB(A) (reference) and 47 dB (guidance tier). Inaudible tier waits for a background noise value.
- Camps and campsites: OpenStreetMap points used only as a check list in the report, never published.

## Deliverables
1. Per tile: download size, wall time, peak RAM, peak disk for each step (metrics.csv).
2. Extrapolation to the region and to Czechia against Actions limits (6 h per job, 16 GB RAM, 14 GB disk, 4 CPUs, 20 concurrent jobs, 256 jobs per run).
3. Screening versus NoiseModelling per band on the sample (bias, spread), with and without ground effect.
4. RÚIAN use-code counts for the region and a checked sample.

## Tools on the PC
Python 3.13.16 (C:\AI-Workspace\tools\python313), Temurin JRE 21 (tools\jre21), NoiseModelling 6.0.0 (tools\NoiseModelling_6.0.0). Data in C:\AI-Workspace\data\frekno (not in git).
