# Follow-up TODO

## Energy chart normalization (#228 / #229)

- [x] Replace the unconditional `>1000` chart-value heuristic with a
  capacity-aware Wh-to-kWh conversion.
- [x] Limit conversion to known energy chart fields.
- [x] Preserve cumulative totals and percentage fields.
- [x] Add debug logging whenever a chart value is normalized.
- [x] Add regression coverage for the reported `40633.4 Wh` value.
- [x] Add regression coverage proving that large, plausible kWh values are not
  divided.
- [ ] Ask affected users for the exact entity name and a sanitized raw
  `energeStatisticsCharts` response if the problem recurs.
- [ ] Confirm whether GoodWe exposes an explicit unit or response variant that
  can replace the capacity-based inference.
- [ ] Validate the released behavior with a large installation whose daily
  energy can legitimately exceed `1000 kWh`.
- [ ] Revisit the workaround if the API supplies reliable unit metadata.

## Validation and maintenance

- [ ] Monitor debug logs for unexpected chart normalizations after upgrades.
- [ ] Add a captured response fixture and an entity-level test for any newly
  observed chart field or unit variant.
- [ ] Keep chart normalization separate from `energeStatisticsTotals` unless a
  verified totals-unit issue is reported.
