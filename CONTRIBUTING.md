# Contributing to Provenance

Thanks for your interest. This project is in early development; the design is locked
in [`docs/plans/provenance-requirements.md`](docs/plans/provenance-requirements.md)
and implementation follows the phased plan (P0 → P6) there.

## Ground rules that shape every change

These are invariants from the spec — PRs that violate them won't be merged:

1. **Database-per-service.** No two services share a datastore; cross-service data is
   joined by id over the wire (R52).
2. **Permissive licenses only.** Every datastore, queue, and OCR/model dependency must be
   Apache-2.0 / MIT / BSD / PostgreSQL / MPL. No SSPL, BSL, RSAL, or GPL/AGPL — the CI
   license-audit enforces this (R59).
3. **Vector is the floor, graph is the lift.** Retrieval never routes to graph-only;
   graph expansion is additive (R25).
4. **Strict groundedness.** An answer with any ungrounded claim is never released (R31/R32).
5. **Provenance is mandatory.** New ingestion steps must record their provenance and
   propagate the trace context (R56).
6. **Contracts are generated, not hand-copied.** Inter-service types come from the shared
   contracts package — gRPC internally, REST/OpenAPI at the Gateway edge (R57, N9).

## Workflow

1. **Find or open an issue** describing the change. Reference the requirement IDs it touches.
2. **Branch** from `main`: `feat/<short-name>`, `fix/<short-name>`, or `docs/<short-name>`.
3. **Develop** inside the owning service; keep the change within one service where possible.
4. **Test** — every requirement has an acceptance criterion; add/adjust the test that proves it.
   Run the relevant service tests and the eval smoke set before opening a PR.
5. **Open a PR** with: what changed, which requirement IDs, tests added/updated, and any
   contract or schema changes called out explicitly.

## Development setup _(available from P0)_

```bash
cp .env.example .env
docker compose up        # 8 services + NATS + Postgres
# per-service dev instructions land with each service in P0–P5
```

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `refactor:`, `test:`, `chore:`. Reference requirement IDs where relevant
(e.g. `feat(parse): table-structure extraction (R62)`).

## Code style

Python: `ruff` + `mypy`. TypeScript: `eslint` + `tsc`. Config lands with the scaffold;
CI runs lint, type-check, tests, and the license-audit on every PR.
