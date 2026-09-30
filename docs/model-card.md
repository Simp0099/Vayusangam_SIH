# Model card — VayuSangam surrogate prototype

## Status and intended use

This is a **PROTOTYPE / REPLAY** workflow demonstration for SIH PS 26082. It is for demonstrating normalized forecast inputs, coupled rollout structure, diagnostics, transport visualization and explainability flow. It is not suitable for operational alerts, public-health decisions, regulatory reporting or scientific AQI forecasting.

## Inputs and outputs

The deterministic surrogate uses synthetic station initial PM2.5/O3/NO2, a diurnal synthetic meteorology sequence, derived PBLH/ISI/ventilation, and a fixed synthetic fire fixture. It emits 72 hourly pollutant and meteorology diagnostic values, AQI display proxies, relative smoke transport and deterministic feature-state explanation values.

## Architecture

At each hour, previous PM2.5 influences an aerosol feedback term. Feedback adjusts the next meteorology state (T2m/PBLH); corrected ISI and ventilation plus relative smoke influence are used by a bounded PM2.5 recurrence. O3 has a separate diurnal response equation. A fixed-seed NumPy particle simulation advects and diffuses particles and exponentially reduces relative particle intensity with age.

The bundled rollout fits `PM25Forecaster` on a fixed-seed synthetic fixture. When LightGBM is installed it exercises LightGBM quantile regressors; in the minimal install it uses the transparent deterministic demo equation. A separate O3 component models diurnal response without smoke as a direct feature. Fixture fitting is not scientific training or validation.

## Uncertainty

The UI shows a prototype interval around AQI values only to visualize forecast spread. It is not a calibrated interval, and no confidence percentage or PICP is available. Do not interpret it as statistical coverage.

## Data and evaluation

All bundled values are fixed-seed **DEMO / REPLAY DATA** and are not observations or an actual historical episode. No MAE, RMSE, bias, F1, coverage, benchmark or improvement claim is made. Scientific evaluation requires timestamp-aligned quality-controlled observations, documented data splits, baselines and independent held-out evaluation.

## Known limitations

See [limitations.md](limitations.md). Main limits include synthetic meteorology and pollutant initialization, simplified chemistry and aerosol feedback, schematic spatial representation, relative smoke transport, no emissions inventory, limited source separation, no live data ingestion, and no operational WRF-Chem/NCUM execution.
