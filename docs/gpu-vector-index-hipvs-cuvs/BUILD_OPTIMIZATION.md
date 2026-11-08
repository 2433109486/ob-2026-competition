# CAGRA build optimization (contest submission)

## What changed

`tools/hipvs_bridge/seekdb_cuvs_bridge.c` used the V5 baseline parameters:

```c
build_algo = NN_DESCENT;
graph_degree = 128;
intermediate_graph_degree = 256;
nn_descent_niter = 100;
```

NN-Descent is experimental in cuVS/hipVS and is run for **100 refinement
iterations** over a 256-degree intermediate graph.  For 250K vectors this is
the dominant part of `CREATE VECTOR INDEX ... lib=cuvs`.

The submission builds the same 128/256-degree graph with IVF-PQ instead:

```c
build_algo = IVF_PQ;                 // default
graph_degree = 128;                  // unchanged
intermediate_graph_degree = 256;     // unchanged
```

IVF-PQ produces the all-neighbours graph in one batched pass and is the
production default for large N in cuVS/hipVS.  Graph degree is kept at the
baseline value so the recall gates (SIFT250K 0.95, Hidden250K 0.90/0.85) are
not traded away.

`SEEKDB_CUVS_BUILD_ALGO=nn_descent` restores the baseline algorithm so the two
paths can be measured in the same build:

```bash
# baseline build
SEEKDB_CUVS_BUILD_ALGO=nn_descent ./build_release/src/observer/seekdb ...

# candidate build (default)
./build_release/src/observer/seekdb ...
```

## Reproduce the build-time comparison

Compile the bridge and seekdb with the official commands, then in `mysql`:

```sql
CREATE TABLE items(id BIGINT PRIMARY KEY, v VECTOR(128));

-- load 250K rows (LOAD DATA, same input as the contest harness)

-- baseline: run the server with SEEKDB_CUVS_BUILD_ALGO=nn_descent
SET @t0 = NOW(6);
CREATE VECTOR INDEX idx_items ON items(v)
  WITH (distance=l2, type=hnsw, lib=cuvs, m=16, ef_construction=200, ef_search=64);
SELECT TIMESTAMPDIFF(MICROSECOND, @t0, NOW(6)) / 1e6 AS build_seconds;

-- candidate: restart without the env var, drop the index, repeat
DROP INDEX idx_items ON items;
SET @t0 = NOW(6);
CREATE VECTOR INDEX idx_items ON items(v)
  WITH (distance=l2, type=hnsw, lib=cuvs, m=16, ef_construction=200, ef_search=64);
SELECT TIMESTAMPDIFF(MICROSECOND, @t0, NOW(6)) / 1e6 AS build_seconds;
```

The contest timer also runs the first fixed query after DDL; add:

```sql
SELECT id FROM items ORDER BY l2_distance(v, '<query>') APPROXIMATE LIMIT 10;
```

## Expected effect

- NN-Descent cost grows with `nn_descent_niter` (100) × `intermediate_graph_degree`
  (256); IVF-PQ removes that loop and uses one IVF-PQ kNN pass.
- Because `graph_degree` and `intermediate_graph_degree` are unchanged, the
  graph used for search has the same out-degree budget as the baseline.
- Query path (`cuvsCagraSearch`, `search_width = 4`, `itopk_size >= 512`) and
  the persisted snapshot format are untouched, so query throughput and recall
  should stay in the same range as V5.

## Verification status

The development host for this submission has an AMD Radeon 780M but no Linux
ROCm/hipVS installation, so the local build was limited to source-level and
API-level checks (the frozen hipVS C header at
`f96a663d0a4441d6f5344bd3ef552b71ae7b370b` defines `IVF_PQ` and the fields
used here).  The official paired CPU/GPU numbers are produced by the contest
cloud runner and are reported by the platform for this commit.

To produce the same report locally, run the two builds above on a ROCm 7.2.4
host and record `build_seconds`, Recall@10/@100 and `nq=4096` QPS for
Top-10/Top-100; the candidate should be compared against the frozen V5 binary
from commit `634888d9b037153fa143d2c913ba4b25503e1d62`.
