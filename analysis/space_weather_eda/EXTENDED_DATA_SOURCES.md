# Extended telemetry sources

The organizer brief explicitly points teams toward NOAA SWPC/NCEI archives and NASA CCMC DONKI, with an emphasis on publication time and reproducible archived responses. The modeling table extends those directions with the following official sources.

| Source | Product used | Model fields | Raw interval | Replay treatment |
|---|---|---|---|---|
| NASA OSDR RadLab | ISS DOSTEL / DosTel, nominal 300 s cadence | absorbed dose rate, particle flux, ISS latitude/longitude/altitude, B, L | 2020-01-01–2024-06-30 | Observation timestamp |
| NOAA NCEI GOES-16 | SGPS L2 5-minute differential proton flux | integral proxies above 10, 50 and 100 MeV | archive availability–2024-06-30 | Observation timestamp |
| NOAA NCEI GOES-16 | XRS L2 1-minute irradiance | A/B channel five-minute maxima and lag/rolling features | 2020-01-01–2024-06-30 | Observation timestamp |
| NOAA NCEI GOES-16 | MPS-HI L2 5-minute particle flux | 50 keV–4 MeV electron bands, >2 MeV electrons, 1/5 MeV proton proxies | 2023-01-01–2024-06-30 | Observation timestamp; experimental ablation only |
| NASA SPDF CDAWeb ACE | SWEPAM/MFI/EPAM preliminary key parameters | solar-wind speed/density, IMF/Bz, energetic ions/electrons | 2023-01-01–2024-06-30 | Observation timestamp plus 1-hour safety lag; experimental ablation only |
| GFZ Potsdam | Kp, Hp30, Hp60, SN, Fobs, Fadj | geomagnetic activity and solar-cycle context | 2020-01-01–2024-06-30 | Backward as-of merge with product-specific tolerance |
| NASA CCMC DONKI | CME, flare, SEP, GST, IPS and HSS records | latest published event age and notification count | 2020-01-01–2024-06-30 | Joined by `submissionTime`, never future event time |

Missing observations remain missing. They are not replaced with zero. SWPC forecast fields without a publication-aware historical archive remain explicit NaNs in the table.

ACE is downloaded through the official CDAWeb HAPI datasets `AC_K0_SWE`,
`AC_K0_MFI` and `AC_H1_EPM`. The K0 streams are preliminary browse products
and can be revised. MPS-HI files are official NOAA Level-2 archives. Because
neither archive provides a complete per-record publication history, these
features are treated as an offline ablation rather than proof of strict replay.

Definitive high-resolution OMNI was deliberately not used in the operational
feature set: the combined product is published with processing delay and would
overstate real-time availability.

The May–June 2024 organizer interval is never used for fitting, feature selection, early stopping, threshold selection, or target calibration.

Official references:

- NASA CDAWeb HAPI: `https://cdaweb.gsfc.nasa.gov/hapi`;
- NASA CDAWeb dataset notes: `https://cdaweb.gsfc.nasa.gov/misc/master_notes.html`;
- NOAA MPS-HI Level-2 guide:
  `https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/docs/GOES-R_SEISS_L2_MPS-HI.ReadMe.pdf`.
