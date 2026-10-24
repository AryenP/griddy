# OpenADR test fixtures (test-only, never shown to a judge)

- `heat_wave_import_limit.json`: the minimal OpenADR 3.1 EVENT from RESEARCH.md ("The request format"),
  adapted from an OpenLEADR-rs fixture. One `IMPORT_CAPACITY_LIMIT` interval of 0.07 kW (70 W) for
  `PT10M` starting 2026-10-25 18:00 UTC. Used by `tests/test_agent_intake.py` to check `parse_openadr`.
  Live events come from a VTN (e.g. OpenLEADR-rs) at runtime, not from this file.
