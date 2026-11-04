# baseline comparison (per-condition mean, standard deviation in brackets)

| condition | n | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | pass rate | output tok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | 4 | 0.800 (0.163) | 0.000 (0.000) | 0.005 (0.005) | 0.042 (0.083) | 0.625 (0.479) | 1.000 (0.000) | 25% | 1477 |
| rag_mc | 4 | 0.600 (0.231) | 0.000 (0.000) | 0.000 (0.000) | 0.017 (0.033) | 0.375 (0.479) | 1.000 (0.000) | 0% | 2019 |
| zero_shot | 4 | 0.350 (0.191) | 0.125 (0.250) | 0.000 (0.000) | 0.042 (0.083) | 0.000 (0.000) | 1.000 (0.000) | 0% | 1344 |

## per-cell detail

| lecture | condition | repeat | pages | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U41 | full | 1 | 6 | 0.800 | 0.000 | 0.010 | 0.000 | 0.500 | 1.000 | fail |
| U41 | full | 2 | 6 | 1.000 | 0.000 | 0.008 | 0.000 | 1.000 | 1.000 | pass |
| U41 | rag_mc | 1 | 6 | 0.800 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | fail |
| U41 | rag_mc | 2 | 6 | 0.800 | 0.000 | 0.000 | 0.067 | 0.500 | 1.000 | fail |
| U41 | zero_shot | 1 | 6 | 0.600 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | fail |
| U41 | zero_shot | 2 | 6 | 0.400 | 0.000 | 0.000 | 0.167 | 0.000 | 1.000 | fail |
| U42 | full | 1 | 3 | 0.600 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | fail |
| U42 | full | 2 | 6 | 0.800 | 0.000 | 0.000 | 0.167 | 1.000 | 1.000 | fail |
| U42 | rag_mc | 1 | 6 | 0.400 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | fail |
| U42 | rag_mc | 2 | 6 | 0.400 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | fail |
| U42 | zero_shot | 1 | 6 | 0.200 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | fail |
| U42 | zero_shot | 2 | 6 | 0.200 | 0.500 | 0.000 | 0.000 | 0.000 | 1.000 | fail |

config: provider=agnes model=agnes-2.5-flash thinking=default temperature=0.3 repeat=2
