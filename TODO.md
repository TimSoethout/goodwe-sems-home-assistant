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

## SEMS+ migration follow-up

- [x] Map active SEMS+ inverter status code `5` to `Normal` (#219).
- [ ] Map SEMS+ three-phase telemetry factors
  `PHASE-A:Vac`, `PHASE-B:Vac`, and `PHASE-C:Vac` to the L1/L2/L3 voltage
  entities, with a fixture and regression test (#219).
- [ ] Capture and map SEMS+ cumulative import/export energy for HomeKit/HK1000
  installations; do not derive kWh sensors directly from instantaneous
  `pGrid` or `pConsum` values (#209, #219).
- [ ] Add SEMS+ smart-meter/HomeKit discovery and entity coverage where the
  response provides stable fields (#188, #209, #219).
- [ ] Clarify the primary HomeKit load entity and its sign convention so
  downstream automations do not need duplicate or absolute-value sensors (#202).
- [ ] Validate multi-inverter stations, including distinct entities, device
  metadata, status, and energy counters (#215).

## Reliability and controls

- [ ] Investigate small energy-counter decreases and transient spikes while
  preserving Home Assistant `TOTAL_INCREASING` and daily reset semantics (#212).
- [ ] Reduce token churn and rate-limit repeated legacy/Web reauthentication
  attempts, especially for accounts serving many stations (#192, #184).
- [ ] Verify and improve inverter on/off control for affected inverter models
  without changing the behavior of read-only accounts (#195).
- [ ] Complete evidence-based battery-inverter control coverage, including
  SEMS+ write-token requirements and the distinction between stopping
  generation and immediate charging (#191).
- [ ] Investigate SEMS+ cloud-push/MQTT support before adding a second polling
  path (#184).
- [ ] Investigate EV-charger device and entity support from the new SEMS+
  endpoints (#182).
