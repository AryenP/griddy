# Backtest: Brownout vs run-now on real grid days

Jobs arrive at 09:00 local and are due 24 h later: training 6 GPU-hours, batch 3 GPU-hours, chat always on at 0.25 busy streams. Watts: this Mac's measured calibration (Apple M2 Pro macOS 15.4.1). Prices: the ISO's day-ahead hourly price at its hub; carbon: the hour's real fuel mix. Regenerate with `uv run python -m dispatcher.backtest` (offline, from docs/evidence/backtest/*.csv).

## CAISO: 14 days, 2026-10-09 to 2026-10-22

| Brownout objective | Energy cost saved vs run-now (median, mean) | Carbon saved (median, mean) | Deadlines met |
|---|---:|---:|---:|
| cost | 1.5 %, 3.4 % | 0.0 %, -0.6 % | 14/14 |
| carbon | -0.2 %, 0.4 % | 0.8 %, 1.3 % | 14/14 |
| balanced | 0.7 %, 2.8 % | 0.5 %, 0.8 % | 14/14 |

Saved per MWh of deferrable work shifted (cost objective): $2.63/MWh.

## ERCOT: 14 days, 2026-10-10 to 2026-10-23

| Brownout objective | Energy cost saved vs run-now (median, mean) | Carbon saved (median, mean) | Deadlines met |
|---|---:|---:|---:|
| cost | 3.3 %, 4.6 % | n/a, n/a | 14/14 |

Carbon n/a for ERCOT: gridstatus serves only today's ERCOT fuel mix, so past days have no hourly carbon; cost only.

Saved per MWh of deferrable work shifted (cost objective): $3.37/MWh.

## Every day

| ISO | Day | Run-now $ | Cost-objective $ | Run-now gCO2 | Carbon-objective gCO2 |
|---|---|---:|---:|---:|---:|
| CAISO | 2026-10-09 | 0.014371 | 0.014371 | 75.9 | 75.5 |
| CAISO | 2026-10-10 | 0.014931 | 0.011353 | 85.3 | 83.9 |
| CAISO | 2026-10-11 | 0.014482 | 0.014106 | 62.3 | 60.1 |
| CAISO | 2026-10-12 | 0.013992 | 0.012826 | 70.7 | 69.2 |
| CAISO | 2026-10-13 | 0.008544 | 0.008298 | 60.6 | 60.0 |
| CAISO | 2026-10-14 | 0.008729 | 0.008705 | 66.0 | 65.8 |
| CAISO | 2026-10-15 | 0.009306 | 0.009306 | 68.1 | 67.7 |
| CAISO | 2026-10-16 | 0.013009 | 0.012983 | 77.1 | 76.8 |
| CAISO | 2026-10-17 | 0.015951 | 0.015734 | 98.5 | 95.2 |
| CAISO | 2026-10-18 | 0.013002 | 0.012976 | 70.0 | 69.4 |
| CAISO | 2026-10-19 | 0.015606 | 0.014935 | 85.8 | 85.8 |
| CAISO | 2026-10-20 | 0.010506 | 0.010332 | 94.1 | 93.7 |
| CAISO | 2026-10-21 | 0.018297 | 0.018237 | 116.2 | 115.8 |
| CAISO | 2026-10-22 | 0.014538 | 0.014241 | 95.1 | 92.7 |
| ERCOT | 2026-10-10 | 0.009154 | 0.008306 | n/a | n/a |
| ERCOT | 2026-10-11 | 0.008744 | 0.008561 | n/a | n/a |
| ERCOT | 2026-10-12 | 0.015656 | 0.014567 | n/a | n/a |
| ERCOT | 2026-10-13 | 0.018223 | 0.017734 | n/a | n/a |
| ERCOT | 2026-10-14 | 0.020255 | 0.018322 | n/a | n/a |
| ERCOT | 2026-10-15 | 0.016308 | 0.014041 | n/a | n/a |
| ERCOT | 2026-10-16 | 0.010828 | 0.010125 | n/a | n/a |
| ERCOT | 2026-10-17 | 0.008699 | 0.008531 | n/a | n/a |
| ERCOT | 2026-10-18 | 0.005719 | 0.005703 | n/a | n/a |
| ERCOT | 2026-10-19 | 0.008718 | 0.008697 | n/a | n/a |
| ERCOT | 2026-10-20 | 0.009582 | 0.009581 | n/a | n/a |
| ERCOT | 2026-10-21 | 0.012376 | 0.012376 | n/a | n/a |
| ERCOT | 2026-10-22 | 0.010424 | 0.009702 | n/a | n/a |
| ERCOT | 2026-10-23 | 0.009379 | 0.009008 | n/a | n/a |
