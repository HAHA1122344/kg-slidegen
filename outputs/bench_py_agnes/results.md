# baseline comparison (per-condition mean, standard deviation in brackets)

| condition | n | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | pass rate | output tok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | 6 | 0.972 (0.068) | 0.000 (0.000) | 0.029 (0.028) | 0.008 (0.019) | 0.833 (0.408) | 1.000 (0.000) | 67% | 0 |
| rag_mc | 6 | 0.921 (0.137) | 0.097 (0.153) | 0.019 (0.015) | 0.035 (0.059) | 0.833 (0.408) | 1.000 (0.000) | 33% | 0 |
| zero_shot | 6 | 0.571 (0.351) | 0.083 (0.204) | 0.048 (0.030) | 0.061 (0.071) | 0.333 (0.516) | 1.000 (0.000) | 17% | 181 |

## per-cell detail

| lecture | condition | repeat | pages | coverage_rate | oog_rate | background_rate | prerequisite_violation | misconception_coverage | editability | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U10 | full | 1 | 6 | 1.000 | 0.000 | 0.007 | 0.000 | 0.000 | 1.000 | pass |
| U10 | full | 2 | 6 | 0.833 | 0.000 | 0.009 | 0.000 | 1.000 | 1.000 | fail |
| U10 | rag_mc | 1 | 6 | 1.000 | 0.000 | 0.000 | 0.067 | 1.000 | 1.000 | fail |
| U10 | rag_mc | 2 | 6 | 1.000 | 0.000 | 0.017 | 0.000 | 1.000 | 1.000 | pass |
| U10 | zero_shot | 1 | 6 | 1.000 | 0.000 | 0.024 | 0.000 | 0.000 | 1.000 | pass |
| U10 | zero_shot | 2 | 6 | 0.667 | 0.000 | 0.048 | 0.167 | 0.000 | 1.000 | fail |
| U11 | full | 1 | 7 | 1.000 | 0.000 | 0.012 | 0.048 | 1.000 | 1.000 | fail |
| U11 | full | 2 | 7 | 1.000 | 0.000 | 0.017 | 0.000 | 1.000 | 1.000 | pass |
| U11 | rag_mc | 1 | 7 | 0.857 | 0.000 | 0.009 | 0.000 | 1.000 | 1.000 | fail |
| U11 | rag_mc | 2 | 7 | 1.000 | 0.000 | 0.018 | 0.143 | 1.000 | 1.000 | fail |
| U11 | zero_shot | 1 | 7 | 0.714 | 0.000 | 0.101 | 0.100 | 1.000 | 1.000 | fail |
| U11 | zero_shot | 2 | 7 | 0.714 | 0.000 | 0.040 | 0.100 | 1.000 | 1.000 | fail |
| U12 | full | 1 | 6 | 1.000 | 0.000 | 0.054 | 0.000 | 1.000 | 1.000 | pass |
| U12 | full | 2 | 6 | 1.000 | 0.000 | 0.073 | 0.000 | 1.000 | 1.000 | pass |
| U12 | rag_mc | 1 | 6 | 0.667 | 0.333 | 0.042 | 0.000 | 1.000 | 1.000 | fail |
| U12 | rag_mc | 2 | 6 | 1.000 | 0.250 | 0.031 | 0.000 | 0.000 | 1.000 | pass |
| U12 | zero_shot | 1 | 3 | 0.000 | 0.000 | 0.017 | 0.000 | 0.000 | 1.000 | fail |
| U12 | zero_shot | 2 | 6 | 0.333 | 0.500 | 0.059 | 0.000 | 0.000 | 1.000 | fail |

config: provider=agnes model=agnes-2.5-flash thinking=default temperature=0.3 repeat=2
