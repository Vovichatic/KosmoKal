# Extended telemetry sources

The organizer brief explicitly points teams toward NOAA SWPC/NCEI archives and NASA CCMC DONKI, with an emphasis on publication time and reproducible archived responses. The modeling table extends those directions with the following official sources.

| Source | Product used | Model fields | Raw interval | Replay treatment |
|---|---|---|---|---|
| NASA OSDR RadLab | ISS DOSTEL / DosTel, nominal 300 s cadence | absorbed dose rate, particle flux, ISS latitude/longitude/altitude, B, L | 2020-01-01–2024-06-30 | Observation timestamp |
| NOAA NCEI GOES-16 | SGPS L2 5-minute differential proton flux | integral proxies above 10, 50 and 100 MeV | archive availability–2024-06-30 | Observation timestamp |
| NOAA NCEI GOES-16 | XRS L2 1-minute irradiance | A/B channel five-minute maxima and lag/rolling features | 2020-01-01–2024-06-30 | Observation timestamp |
| GFZ Potsdam | Kp, Hp30, Hp60, SN, Fobs, Fadj | geomagnetic activity and solar-cycle context | 2020-01-01–2024-06-30 | Backward as-of merge with product-specific tolerance |
| NASA CCMC DONKI | CME, flare, SEP, GST, IPS and HSS records | latest published event age and notification count | 2020-01-01–2024-06-30 | Joined by `submissionTime`, never future event time |

Missing observations remain missing. They are not replaced with zero. SWPC forecast fields without a publication-aware historical archive remain explicit NaNs in the table.

The May–June 2024 organizer interval is never used for fitting, feature selection, early stopping, threshold selection, or target calibration.
