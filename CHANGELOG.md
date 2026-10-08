# Modelling revisions

## 2026-10-08

- Replaced 24-hour lead weather inside a longer price horizon with fixed 48-hour lead weather,
  a six-hour availability buffer and explicit timing guards; removed future backfill.
- Removed VAT double counting from the illustrative dynamic tariff; distinguished its BDEW
  proxy from a supplier quote and exposed annual base charges.
- Removed the incorrect MiSpeL grid-charging allowance. The fixed-feed-in baseline exports PV
  directly and uses the battery only for household supply. Market feed-in is explicitly hypothetical.
- Added a shared inverter throughput limit and start-of-hour inventory/headroom constraints;
  enforced the combined export cap and shared heat-pump capacity during realised operation.
- Kept imputed wear in dispatch but removed it from cash bills, avoiding duplicate replacement
  costs in NPV. Annual import balance now includes battery grid charging.
- Replaced claims of annual upper bounds and guaranteed comfort with rolling benchmarks and
  exported shortfall diagnostics. Clarified synthetic measured-load replays and appliance limits.
- Added targeted regression tests and regenerated the published tables and figures.

Earlier published values used a different tariff and operating-cost convention. The regenerated
results supersede those numbers; see `reports/` and the method assumptions rather than combining
old and new tables.
