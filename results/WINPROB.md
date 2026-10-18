# Live win probability: evaluation

Dev races (tuning): Melbourne, Shanghai, Suzuka, Miami, Montreal, Monte Carlo, Catalunya, Spielberg
Test races (scored once): Silverstone, Spa-Francorchamps, Hungaroring, Zandvoort, Monza, Madring, Baku, Kuala Lumpur, Singapore
Chosen on dev: kappa=4.0, tau=1.0, w=0.8

Scored on every lap from 15 % race distance (lower log-loss / Brier is better):

| Method | Split | Laps | Log-loss | Brier | Top-pick accuracy |
|---|---|---|---|---|---|
| calibrated_simulator | dev | 407 | 0.713 | 0.331 | 75.4% |
| raw_simulator | dev | 407 | 0.999 | 0.448 | 69.0% |
| running_order_prior | dev | 407 | 0.744 | 0.330 | 75.4% |
| leader_takes_all | dev | 407 | 1.693 | 0.477 | 75.7% |
| calibrated_simulator | test | 379 | 1.031 | 0.565 | 60.9% |
| raw_simulator | test | 379 | 1.062 | 0.529 | 55.4% |
| running_order_prior | test | 379 | 1.216 | 0.613 | 60.7% |
| leader_takes_all | test | 379 | 2.709 | 0.766 | 60.9% |

## Test checkpoints

| Race distance | Method | Log-loss | Brier | Top pick |
|---|---|---|---|---|
| 25% | calibrated_simulator | 1.207 | 0.562 | 56% (9 races) |
| 25% | running_order_prior | 1.224 | 0.571 | 56% (9 races) |
| 50% | calibrated_simulator | 1.336 | 0.800 | 44% (9 races) |
| 50% | running_order_prior | 1.463 | 0.853 | 44% (9 races) |
| 75% | calibrated_simulator | 0.836 | 0.526 | 67% (9 races) |
| 75% | running_order_prior | 1.038 | 0.596 | 67% (9 races) |

## Reliability (test, all drivers and laps)

| Predicted | Mean predicted | Observed | n |
|---|---|---|---|
| 0.0–0.1 | 0.007 | 0.007 | 6915 |
| 0.1–0.2 | 0.136 | 0.451 | 213 |
| 0.2–0.3 | 0.235 | 0.056 | 18 |
| 0.3–0.4 | 0.357 | 0.222 | 18 |
| 0.4–0.5 | 0.446 | 0.556 | 18 |
| 0.5–0.6 | 0.554 | 0.286 | 21 |
| 0.6–0.7 | 0.660 | 0.590 | 39 |
| 0.7–0.8 | 0.756 | 0.431 | 72 |
| 0.8–0.9 | 0.837 | 0.538 | 130 |
| 0.9–1.0 | 0.945 | 1.000 | 88 |
