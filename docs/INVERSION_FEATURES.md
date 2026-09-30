# VayuSangam — Inversion Features

## What an inversion is, stated explicitly

A **surface (radiation) inversion** exists when temperature **increases with height** over some
layer near the ground. The standard diagnostic uses a temperature *difference* between a lower and
an upper level at the same location and time:

    ΔT(k) = T(k hPa) − T(2 m)

For k = 925 hPa: a surface inversion is present when `ΔT(925) > 0`.
For k = 850 hPa: same rule.

`k = 925 hPa` is the level most directly tied to the lower troposphere/valley layer over the
Delhi basin; `850 hPa` gives a deeper-layer view. Both are computed, neither is assumed.

## Feature table

| Variable | Formula | Source | Interpretation | Limitations |
|---|---|---|---|---|
| `T2m` | 2 m temperature | ERA5 `2m_temperature` (K) | Surface air temperature | Reanalysis, not station-observed; 0.25° grid |
| `T925` | temperature @ 925 hPa | ERA5 `reanalysis-era5-pressure-levels` / `temperature` (K) | Lower-troposphere temperature | Same reanalysis bias as T2m; biases partly cancel in the difference |
| `T850` | temperature @ 850 hPa | ERA5 `reanalysis-era5-pressure-levels` / `temperature` (K) | Mid-lower troposphere | — |
| `dT_925_2m` | `T925 − T2m` | derived | **> 0 ⇒ surface inversion diagnosed at 925 hPa** | A positive difference over 0.25°/1 hour is a *proxy*, not a collocated radiosonde inversion |
| `dT_850_2m` | `T850 − T2m` | derived | **> 0 ⇒ surface inversion diagnosed at 850 hPa** | Same caveats; stronger-mixing layers may mask shallow inversions |
| `PBLH` | boundary layer height | ERA5 `boundary_layer_height` (m) | Height to which the atmosphere is well mixed; small PBLH traps pollutant | Bulk Richardson-number diagnostic; known to be biased in stable/very stable conditions, which is exactly the regime that matters here |
| `u_wind`, `v_wind` | 10 m u/v components | ERA5 `10m_u_component_of_wind`, `10m_v_component_of_wind` (m s⁻¹) | Wind vector for transport direction | 10 m is a proxy for the near-surface mixing layer under unstable conditions; under inversion the effective transport height differs |
| `wind_speed_10m` | `sqrt(u²+v²)` | derived | — | — |
| `wind_direction_10m` | meteorological-from convention: `(atan2(-u,-v)·180/π + 360) mod 360` | derived | Direction wind comes *from* | Must be stated in code; the 180° flip is a classic silent bug |

## Inversion-episode flag (derived, labelled as derived)

A candidate trapping episode at a grid cell and hour:

    inversion_candidate = (dT_925_2m > 0) AND (PBLH < PBLH_p50) AND (wind_speed_10m < V_thresh)

**This is a screening heuristic, not a confirmed inversion.** It requires a threshold choice
(`PBLH_p50`, `V_thresh`) that is scientifically consequential. VayuSangam will not hard-code
these before the user agrees on them; they must be estimated on training-period data only and
frozen in the manifest.

## Limitations that must travel with these features

1. ERA5 and Open-Meteo are **not independent** — Open-Meteo serves ERA5/ERA5-Land. Feeding both to
   a model leaks the same reanalysis twice and inflates apparent skill.
2. ERA5 0.25° cells (~25 km) are far coarser than Delhi's mixed-layer structure; a grid-cell
   "inversion" may not exist at the station.
3. Reanalysis over India is known to be weak in the nocturnal boundary layer. A `dT_925_2m`
   derived from ERA5 should be validated against ground temperature before it is trusted.
4. Two-level differences cannot detect elevated/capping inversions above 850 hPa.
5. **Association is not causation.** Inversion co-occurrence with high PM2.5 is a predictive
   relationship. It does not establish that the inversion caused the concentration.

## Status

All rows above are **specifications**. No ERA5 data has been downloaded, so no inversion feature
has been computed or verified yet. The loader will assert units against `docs/UNITS.md`.
