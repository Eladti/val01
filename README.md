# VAL01 — Validation Automation Rig

A pytest-based framework for register-level validation of a device under test (DUT)
over a CRC-protected serial protocol. The same test suite runs against three targets:

| Target | DUT                                                                  | Runs in    |
|--------|----------------------------------------------------------------------|------------|
| `sim`  | Python behavioral model                                              | CI         |
| `fw`   | the Arduino sketch compiled for the host, over a pseudo-terminal     | CI         |
| `hw`   | the same sketch on an Arduino Uno/Nano over USB serial               | bench      |

Tests talk only to `DutClient`. The client talks to a `Transport`, and the transport
decides whether the bytes go to the simulator or to a real UART. That boundary is what
lets one test suite validate both targets.

```
tests ──► DutClient ──► Transport ──┬──► SimTransport ────► SimDut (Python model)
                                    └──► SerialTransport ─┬─► pty ──► firmware (host build)
                                                          └─► USB ──► firmware (Arduino)
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # simulator target
pytest -m dut -v          # DUT tests only
pytest --report           # + reports/report.html, results.json, summary.md

pip install -e ".[dev,hw]"
pytest --target fw        # real firmware logic, no board needed (requires g++)
pytest --target hw --port /dev/ttyACM0   # see docs/hw_setup.md
```

## Test report

`pytest --report` writes a traceability report. It joins every requirement in
`docs/test_plan.md` with the tests tagged `@pytest.mark.tp("<ID>")` and gives
each requirement a verdict: PASS / FAIL / SKIPPED / NOT COVERED / N/A / ORPHAN.
CI runs with `--strict-trace`, so a requirement without a test, or a test
without a requirement, fails the build just like a failing test does. The
report is published as the job summary and uploaded as a build artifact.

## Docs

- [Protocol & register map](docs/protocol.md): the spec both targets implement
- [Test plan](docs/test_plan.md): requirement → test ID traceability, defect log
- [Hardware setup](docs/hw_setup.md): wiring, flashing, bring-up

## Status

- [x] Protocol spec, simulator, client, target-agnostic tests, CI
- [x] Fault injection & client retry policy (found and fixed DEF-001, see test plan)
- [x] Arduino firmware, verified on the `fw` target in CI
- [ ] First run on a physical board (`hw`)
- [x] Test report with requirement traceability, CI job summary + artifact
