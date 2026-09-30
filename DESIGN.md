---
name: VayuSangam Forecast Desk
description: An editorial environmental forecasting desk derived from the VayuSangam reference design.
colors:
  primary: "#56612F"
  primary-soft: "#D3DCC9"
  neutral-bg: "#DDE4D5"
  surface: "#E8EDDF"
  surface-muted: "#D3DCC9"
  ink: "#28321E"
  ink-secondary: "#3e4933"
  text-muted: "#4f5c45"
  line: "#B9C5AD"
  sage: "#8B9D83"
  clay: "#B08B6E"
  terra: "#C66B3D"
  ochre: "#C08E3A"
  inversion: "#7C3AED"
  smoke: "#B08B6E"
  smoke-ink: "#7A593F"
  positive: "#286b4e"
  alert: "#9b4036"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "clamp(1.5rem, 2.5vw, 2.2rem)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Epilogue, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  technical:
    fontFamily: "SFMono-Regular, Consolas, Liberation Mono, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.02em"
rounded:
  sm: "10px"
  md: "16px"
  lg: "22px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "22px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    height: "44px"
    padding: "0 14px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "14px"
  navigation-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    height: "42px"
    padding: "0 11px"
---

## Overview

VayuSangam is a working forecast desk for atmospheric forecasters and monitoring operators. Its visual character follows the supplied redesign: a **sage field journal** with Fraunces display type, Epilogue body type, olive navigation, warm earth accents, compact uppercase metadata and rounded scientific panels.

**The Forecast Sheet Rule.** Every color, line, and label has a job in reading the forecast. Do not add decoration that competes with the AQI, time horizon, map, or model drivers.

## Colors

Sage (#DDE4D5) is the page ground, pale green (#E8EDDF) is the panel surface and muted sage (#D3DCC9) anchors the rail. Deep olive (#28321E) carries text; the reference moss (#606C38) is darkened to #56612F for readable action text. Clay (#B08B6E) marks smoke shapes, with #7A593F used where clay carries text. Terracotta and ochre identify atmospheric conditions. Pollution categories use semantic color plus explicit text.

Use mostly solid surfaces and fine borders. Keep the restrained two-tone green brand mark from the reference. Avoid glass, glow, neon, and decorative gradients.

**The Truth-in-Color Rule.** Use green for operational status only when the app reports it. Never let a color alone imply measured conditions, model skill, or public-health advice.

## Typography

Use Fraunces for the main title and primary readings, Epilogue for interface and explanatory text, and system monospace only for timestamps, units and tabular values. Keep numbers tabular. Metadata labels are compact and uppercase; explanatory copy stays sentence case.

## Layout

At desktop widths, keep navigation on a quiet left rail, the map and forecast workspace in the center, and selected-station context alongside it. The first screen should expose replay state, current AQI proxy, pollutant/met KPIs, the schematic NCR map, and station forecast context. Keep the time control attached to the forecast story.

At phone widths, make the KPI strip a horizontally scrollable row, preserve the map as the main visual, and use the forecast control as a sticky bottom surface. Detail panels become full-width content. Avoid horizontal page overflow; only bounded data strips and tables may scroll horizontally.

## Elevation & Depth

Use thin sage borders and one restrained soft shadow on primary panels. Avoid stacked shadows, blur and translucent glass.

## Shapes

Use 22px rounded primary panels, 14–16px navigation/control surfaces and compact pill badges. Keep station markers crisp and map geometry precise.

## Components

**Metric strip.** Show one prominent AQI proxy followed by PM2.5, O₃, PBL height, ventilation, and relative smoke influence. Preserve labels and units at every viewport.

**Forecast map.** Keep its schematic status visible. Distinguish district boundaries, station marks, demo fire points, and smoke influence in the legend. Station selection must be keyboard operable and expose an AQI/category label.

**Station context.** Pair the AQI proxy and category with pollutant values, a time-aware forecast trace, a clearly labeled prototype interval, and deterministic driver weights. Never present an uncalibrated interval as confidence.

**Time control.** Keep the slider keyboard accessible, display its current hour in text, and provide a real play/pause button. Honor reduced-motion preferences.

**Status.** Keep REPLAY / DEMO state visible near the forecast header. Distinguish a schematic map and surrogate output from live observations or operational model results.

## Do's and Don'ts

- **Do** use moss/olive consistently for active navigation and forecast focus.
- **Do** identify synthetic replay values where they appear.
- **Do** use motion only to acknowledge an action or reveal a state; support reduced motion.
- **Do** keep focus outlines visible and targets comfortably operable on touch screens.
- **Don't** add dark-mode surfaces, decorative hero graphics, or repeated nested card scaffolding.
- **Don't** encode AQI category, inversion, smoke, or status only through color.
- **Don't** make claims of live data, forecast accuracy, or model validation without connected evidence.
