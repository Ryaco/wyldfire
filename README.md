# Wyldfire

An opinionated finite-state-machine CLI workflow for solo / small-team indie game developers:
`prototype → gate → production`. Built around the discipline of Benjamin Kean Anderson's
*Production Point* — keep the dev in the right schedule (maker vs. manager) so games
actually get finished.

- [Build spec](docs/BUILD_SPEC.md) — architecture, storage, command reference, gate/wick design, sync
- [UX spec](docs/UX_SPEC.md) — workflow, terminology, command examples

## The Idea in Brief

- **Flames** — prototypes: mechanical proofs of concept, even paper ones
- **Stokes** — playtests; dev-defined metrics, staged smoke filed on commit
- **Smoke** — issues with a lifecycle (staged → open → identified → cleared), forming a searchable fix database
- **Embers** — parked ideas, safe from mid-prototype distraction
- **Fires** — named collections of flames, each running prototype → gate → production
- **Gate** — three-part verdict: Part 1 production point (frozen loop, toys, scope, pinned versions), Part 2 vertical slice, Part 3 content plan
- **Wick** — the content burn-down: bundles of fuel burned one at a time with ETA projections
- **Sync** — offline-first event sourcing with hosted personal sync server

---

## Installation

```bash
# Clone the repository
git clone https://github.com/example/wyldfire.git
cd wyldfire

# Install CLI in editable mode
pip install -e .

# Or with server dependencies
pip install -e ".[server]"
```

Verify installation:
```bash
wyld --help
```

---

## Quickstart Walkthrough

```bash
# 1. Initialize a new project
wyld init wildfire-game && cd wildfire-game

# 2. Spark a prototype flame
wyld flame spark "wildfire" --desc "cut firebreaks, starve the fire"

# 3. Define metrics to ask testers
wyld metric define enjoyment --prompt "How much did you enjoy it? (1-10)" --type number

# 4. Playtest (stoke) the flame
wyld flame stoke wildfire --tester Jo --metric enjoyment=6 --notes "wind chaos"

# 5. Iterate a new version
wyld flame version wildfire --notes "wind every 2 turns"
wyld flame stoke wildfire --tester Jo --metric enjoyment=8 --notes "sings now"

# 6. Park mid-prototype ideas as embers
wyld ember bank "ashen city theme" --note "rain-slick streets vs fire glow"

# 7. Start a fire (composition of flames) and check it out
wyld fire start "game" --flames wildfire --desc "the full game"
wyld fire checkout game
wyld fire stoke game --tester Jo --metric enjoyment=8 --notes "composition works"

# 8. Declare core loop, toys, and attest scope
wyld fire set-loop "spot fire → cut firebreaks → starve it → score"
wyld fire add-toy "cutting firebreaks"
wyld gate attest-scope --note "one mechanic, one game"
wyld ember kindle 1 --note "becomes area 1 theme"

# 9. Pass Gate Part 1 (Production point reached)
wyld gate open

# 10. Gate Part 2: Vertical Slice
wyld wick plan
wyld gate slice set --bundles "area 1"
wyld wick bundle add "area 1" --meta theme="ashen city"
wyld wick fuel add "firefighter sprite" --to "area 1" --type sprite
wyld wick start "firefighter sprite"
wyld wick log "firefighter sprite" --time 3h
wyld wick finish "firefighter sprite"
wyld fire stoke game --tester Jo --metric enjoyment=9 --notes "slice sings"
wyld gate slice-done --note "pitch-ready"

# 11. Gate Part 3: Content Plan
wyld wick bundle add "area 2"
wyld wick fuel define "area 2" --note "bridge"
wyld wick bundle add "area 3" --meta theme="flooded dam"
wyld wick bundle define "area 2" --meta theme="canyon pass"
wyld wick finish "define: area 2"
wyld gate plan-done --note "iteration 1 covers areas 1-3"

# 12. Production & Ship
# ... burn the wick, beta stokes, cut/scope-change as needed ...
wyld fire ship
```

---

## Hosted Sync Server Container (VPS / Raspberry Pi)

The Wyldfire sync server is lightweight, offline-first, and containerized with **multi-arch support** (`linux/amd64` for cloud VPS and `linux/arm64` for Raspberry Pi / ARM boards).

### Using Docker Compose

1. Copy `docker-compose.yml` to your server or Raspberry Pi:
```bash
docker compose up -d
```

By default, this:
- Binds to port `8000`
- Persists data in a Docker volume named `wyld-data` (`/data` in the container)
- Sets `WYLD_SERVER_TOKEN` (override with your secret token via env or `.env` file)

### Building and Running with Docker Directly

```bash
# Build multi-arch or native container
docker build -t wyldfire-server .

# Run with persistent volume and custom token
docker run -d \
  --name wyldfire-server \
  --restart unless-stopped \
  -p 8000:8000 \
  -v wyld-data:/data \
  -e WYLD_SERVER_TOKEN="your-secure-token-here" \
  wyldfire-server
```

### Healthcheck

The container includes a built-in Docker healthcheck:
```bash
docker ps
# Inspect status: (healthy)
curl http://localhost:8000/health
# {"status":"ok","app":"wyldfire-sync-server"}
```

### Pairing with the CLI

From your local development machine:
```bash
# Log in to your hosted server
wyld login --server https://wyld.example.com --token your-secure-token-here

# Link current project
wyld link

# Sync whenever you are online
wyld sync
```

---

## Command Summary

| Command | Description |
|---------|-------------|
| `wyld init [name] [--server <url>]` | Initialize project, register in `~/.wyld/registry.json` |
| `wyld status [--json]` | Dashboard: fires, phase, wick position, issues, embers |
| `wyld flame spark <name>` | Spark a new prototype flame |
| `wyld flame version <name>` | Record an iteration (sparked → burning on v2) |
| `wyld flame stoke <name>` | Playtest flame; commit staged smoke |
| `wyld flame crown <name>` / `douse` | Terminal flame states (chosen or killed) |
| `wyld smoke log <title> --on <ctx>` | Log an open issue (flame/\*, fire/\*, gate, production) |
| `wyld smoke stage <title> --on <ctx>` | Stage mid-playtest issue; committed by next stoke |
| `wyld smoke identify <id>` / `clear` | Diagnose problem / record fix |
| `wyld smoke search --tags ...` | Search cleared fixes locally; auto-widens to all projects |
| `wyld ember bank <title>` | Park production-sized idea during prototype |
| `wyld ember kindle <id>` / `dismiss` | Review embers at gate or production |
| `wyld fire start <name> --flames ...` | Named collection of flames (multi-stream) |
| `wyld fire checkout <name>` | Focus single stream for managerial operations |
| `wyld fire set-loop` / `add-toy` | Declare repeated cycle and playful systems |
| `wyld gate status` / `open` | Part 1 verdict; frozen spec; laps for re-gating |
| `wyld gate slice set` / `slice-done` | Part 2 vertical slice burn & attestation |
| `wyld gate plan-done` | Part 3 content plan attestation |
| `wyld wick bundle add` / `define` | Hierarchical content bundles |
| `wyld wick fuel add` / `define` | Atomic content tasks and deferred design placeholders |
| `wyld wick start` / `finish` / `log` | Advance the content burn and track time |
| `wyld wick next` / `eta` | Traversal position and date projection from logged pace |
| `wyld template new` / `list` | Project-level reusable bundle structures |
| `wyld login` / `sync` / `doctor` | Offline-first hosted sync and health diagnostics |
