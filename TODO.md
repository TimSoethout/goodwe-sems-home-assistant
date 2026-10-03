# Follow-up work

Architecture and evidence requirements are in
[`ARCHITECTURE_PLAN.md`](./ARCHITECTURE_PLAN.md). Keep this file to work that
is not yet complete. Before changing a mapping, add sanitized captured
evidence and fixture-backed regression coverage where practical.

## SEMS+ behavior and entity coverage

- [ ] Validate HomeKit-only setup against a sanitized SEMS+ response with no
  inverter-like devices but available station flow (#187, #257). The current
  regression test covers the coordinator boundary using the captured
  `station_flow.json`; it does not prove the API returns this combination.
- [ ] Validate a multi-inverter station end to end (#215). Capture at least two
  devices with distinct output/model/status and assert unique entities,
  metadata, per-device requests, and independent counters. One idle or
  incomplete device must not overwrite another.
- [ ] Create stable PV string entities when MPPT factors are absent in the
  first refresh, leaving their state unavailable until later telemetry
  supplies a value. Test entity identity across refreshes (#219).
- [ ] Verify and document the canonical HomeKit load entity and its sign
  convention with paired import/export evidence (#202, #234). Do not apply
  `abs()` or reverse signs without a capture proving the direction.
- [ ] Verify HomeKit lifetime import/export totals from captured responses and
  final Home Assistant entity states, including `TOTAL_INCREASING` reset
  behavior (#212). Never derive energy from instantaneous flow power.
- [ ] Preserve legacy inverter attribute aliases such as `vload`, `iload`, and
  `soc` only where a captured device response supports them; add regression
  coverage for each alias and its units/nullability (#219).
- [ ] Document fields not supplied by tested single-phase or non-generator
  contracts, including phase 2/3, generator, detailed load-status, and
  `grid_meter_power` fields. Investigate `profitProStats` and
  `profitGridStats` before exposing income entities (#219).
- [ ] Capture and sanitize a station-production response. Verify its totals
  and currency fields against the existing optional request; add parser and
  entity tests only for fields confirmed by that response (#219).
- [ ] Evaluate the HEMS power-graph endpoint only after capturing import and
  export cases that establish sign, unit, and timestamp semantics. Do not add
  a second graph/data path until it has a clear entity use.
- [ ] Confirm whether battery-rack, dongle, and other supported device
  mappings need additional model/region fixtures (#219). Keep unrelated
  device telemetry out of inverter entities.

## Authentication, permissions, and reliability

- [ ] Validate SEMS+ Web login and refresh across supported account roles and
  regions, including accounts that return `100004`, before removing legacy
  authentication fallback (#219).
- [ ] Collect sanitized cases for expired Web tokens and `C0602`; confirm a
  bounded renew-and-retry path and reduce duplicate error logging without
  retrying permission or rate-limit failures (#192, #219).
- [ ] Investigate recurring telemetry `100025` separately from authentication
  failures. Record endpoint, region, device type, and account/station
  permission context from sanitized evidence (#219); do not add speculative
  fallback requests.
- [ ] Measure repeated authentication and `GY0429` behavior across
  multi-station setups. Reduce unnecessary token churn while preserving
  endpoint-specific token profiles and a bounded retry policy (#192).
- [ ] Validate and then consider removing legacy inverter-control fallback
  across older inverter models, regions, and permission levels. Keep
  monitoring and write permissions distinct (#195).
- [ ] Complete compatibility evidence for existing battery immediate-charging
  controls and identify any additional supported battery controls. Verify
  write permissions and state transitions; keep these distinct from inverter
  stop/start and add new controls only from captured request/response contracts
  (#191, #234).

## Energy counters and chart normalization

- [ ] Investigate small counter decreases and transient spikes using
  timestamped captures across reset, reconnect, and cloud correction. Preserve
  Home Assistant `TOTAL_INCREASING` semantics; do not clamp decreases without
  evidence (#212).
- [ ] Determine whether GoodWe provides explicit units for chart values that
  can replace the capacity-aware Wh-to-kWh heuristic. Prefer field-level unit
  metadata if a stable contract is found (#228, PR #229).
- [ ] Validate chart normalization with a large installation where daily
  energy can legitimately exceed `1000 kWh`; compare the sanitized payload,
  capacity, and final Home Assistant states (#228, PR #229).
- [ ] Monitor redacted debug logs for unexpected chart conversions after
  releases. Keep chart normalization restricted to known daily energy fields
  and separate from `energeStatisticsTotals` unless a totals-unit issue is
  demonstrated (#228, PR #229).
- [ ] Add a sanitized fixture and entity-level test for every newly observed
  chart field or unit variant before mapping it.

## Evidence and exploratory work

- [ ] Add sanitized fixtures and focused tests for newly observed response
  codes and optional fields. Missing values must stay unavailable rather than
  becoming fabricated zeroes.
- [ ] Review captures for credentials, tokens, cookies, signatures, station
  IDs, serials, trace IDs, names, and other personal data before sharing or
  committing them. Do not commit raw browser/HAR files.
- [ ] Investigate whether GoodWe exposes a supported cloud-push/MQTT/WebSocket
  contract before considering a second polling path. Retain bounded HTTPS
  polling unless a documented push contract proves more reliable (#184).
- [ ] Investigate EV-charger discovery, telemetry, counters, and related
  devices from a real station capture. Model a charger separately; do not
  merge charger power into inverter power by default (#182).
