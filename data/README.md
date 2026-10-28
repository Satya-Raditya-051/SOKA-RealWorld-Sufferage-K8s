# Benchmark data

`GoCJ_Dataset_100.txt` contains the published 100-job GoCJ workload in
millions of instructions. The benchmark uses the first 24 rows in their
published order; it does not generate replacement values or invent network
input sizes.

Source: Altaf Hussain and Muhammad Aleem, *GoCJ: Google Cloud Jobs Dataset for
Distributed and Cloud Computing Infrastructures*, Data 2018, 3(4), 38.

- DOI: https://doi.org/10.3390/data3040038
- Dataset DOI: https://doi.org/10.17632/b7bp6xhrcd.1
- License: Creative Commons Attribution 4.0

The `source_mi` value is research metadata. `scheduler/datasets.py` maps it to
deterministic executable PBKDF2 work while preserving job-size ratios. GoCJ
contains no per-job input-data size, so its network input is zero.
