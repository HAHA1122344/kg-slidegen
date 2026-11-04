# baseline comparison (per-condition mean, standard deviation in brackets)

| condition | n | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | pass rate | output tok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | 4 | 0.900 (0.115) | 0.000 (0.000) | 0.002 (0.003) | 0.042 (0.083) | 0.875 (0.250) | 1.000 (0.000) | 50% | 4728 |
| rag_mc | 4 | 0.700 (0.383) | 0.000 (0.000) | 0.000 (0.000) | 0.060 (0.079) | 0.375 (0.479) | 1.000 (0.000) | 25% | 2645 |

## per-cell detail

| lecture | condition | repeat | pages | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U41 | full | 1 | 6 | 0.800 | 0.000 | 0.006 | 0.000 | 1.000 | 1.000 | fail |
| U41 | full | 2 | 6 | 1.000 | 0.000 | 0.000 | 0.000 | 0.500 | 1.000 | pass |
| U41 | rag_mc | 1 | 6 | 1.000 | 0.000 | 0.000 | 0.000 | 0.500 | 1.000 | pass |
| U41 | rag_mc | 2 | 6 | 1.000 | 0.000 | 0.000 | 0.071 | 0.000 | 1.000 | fail |
| U42 | full | 1 | 6 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | pass |
| U42 | full | 2 | 6 | 0.800 | 0.000 | 0.000 | 0.167 | 1.000 | 1.000 | fail |
| U42 | rag_mc | 1 | 6 | 0.600 | 0.000 | 0.000 | 0.167 | 0.000 | 1.000 | fail |
| U42 | rag_mc | 2 | 6 | 0.200 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | fail |

config: provider=deepseek model=deepseek-v4-flash thinking=default temperature=0.3 repeat=2