"""AURUM — Darwin: Adaptive Strategy Evolution via Natural Selection."""
import json, math, copy, logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import numpy as np

from core.persistence import atomic_write_json

log = logging.getLogger("darwin")

# ── FITNESS CALCULATION ──────────────────────────────────────
def calc_fitness(trades: list[dict], window: int = 30) -> dict:
    """
    Calculate composite fitness score for a set of trades.
    Components (weights):
      - Sortino ratio (40%)
      - Profit Factor (20%)
      - Adjusted Win Rate (20%) = WR * avg_win / avg_loss
      - Stability (20%) = 1 - CV of PnL per window
    Returns dict with total fitness and components.
    """
    if len(trades) < 5:
        return {"fitness": 0.0, "sortino": 0.0, "pf": 0.0, "adj_wr": 0.0, "stability": 0.0, "n_trades": len(trades)}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # Sortino (normalize to ~0-1 range)
    mean_pnl = np.mean(pnls)
    downside = np.sqrt(np.mean([p**2 for p in pnls if p < 0])) if losses else 0.001
    sortino_raw = mean_pnl / downside if downside > 0 else 0.0
    sortino = np.clip(sortino_raw / 3.0, -1.0, 1.0)  # normalize: 3.0 sortino = 1.0

    # Profit Factor
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.001
    pf_raw = gross_profit / gross_loss if gross_loss > 0 else 0.0
    pf = np.clip((pf_raw - 1.0) / 2.0, -1.0, 1.0)  # normalize: PF 3.0 = 1.0

    # Adjusted Win Rate
    wr = len(wins) / len(pnls) if pnls else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 0.001
    adj_wr = wr * (avg_win / avg_loss) if avg_loss > 0 else 0.0
    adj_wr_norm = np.clip((adj_wr - 0.5) * 2.0, -1.0, 1.0)  # 1.0 adj_wr = 1.0 score

    # Stability = 1 - coefficient of variation of rolling PnL
    if len(pnls) >= window:
        chunks = [sum(pnls[i:i+window]) for i in range(0, len(pnls)-window+1, window//2)]
        if len(chunks) >= 2:
            cv = np.std(chunks) / (abs(np.mean(chunks)) + 0.001)
            stability = np.clip(1.0 - cv, -1.0, 1.0)
        else:
            stability = 0.0
    else:
        stability = 0.0

    fitness = 0.40 * sortino + 0.20 * pf + 0.20 * adj_wr_norm + 0.20 * stability

    return {
        "fitness": round(fitness, 4),
        "sortino": round(sortino, 4),
        "pf": round(pf, 4),
        "adj_wr": round(adj_wr_norm, 4),
        "stability": round(stability, 4),
        "n_trades": len(trades),
        "total_pnl": round(sum(pnls), 2),
        "win_rate": round(wr * 100, 1),
    }


class DarwinAllocator:
    """
    Adaptive capital allocator using natural selection.
    Each engine is an 'organism' competing for capital based on live fitness.
    """

    ENGINE_KEYS = ["AZOTH", "HERMES", "NEWTON", "MERCURIO", "THOTH"]

    # Capital allocation tiers
    ALLOC_TOP      = 0.35   # top performer
    ALLOC_ABOVE    = 0.25   # above median
    ALLOC_BELOW    = 0.10   # below median
    ALLOC_KILLED   = 0.05   # kill zone (3 consecutive negative windows)

    EVAL_WINDOW    = 30     # trades per evaluation window
    MUTATION_CYCLE = 100    # trades between mutation attempts
    MUTATION_RANGE = 0.10   # ±10% parameter perturbation
    MUTATION_MIN_IMPROVEMENT = 0.05  # 5% Sharpe improvement to adopt
    MAX_MUTATIONS_PER_CYCLE = 1
    KILL_ZONE_WINDOWS = 3   # consecutive negative windows to pause

    # Mutable parameters per engine (param_name: (min, max))
    MUTABLE_PARAMS = {
        "SCORE_THRESHOLD": (0.45, 0.70),
        "STOP_ATR_M":      (1.0, 3.0),
        "TARGET_RR":       (1.2, 4.0),
        "RSI_BULL_MIN":    (35, 50),
        "RSI_BULL_MAX":    (60, 75),
        "RSI_BEAR_MIN":    (25, 40),
        "RSI_BEAR_MAX":    (50, 65),
    }

    def __init__(self, engines: list[str] | None = None, data_dir: str = "data/aqr"):
        self.engines = engines or self.ENGINE_KEYS
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # State per engine
        self.population = {}   # engine -> {dna: {param: value}, fitness_history: [...], ...}
        self.allocations = {}  # engine -> float (capital fraction)
        self.generation = 0
        self.evolution_log = []
        self.mutations_log = []

        self._load_state()

    def _load_state(self):
        """Load or initialize population state."""
        pop_path = self.data_dir / "population.json"
        if pop_path.exists():
            try:
                with open(pop_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.population = state.get("population", {})
                self.allocations = state.get("allocations", {})
                self.generation = state.get("generation", 0)
                return
            except Exception as e:
                log.warning(f"Failed to load population: {e}")

        # Initialize fresh population
        from config.params import (SCORE_THRESHOLD, STOP_ATR_M, TARGET_RR,
                                    RSI_BULL_MIN, RSI_BULL_MAX, RSI_BEAR_MIN, RSI_BEAR_MAX)
        default_dna = {
            "SCORE_THRESHOLD": SCORE_THRESHOLD,
            "STOP_ATR_M": STOP_ATR_M,
            "TARGET_RR": TARGET_RR,
            "RSI_BULL_MIN": RSI_BULL_MIN,
            "RSI_BULL_MAX": RSI_BULL_MAX,
            "RSI_BEAR_MIN": RSI_BEAR_MIN,
            "RSI_BEAR_MAX": RSI_BEAR_MAX,
        }

        equal_alloc = round(1.0 / len(self.engines), 4)
        for eng in self.engines:
            self.population[eng] = {
                "dna": copy.deepcopy(default_dna),
                "fitness_history": [],
                "current_fitness": 0.0,
                "negative_streak": 0,
                "paused": False,
                "trades_since_mutation": 0,
                "mutations_applied": 0,
                "dna_backup": None,
            }
            self.allocations[eng] = equal_alloc

    def evaluate(self, engine_trades: dict[str, list[dict]]) -> dict:
        """
        Evaluate all engines and update allocations.
        engine_trades: {engine_name: [trade_dicts]} — recent trades per engine
        Returns: current allocations dict
        """
        self.generation += 1
        gen_log = {
            "generation": self.generation,
            "timestamp": datetime.now().isoformat(),
            "fitness": {},
            "allocations": {},
            "events": [],
        }

        # 1. Calculate fitness for each engine
        fitness_scores = {}
        for eng in self.engines:
            trades = engine_trades.get(eng, [])
            fitness = calc_fitness(trades, self.EVAL_WINDOW)
            fitness_scores[eng] = fitness

            pop = self.population[eng]
            pop["current_fitness"] = fitness["fitness"]
            pop["fitness_history"].append(fitness)

            # Track negative streaks
            if fitness["fitness"] < 0:
                pop["negative_streak"] += 1
            else:
                pop["negative_streak"] = 0

            # Kill zone check
            if pop["negative_streak"] >= self.KILL_ZONE_WINDOWS:
                if not pop["paused"]:
                    pop["paused"] = True
                    gen_log["events"].append(f"{eng} PAUSED: {self.KILL_ZONE_WINDOWS} consecutive negative windows")
            elif pop["paused"] and fitness["fitness"] > 0:
                pop["paused"] = False
                gen_log["events"].append(f"{eng} RESUMED: positive fitness recovered")

            # Track trades for mutation cycle
            pop["trades_since_mutation"] += len(trades)

            gen_log["fitness"][eng] = fitness

        # 2. Selection: allocate capital based on fitness ranking
        self._allocate(fitness_scores)
        gen_log["allocations"] = copy.deepcopy(self.allocations)

        # 3. Mutation: check if any engine is due for parameter evolution
        for eng in self.engines:
            pop = self.population[eng]
            if pop["trades_since_mutation"] >= self.MUTATION_CYCLE:
                mutation = self._maybe_mutate(eng)
                if mutation:
                    gen_log["events"].append(f"{eng} MUTATED: {mutation}")
                pop["trades_since_mutation"] = 0

        self.evolution_log.append(gen_log)
        self._save_state()

        return copy.deepcopy(self.allocations)

    def _allocate(self, fitness_scores: dict):
        """Allocate capital based on fitness ranking."""
        # Sort engines by fitness (descending)
        ranked = sorted(fitness_scores.items(), key=lambda x: x[1]["fitness"], reverse=True)
        n = len(ranked)
        if n == 0:
            return

        median_idx = n // 2
        top_eng = ranked[0][0]

        new_alloc = {}
        for i, (eng, fit) in enumerate(ranked):
            pop = self.population[eng]
            if pop["paused"]:
                new_alloc[eng] = self.ALLOC_KILLED
            elif i == 0:
                new_alloc[eng] = self.ALLOC_TOP
            elif i < median_idx:
                new_alloc[eng] = self.ALLOC_ABOVE
            else:
                new_alloc[eng] = self.ALLOC_BELOW

        # Normalize to sum=1.0
        total = sum(new_alloc.values())
        if total > 0:
            for eng in new_alloc:
                new_alloc[eng] = round(new_alloc[eng] / total, 4)

        self.allocations = new_alloc

    def _maybe_mutate(self, engine: str) -> str | None:
        """
        Try a parameter mutation for the engine.
        Perturb ±10%, test if improvement > 5%.
        Returns description of mutation if applied, None otherwise.
        """
        pop = self.population[engine]
        dna = pop["dna"]

        # Pick a random parameter to mutate
        param = list(self.MUTABLE_PARAMS.keys())[self.generation % len(self.MUTABLE_PARAMS)]
        lo, hi = self.MUTABLE_PARAMS[param]
        current = dna[param]

        # Perturbation: ±MUTATION_RANGE
        delta = current * self.MUTATION_RANGE
        direction = 1 if (self.generation // len(self.MUTABLE_PARAMS)) % 2 == 0 else -1
        new_val = current + direction * delta

        # Clamp to bounds
        if isinstance(lo, int):
            new_val = int(np.clip(round(new_val), lo, hi))
        else:
            new_val = round(float(np.clip(new_val, lo, hi)), 4)

        if new_val == current:
            return None

        # Store backup and apply mutation
        pop["dna_backup"] = copy.deepcopy(dna)
        dna[param] = new_val
        pop["mutations_applied"] += 1

        desc = f"{param}: {current} -> {new_val}"
        self.mutations_log.append({
            "generation": self.generation,
            "engine": engine,
            "param": param,
            "old": current,
            "new": new_val,
            "timestamp": datetime.now().isoformat(),
        })

        log.info(f"  MUTATION [{engine}] {desc}")
        return desc

    def revert_mutation(self, engine: str):
        """Revert last mutation if it didn't improve performance."""
        pop = self.population[engine]
        if pop["dna_backup"]:
            pop["dna"] = pop["dna_backup"]
            pop["dna_backup"] = None
            log.info(f"  REVERTED mutation for {engine}")

    def crossover(self, eng_a: str, eng_b: str) -> dict:
        """
        Create hybrid DNA from two well-performing engines.
        Takes average of each parameter.
        """
        dna_a = self.population[eng_a]["dna"]
        dna_b = self.population[eng_b]["dna"]
        hybrid = {}
        for param in self.MUTABLE_PARAMS:
            lo, hi = self.MUTABLE_PARAMS[param]
            val = (dna_a[param] + dna_b[param]) / 2
            if isinstance(lo, int):
                hybrid[param] = int(np.clip(round(val), lo, hi))
            else:
                hybrid[param] = round(float(np.clip(val, lo, hi)), 4)
        return hybrid

    def get_engine_capital(self, engine: str, total_capital: float) -> float:
        """Get allocated capital for an engine."""
        return total_capital * self.allocations.get(engine, 0.0)

    def dashboard(self) -> str:
        """Generate text dashboard showing current state."""
        lines = []
        lines.append("=" * 60)
        lines.append("  DARWIN — Adaptive Strategy Evolution")
        lines.append(f"  Generation: {self.generation}")
        lines.append("=" * 60)

        # Ranking by fitness
        ranked = sorted(self.population.items(),
                       key=lambda x: x[1]["current_fitness"], reverse=True)

        lines.append(f"\n  {'ENGINE':<12} {'FITNESS':>8} {'ALLOC':>8} {'TRADES':>8} {'STATUS':<10}")
        lines.append("  " + "-" * 52)

        for eng, pop in ranked:
            status = "PAUSED" if pop["paused"] else "ACTIVE"
            alloc = self.allocations.get(eng, 0.0) * 100
            n_trades = sum(f.get("n_trades", 0) for f in pop["fitness_history"][-3:])
            lines.append(f"  {eng:<12} {pop['current_fitness']:>8.4f} {alloc:>7.1f}% {n_trades:>8} {status:<10}")

        # Recent mutations
        recent_mut = self.mutations_log[-5:] if self.mutations_log else []
        if recent_mut:
            lines.append(f"\n  RECENT MUTATIONS:")
            for m in recent_mut:
                lines.append(f"    Gen {m['generation']}: [{m['engine']}] {m['param']} {m['old']} -> {m['new']}")

        # Paused engines
        paused = [e for e, p in self.population.items() if p["paused"]]
        if paused:
            lines.append(f"\n  PAUSED: {', '.join(paused)}")

        lines.append("")
        return "\n".join(lines)

    def _save_state(self):
        """Persist population and logs. Atomic so a crash mid-write never
        leaves truncated state — the generation either fully lands or
        stays as whatever existed before."""
        state = {
            "generation": self.generation,
            "population": self.population,
            "allocations": self.allocations,
            "saved_at": datetime.now().isoformat(),
        }
        atomic_write_json(self.data_dir / "population.json", state)
        atomic_write_json(self.data_dir / "evolution_log.json", self.evolution_log[-100:])
        atomic_write_json(self.data_dir / "mutations.json", self.mutations_log[-200:])
