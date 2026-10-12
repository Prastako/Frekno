# Known answers

Values taken from `docs/acoustic_sanity_check.xlsx` (2026-10-12) and checked against an independent recalculation (largest difference 5e-12 dB). Code must reproduce them; tolerance 0.01 dB unless a test says otherwise.

| File | Rows | Content |
|---|---|---|
| air_absorption.csv | 9 | ISO 9613-1 air absorption in dB/km at 10 C, 70 % RH, 101.325 kPa, exact band centres |
| attenuation_from_1m.csv | 54 | spreading plus air absorption from 1 m to 0.5, 1, 2, 3, 5 and 10 km, per band |
| character_levels.csv | 3 | dB(A) and dB(C) of each character spectrum in config/acoustics.json |
| receptor_levels.csv | 486 | band level at the receptor for 3 classes x 3 characters x 6 distances x 9 bands |
| margins.csv | 54 | dB(A), dB(C), margin to the 35 dB(A) reference (35 minus dB(A)) and worst band margin to the hearing threshold (min of threshold minus level) |

Model: level at d = character bands shifted so their dB(A) equals the class level, minus 20 log10(d / class distance), minus air absorption x (d - class distance). Point source, free field.
