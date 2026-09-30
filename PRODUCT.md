# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are atmospheric forecasters and monitoring operators working with Delhi NCR air-quality conditions. Smart India Hackathon judges are the main audience for the current local prototype demonstration.

## Product Purpose

VayuSangam presents a 72-hour Delhi NCR air-quality forecast alongside meteorology, inversion, boundary-layer ventilation, and transported-smoke context. Success means an operator can inspect the forecast trend, select a station, and understand which modeled conditions contribute to a change.

## Positioning

The prototype makes the weather–pollution feedback loop explicit: prior PM2.5 loading adjusts the next meteorological state, which then feeds the next pollutant forecast step. It presents this coupled surrogate alongside its process drivers.

## Operating Context

The prototype runs locally and defaults to deterministic replay so the demonstration works without external data services. The current episode is synthetic and supports a scientific workflow demonstration, not a historical event reconstruction.

## Capabilities and Constraints

- Overview, station forecast, 72-hour time control, inversion diagnostics, smoke transport, coupling comparison, scenario simulation, and a verification framework are available in the prototype.
- The displayed AQI is a PM2.5 sub-index proxy, not a complete regulatory AQI.
- Smoke Influence Index is a relative transport indicator, not an emissions inventory.
- Replay values are synthetic. No live CPCB, FIRMS, CAMS, ERA5, WRF-Chem, or NCUM data is connected, and no scientific skill scores are available.
- The map is schematic. Operational WRF-Chem/NCUM adapters and verified historical evaluation remain planned.
- Preserve current forecast interactions, model-status honesty, and replay-first reliability through the visual redesign.

## Brand Commitments

Product name: VayuSangam. Team: LogiNexa. Context: Smart India Hackathon 2026, Problem Statement 26082, air pollution–weather coupled forecasting for Delhi NCR.

## Evidence on Hand

The repository contains deterministic synthetic replay data in `demo/replay/`, a functioning coupled surrogate, and local API-backed frontend interactions. No validated historical observations, live integrations, operational chemistry model results, or measured model skill are available.

## Product Principles

- Make AQI state, forecast trend, inversion/stagnation, and smoke influence easy to scan.
- Explain forecast changes with traceable model-derived conditions.
- Identify replay, synthetic data, uncertainty, and unavailable evidence clearly.
- Keep the full demonstration usable offline and without credentials.
- Treat the weather–pollution feedback loop as a core product mechanism.

## Accessibility & Inclusion

Use semantic controls, keyboard access, visible focus, reduced-motion support, readable contrast, and non-color labels for AQI categories and forecast states.
