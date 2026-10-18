# Stint forecasting backtest

Dev races (used to choose n0): Melbourne, Shanghai, Suzuka, Miami, Montreal, Monte Carlo, Catalunya, Spielberg
Test races (scored once): Silverstone, Spa-Francorchamps, Hungaroring, Zandvoort, Monza, Madring, Baku, Kuala Lumpur, Singapore

Mean absolute error of the forecast lap time, seconds (lower is better):

| Split | Stints | Laps | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|---|
| dev | 331 | 6035 | 0.564 | 0.651 | 1.233 | 0.963 | 5.901 |
| **test** | 362 | 6274 | 0.610 | 0.673 | 1.530 | 0.843 | 4.268 |

## Test MAE by forecast horizon

| Laps ahead | n | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|
| 1-5 | 1810 | 0.590 | 0.644 | 1.508 | 0.643 | 1.430 |
| 6-10 | 1627 | 0.580 | 0.637 | 1.497 | 0.735 | 3.270 |
| 11+ | 2837 | 0.640 | 0.712 | 1.562 | 1.032 | 6.652 |

## Test MAE by compound

| Compound | Laps | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|
| HARD | 2834 | 0.616 | 0.684 | 1.425 | 0.938 | 3.999 |
| MEDIUM | 1945 | 0.503 | 0.562 | 1.544 | 0.682 | 3.787 |
| SOFT | 1495 | 0.736 | 0.796 | 1.710 | 0.872 | 5.405 |

## Per race (model vs flat)

| Race | Split | Laps | model | flat |
|---|---|---|---|---|
| Melbourne | dev | 498 | 0.601 | 0.804 |
| Shanghai | dev | 649 | 0.412 | 0.918 |
| Suzuka | dev | 770 | 0.397 | 0.563 |
| Miami | dev | 701 | 0.458 | 0.569 |
| Montreal | dev | 805 | 0.665 | 1.995 |
| Monte Carlo | dev | 823 | 0.997 | 1.260 |
| Catalunya | dev | 813 | 0.516 | 0.983 |
| Spielberg | dev | 976 | 0.447 | 0.557 |
| Silverstone | test | 675 | 0.413 | 0.485 |
| Spa-Francorchamps | test | 556 | 0.448 | 0.584 |
| Hungaroring | test | 1036 | 0.541 | 0.717 |
| Zandvoort | test | 882 | 0.524 | 0.666 |
| Monza | test | 739 | 0.598 | 0.703 |
| Madring | test | 813 | 0.913 | 1.455 |
| Baku | test | 534 | 0.430 | 1.217 |
| Kuala Lumpur | test | 236 | 1.594 | 1.135 |
| Singapore | test | 803 | 0.605 | 0.854 |

## Shrinkage tuning (dev only, model MAE)

| n0 | MAE |
|---|---|
| 0.0 | 0.802 |
| 1.0 | 0.696 |
| 3.0 | 0.616 |
| 6.0 | 0.581 |
| 12.0 | 0.564 |
| 1000000000.0 | 0.565 |
