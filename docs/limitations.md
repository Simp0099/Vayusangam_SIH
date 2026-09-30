# Prototype limitations

- The current provider is a deterministic surrogate, not operational WRF-Chem or NCUM.
- Demo/replay values are synthetic and are not scientific validation or historical observations.
- Smoke Influence Index is a relative transport indicator, not an emissions inventory, fire detection product or exposure estimate.
- The prototype has limited local/regional source separation and no calibrated chemical mechanism.
- The 72-hour display is a schematic/downscaled prototype view; no validated high-resolution grid is connected.
- Real historical data must be connected before computing verification metrics.
- CPCB/OpenAQ, FIRMS, CAMS and ERA5 integrations are planned provider interfaces; no live integration is currently active.
- The map and particle display are schematic inline SVG, not a live basemap or geospatially rigorous plume raster.
- The PM2.5 model uses a synthetic training fixture for demo pipeline behavior; it is not trained on real air-quality measurements.
- Verification framework returns no invented values. WRF-Chem and NCUM integrations are planned.
