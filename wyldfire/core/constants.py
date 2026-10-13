"""Constants and enums for Wyldfire."""

# Fire phases
PHASE_PROTOTYPE = "prototype"
PHASE_GATE_PART1 = "gate:part1"
PHASE_GATE_PART2 = "gate:part2"
PHASE_GATE_PART3 = "gate:part3"
PHASE_PRODUCTION = "production"
PHASE_SHIPPED = "shipped"

FIRE_PHASES = (
    PHASE_PROTOTYPE,
    PHASE_GATE_PART1,
    PHASE_GATE_PART2,
    PHASE_GATE_PART3,
    PHASE_PRODUCTION,
    PHASE_SHIPPED,
)

# Flame states
FLAME_SPARKED = "sparked"
FLAME_BURNING = "burning"
FLAME_TESTED = "tested"
FLAME_CROWNED = "crowned"
FLAME_DOUSED = "doused"

FLAME_STATES = (
    FLAME_SPARKED,
    FLAME_BURNING,
    FLAME_TESTED,
    FLAME_CROWNED,
    FLAME_DOUSED,
)

# Smoke statuses
SMOKE_STAGED = "staged"
SMOKE_OPEN = "open"
SMOKE_IDENTIFIED = "identified"
SMOKE_CLEARED = "cleared"

SMOKE_STATUSES = (
    SMOKE_STAGED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    SMOKE_CLEARED,
)

# Smoke severity
SEVERITY_NIT = 1
SEVERITY_PROBLEM = 2
SEVERITY_CRITICAL = 3

SEVERITY_NAMES = {
    1: "nit/polish",
    2: "problem",
    3: "critical",
}

# Fuel states
FUEL_QUEUED = "queued"
FUEL_CREATING = "creating"
FUEL_FINISHED = "finished"

FUEL_KINDS = ("task", "define")

# Ember states and kinds
EMBER_BANKED = "banked"
EMBER_KINDLED = "kindled"
EMBER_DISMISSED = "dismissed"

EMBER_KINDS = ("content", "mechanic")

# Gate defaults
DEFAULT_MIN_STOKES = 3
DEFAULT_BLOCKED_SEVERITY = 2
