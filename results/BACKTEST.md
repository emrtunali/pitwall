# Stint forecasting backtest

Dev races (used to choose n0): Melbourne, Shanghai, Suzuka, Miami, Montreal, Monte Carlo, Catalunya, Spielberg
Test races (scored once): Silverstone, Spa-Francorchamps, Hungaroring, Zandvoort, Monza, Madring, Baku, Kuala Lumpur, Singapore

Mean absolute error of the forecast lap time, seconds (lower is better):

| Split | Stints | Laps | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|---|
| dev | 331 | 6035 | 0.564 | 0.651 | 1.233 | 0.963 | 5.901 |
| **test** | 362 | 6289 | 0.610 | 0.672 | 1.527 | 0.844 | 4.294 |

## Test MAE by forecast horizon

| Laps ahead | n | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|
| 1-5 | 1810 | 0.592 | 0.645 | 1.505 | 0.649 | 1.438 |
| 6-10 | 1634 | 0.578 | 0.633 | 1.494 | 0.731 | 3.293 |
| 11+ | 2845 | 0.639 | 0.711 | 1.560 | 1.033 | 6.685 |

## Test MAE by compound

| Compound | Laps | model | no_deg | driver_median | flat | linear |
|---|---|---|---|---|---|---|
| HARD | 2836 | 0.617 | 0.684 | 1.422 | 0.937 | 4.009 |
| MEDIUM | 1948 | 0.503 | 0.562 | 1.542 | 0.680 | 3.787 |
| SOFT | 1505 | 0.735 | 0.790 | 1.707 | 0.881 | 5.486 |

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
| Zandvoort | test | 897 | 0.526 | 0.677 |
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
