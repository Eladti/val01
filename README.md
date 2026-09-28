# VAL01 — Validation Automation Rig

A pytest-based framework for register-level validation of a device under test (DUT)
over a CRC-protected serial protocol. The same test suite runs against:

- **`sim`**: a behavioral model of the DUT, run in CI on every push
- **`hw`**: an Arduino running firmware for the same protocol *(in progress)*

Tests talk only to `DutClient`. The client talks to a `Transport`, and the transport
decides whether the bytes go to the simulator or to a real UART. That boundary is what
lets one test suite validate both targets.

```
tests ──► DutClient ──► Transport ──┬──► SimTransport ──► SimDut (Python model)
                                    └──► SerialTransport ──► Arduino DUT   (planned)
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # simulator target
pytest -m dut -v          # DUT tests only
```

## Docs

- [Protocol & register map](docs/protocol.md): the spec both targets implement
- [Test plan](docs/test_plan.md): requirement → test ID traceability

## Status

- [x] Protocol spec, simulator, client, target-agnostic tests, CI
- [x] Fault injection & client retry policy (found and fixed DEF-001, see test plan)
- [ ] Arduino firmware + hardware-in-the-loop runs
- [ ] Test report generation
