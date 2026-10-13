# Wyldfire

An opinionated CLI workflow for solo/small-team indie game development:
prototype → gate → production. Built around the discipline of Benjamin Kean Anderson's
*Production Point* — keep the dev in the right schedule (maker vs. manager) so games
actually get finished.

**Status:** design phase. The specs below are the complete v1 design; implementation
hasn't started yet.

- [Build spec](docs/BUILD_SPEC.md) — architecture, storage, command reference, gate/wick design, sync
- [UX spec](docs/UX_SPEC.md) — workflow, terminology, command examples

```bash
pip install wyldfire  # not yet published
wyld flame spark "my mechanic" --desc "..."
```

## The idea in brief

- **Flames** — prototypes: mechanical proofs of concept, even paper ones
- **Stokes** — playtests; dev-defined metrics, staged smoke filed on commit
- **Smoke** — issues with a lifecycle, forming a searchable fix database
- **Embers** — parked ideas, safe from mid-prototype distraction
- **Fires** — named collections of flames, each running prototype → gate → production
- **Gate** — the three-part verdict: production point, vertical slice, content plan
- **Wick** — the content burn-down: bundles of fuel, one at a time
