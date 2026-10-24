# Test fixtures

Everything here is a **real capture** from the demo Mac, saved for tests and frontend development only.
Never shown to a judge as live data.

| File | What |
|---|---|
| `caiso_*.csv` | gridstatus CAISO pull, Fri 23 Oct 2026 ~21:44 PT (first line of each file says so) |
| `real_timeline_calibrate_20261023.jsonl` | `make calibrate` run, 23:11 PT: 1 Hz `power` events while each job ran, knob `action`s, phase `note`s |
| `real_timeline_solve_20261023.jsonl` | `make solve` run, 23:15 PT: live CAISO `grid` signal, `policy`, solved `schedule` |
