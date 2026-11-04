# repair loop on the stored runs

| condition | n | first-pass | after repair | runs repaired | mean coverage (first -> final) |
| --- | --- | --- | --- | --- | --- |
| full | 6 | 4/6 | 5/6 | 2 | 0.972 -> 1.000 |

## per-run detail

| unit | condition | rep | first pass | rounds used | final pass | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U10 | full | 1 | yes | 0 | yes | 1.000 | 0.000 | 0.007 | 0.000 | 0.000 |
| U10 | full | 2 | no | 1 | yes | 1.000 | 0.000 | 0.009 | 0.000 | 1.000 |
| U11 | full | 1 | no | 3 | no | 1.000 | 0.000 | 0.015 | 0.381 | 1.000 |
| U11 | full | 2 | yes | 0 | yes | 1.000 | 0.000 | 0.017 | 0.000 | 1.000 |
| U12 | full | 1 | yes | 0 | yes | 1.000 | 0.000 | 0.054 | 0.000 | 1.000 |
| U12 | full | 2 | yes | 0 | yes | 1.000 | 0.000 | 0.073 | 0.000 | 1.000 |
