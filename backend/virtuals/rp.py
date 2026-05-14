
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# -----------------------------
# Core utilities
# -----------------------------

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sigmoid(x: float) -> float:
    # Safe sigmoid for moderate x values used in this model.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def normalize_three(a: float, b: float, c: float) -> Tuple[float, float, float]:
    total = a + b + c
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return a / total, b / total, c / total


def poisson_sample(lam: float, rng: random.Random) -> int:
    """Knuth sampler; stable for small/medium lambdas."""
    lam = max(0.01, lam)
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def odds_to_probs(home_odds: float, draw_odds: float, away_odds: float) -> Dict[str, float]:
    inv_h = 1.0 / max(home_odds, 1e-9)
    inv_d = 1.0 / max(draw_odds, 1e-9)
    inv_a = 1.0 / max(away_odds, 1e-9)
    h, d, a = normalize_three(inv_h, inv_d, inv_a)
    return {"home": h, "draw": d, "away": a}


# -----------------------------
# Data models
# -----------------------------

@dataclass
class LeagueParams:
    # Rating model
    home_adv: float = 6.0
    scale: float = 10.0

    # Draw model
    base_draw: float = 0.26
    draw_slope: float = 0.18
    close_band: float = 0.90
    draw_min: float = 0.14
    draw_max: float = 0.50

    # Upset / trap model
    base_upset_rate: float = 0.18
    round_shock_low: float = 0.00
    round_shock_high: float = 0.20

    # Score model
    goal_cap: int = 6
    base_home_goals: float = 1.15
    base_away_goals: float = 1.05

    # V13/V14 dynamics thresholds
    chaos_draw_boost: float = 0.10
    fixed_draw_boost: float = 0.20
    trap_gap_low: float = 5.0
    trap_gap_high: float = 12.0
    safe_gap: float = 12.0

    # ASE (Away Sharpness Engine)
    ase_away_odds_low: float = 2.80
    ase_away_odds_high: float = 4.20
    ase_home_odds_max: float = 2.40
    ase_draw_min: float = 0.28

    # Score expansion / collapse controls
    dvf_high: float = 0.68
    caf_high: float = 0.68


@dataclass
class MatchContext:
    """Optional information that helps the model adapt to round-level behavior."""
    recent_results: List[Tuple[int, int]] = field(default_factory=list)
    round_number: Optional[int] = None
    derby_factor: float = 0.0
    home_form: float = 0.0
    away_form: float = 0.0


@dataclass
class Prediction:
    home_prob: float
    draw_prob: float
    away_prob: float
    predicted_result: str
    most_likely_score: str
    scoreline_distribution: List[Tuple[str, float]]
    metrics: Dict[str, float]
    flags: List[str]


# -----------------------------
# Main engine
# -----------------------------

class VirtualLeagueMasterEngine:
    """Merged engine that combines the ideas from V6 -> V14."""

    def __init__(self, params: Optional[LeagueParams] = None, seed: Optional[int] = None):
        self.p = params or LeagueParams()
        self.rng = random.Random(seed)

        # Round-level adaptation state
        self.round_pressure = 0.0  # positive => more shocks, negative => more stability
        self.season_chaos = 4.0

    # -----------------------------
    # Round/season adaptation
    # -----------------------------

    def update_round_pressure(self, recent_results: List[Tuple[int, int]]) -> None:
        """Update a lightweight volatility signal from recent score patterns."""
        if not recent_results:
            self.round_pressure = 0.0
            return

        draws = sum(1 for h, a in recent_results if h == a)
        blowouts = sum(1 for h, a in recent_results if abs(h - a) >= 3)
        away_wins = sum(1 for h, a in recent_results if a > h)
        home_wins = sum(1 for h, a in recent_results if h > a)

        pressure = 0.0
        pressure += 0.08 * max(0, draws - 2)
        pressure += 0.10 * max(0, blowouts - 1)
        pressure += 0.04 * max(0, away_wins - home_wins)
        pressure -= 0.05 * max(0, 2 - draws)

        self.round_pressure = clamp(pressure, -0.20, 0.25)

    def update_season_chaos(self, recent_results: List[Tuple[int, int]]) -> None:
        draws = sum(1 for h, a in recent_results if h == a)
        shocks = sum(1 for h, a in recent_results if abs(h - a) >= 2)
        big_losses = sum(1 for h, a in recent_results if abs(h - a) >= 3)
        self.season_chaos = draws + shocks + 1.5 * big_losses

    def league_state(self) -> str:
        if self.season_chaos >= 6:
            return "CHAOTIC"
        if self.season_chaos >= 3:
            return "UNSTABLE"
        return "STABLE"

    # -----------------------------
    # V8/V9/V10 feature layers
    # -----------------------------

    def _strength_gap(self, home_rating: float, away_rating: float, home_form: float = 0.0, away_form: float = 0.0) -> float:
        return (home_rating + self.p.home_adv + home_form * 1.5) - (away_rating + away_form * 1.2)

    def _market_pressure(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        # Higher = more unstable / less efficient market.
        return (1.0 / home_odds) + (1.0 / draw_odds) + (1.0 / away_odds)

    def _draw_gravity(self, draw_odds: float) -> float:
        return 1.0 / max(draw_odds, 1e-9)

    def _favorite_fragility(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        fav = max(probs["home"], probs["draw"], probs["away"])
        runner_up = sorted([probs["home"], probs["draw"], probs["away"]], reverse=True)[1]
        return fav - runner_up

    def _trap_index(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        fav = max(probs["home"], probs["draw"], probs["away"])
        runner_up = sorted([probs["home"], probs["draw"], probs["away"]], reverse=True)[1]
        frag = max(0.0, 1.0 - (fav - runner_up))

        mp = self._market_pressure(home_odds, draw_odds, away_odds)
        dg = self._draw_gravity(draw_odds)
        # Scale to 0..100-ish
        trap = (
            45.0 * frag
            + 20.0 * clamp(mp / 1.2, 0.0, 1.0)
            + 15.0 * clamp(dg / 0.35, 0.0, 1.0)
            + 20.0 * clamp(self.round_pressure / 0.25, 0.0, 1.0)
        )
        return clamp(trap, 0.0, 100.0)

    def _draw_pressure(self, home_odds: float, draw_odds: float, away_odds: float, gap: float) -> float:
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        closeness = max(0.0, 1.0 - min(abs(gap) / 10.0, 1.0))
        return clamp((probs["draw"] * 100.0) * 0.7 + closeness * 30.0 + self.round_pressure * 40.0, 0.0, 100.0)

    def _stability_score(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        gap12 = abs(probs["home"] - probs["away"])
        gap13 = abs(max(probs.values()) - sorted(probs.values(), reverse=True)[1])
        return clamp((gap12 * 100.0 * 0.6) + (gap13 * 100.0 * 0.4), 0.0, 100.0)

    # -----------------------------
    # V13/V14 match dynamics
    # -----------------------------

    def _dvf(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        """Dual Volatility Factor.

        High when both teams can score and the odds suggest an open game.
        """
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        closeness = 1.0 - abs(probs["home"] - probs["away"])
        open_draw = probs["draw"]
        market_noise = self._market_pressure(home_odds, draw_odds, away_odds)
        dvf = 100.0 * (0.45 * closeness + 0.35 * open_draw + 0.20 * clamp(market_noise / 1.15, 0.0, 1.0))
        return clamp(dvf, 0.0, 100.0)

    def _caf(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        """Collapse Amplification Factor.

        High when one side is likely to break and the other side can run away with it.
        """
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        fav = max(probs["home"], probs["draw"], probs["away"])
        runner_up = sorted([probs["home"], probs["draw"], probs["away"]], reverse=True)[1]
        spread = fav - runner_up
        away_sharp = self._ase(home_odds, draw_odds, away_odds) / 100.0
        caf = 100.0 * (0.55 * clamp((spread - 0.05) / 0.35, 0.0, 1.0) + 0.45 * away_sharp)
        return clamp(caf, 0.0, 100.0)

    def _ase(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        """Away Sharpness Engine.

        Detects when the away side is underestimated by the market.
        """
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        away_prob = probs["away"]
        home_prob = probs["home"]
        draw_prob = probs["draw"]

        cond_odds = 1.0 if self.p.ase_away_odds_low <= away_odds <= self.p.ase_away_odds_high else 0.0
        cond_home = 1.0 if home_odds < self.p.ase_home_odds_max else 0.0
        cond_draw = 1.0 if draw_prob >= self.p.ase_draw_min else 0.0

        # Higher away probability relative to the market can also trigger ASE.
        base = (
            0.42 * cond_odds
            + 0.25 * cond_home
            + 0.15 * cond_draw
            + 0.18 * clamp(away_prob - home_prob + 0.08, 0.0, 0.35) / 0.35
        )
        return clamp(base * 100.0, 0.0, 100.0)

    def _udi(self, home_odds: float, draw_odds: float, away_odds: float) -> float:
        """Upset Drift Index.

        Detects matches that look safe but have hidden upset potential.
        """
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        fav = max(probs["home"], probs["draw"], probs["away"])
        runner_up = sorted([probs["home"], probs["draw"], probs["away"]], reverse=True)[1]
        stability_gap = fav - runner_up
        ase = self._ase(home_odds, draw_odds, away_odds) / 100.0
        draw = probs["draw"]
        udi = 100.0 * (
            0.40 * clamp(1.0 - stability_gap / 0.25, 0.0, 1.0)
            + 0.35 * ase
            + 0.25 * clamp(draw / 0.35, 0.0, 1.0)
        )
        return clamp(udi, 0.0, 100.0)

    # -----------------------------
    # Script classification
    # -----------------------------

    def _script_type(
        self,
        home_rating: float,
        away_rating: float,
        home_odds: float,
        draw_odds: float,
        away_odds: float,
        context: Optional[MatchContext] = None,
    ) -> str:
        context = context or MatchContext()
        gap = self._strength_gap(home_rating, away_rating, context.home_form, context.away_form)
        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        trap = self._trap_index(home_odds, draw_odds, away_odds)
        draw_pressure = self._draw_pressure(home_odds, draw_odds, away_odds, gap)
        dvf = self._dvf(home_odds, draw_odds, away_odds)
        caf = self._caf(home_odds, draw_odds, away_odds)
        ase = self._ase(home_odds, draw_odds, away_odds)
        udi = self._udi(home_odds, draw_odds, away_odds)

        # V7/V8/V9 style behavior zones
        if draw_pressure >= 60 and abs(gap) <= 4:
            return "FIXED_DRAW"
        if caf >= 68:
            return "COLLAPSE"
        if dvf >= 68 and trap >= 55:
            return "CHAOS"
        if ase >= 60 or udi >= 60:
            return "UPSET"
        if trap >= 65:
            return "TRAP"
        if gap >= self.p.safe_gap and probs["home"] >= probs["away"]:
            return "SAFE_HOME"
        if gap <= -4 and probs["away"] >= probs["home"]:
            return "SAFE_AWAY"
        return "BALANCED"

    # -----------------------------
    # Probability engine
    # -----------------------------

    def _base_1x2_probs(
        self,
        home_rating: float,
        away_rating: float,
        home_odds: float,
        draw_odds: float,
        away_odds: float,
        context: Optional[MatchContext] = None,
    ) -> Tuple[float, float, float, float]:
        context = context or MatchContext()
        gap = self._strength_gap(home_rating, away_rating, context.home_form, context.away_form)
        state = self.league_state()

        factor = {"STABLE": 10.0, "UNSTABLE": 9.2, "CHAOTIC": 8.5}[state]
        x = gap / factor

        probs = odds_to_probs(home_odds, draw_odds, away_odds)
        trap = self._trap_index(home_odds, draw_odds, away_odds) / 100.0
        draw_pressure = self._draw_pressure(home_odds, draw_odds, away_odds, gap) / 100.0
        ase = self._ase(home_odds, draw_odds, away_odds) / 100.0
        udi = self._udi(home_odds, draw_odds, away_odds) / 100.0
        dvf = self._dvf(home_odds, draw_odds, away_odds) / 100.0
        caf = self._caf(home_odds, draw_odds, away_odds) / 100.0
        stability = self._stability_score(home_odds, draw_odds, away_odds) / 100.0

        # Base home/away weights from gap + forms
        home_raw = sigmoid(x + context.home_form * 0.35 - context.away_form * 0.20)
        away_raw = sigmoid(-x + context.away_form * 0.30 - context.home_form * 0.15)

        # Draw starts from market draw + closeness + pressure
        closeness = max(0.0, 1.0 - min(abs(gap) / 10.0, 1.0))
        draw_raw = self.p.base_draw + closeness * self.p.draw_slope + self.round_pressure

        # Round and market adjustment layers
        if state == "CHAOTIC":
            draw_raw += self.p.chaos_draw_boost
        elif state == "UNSTABLE":
            draw_raw += 0.05

        # Trap / collapse / upset adjustments
        if caf >= self.p.caf_high:
            # Collapse tends to reduce draw and create decisive scorelines.
            draw_raw -= 0.04
            if probs["home"] >= probs["away"]:
                home_raw += 0.10
            else:
                away_raw += 0.10

        if dvf >= self.p.dvf_high:
            draw_raw += 0.03
            home_raw += 0.03
            away_raw += 0.03

        if ase >= 0.60 or udi >= 0.60:
            # Away-sharp matches increase away probability and suppress draw slightly.
            away_raw += 0.10 + 0.08 * ase
            draw_raw -= 0.03
            home_raw -= 0.02

        if trap >= 0.65:
            # High trap often means the favorite can flip or collapse.
            if probs["home"] >= probs["away"]:
                home_raw -= 0.06
                away_raw += 0.08
            else:
                away_raw -= 0.06
                home_raw += 0.08

        # Draw suppression / boost.
        if draw_pressure >= 0.60:
            draw_raw += 0.08
        elif draw_pressure <= 0.30:
            draw_raw -= 0.03

        # Safety bounds
        draw_raw = clamp(draw_raw, self.p.draw_min, self.p.draw_max)
        home_raw = clamp(home_raw, 0.02, 0.95)
        away_raw = clamp(away_raw, 0.02, 0.95)

        # Market rough sanity: bring favorite closer to market if gap isn't extreme
        if gap > 0 and probs["home"] > probs["away"]:
            home_raw += 0.02 * clamp(stability, 0.0, 1.0)
        if gap < 0 and probs["away"] > probs["home"]:
            away_raw += 0.02 * clamp(stability, 0.0, 1.0)

        home_prob, draw_prob, away_prob = normalize_three(home_raw, draw_raw, away_raw)
        return home_prob, draw_prob, away_prob, gap

    # -----------------------------
    # Score engine
    # -----------------------------

    def _score_lambdas(
        self,
        home_rating: float,
        away_rating: float,
        home_odds: float,
        draw_odds: float,
        away_odds: float,
        context: Optional[MatchContext] = None,
    ) -> Tuple[float, float, Dict[str, float]]:
        context = context or MatchContext()
        gap = self._strength_gap(home_rating, away_rating, context.home_form, context.away_form)
        dvf = self._dvf(home_odds, draw_odds, away_odds) / 100.0
        caf = self._caf(home_odds, draw_odds, away_odds) / 100.0
        ase = self._ase(home_odds, draw_odds, away_odds) / 100.0
        draw_pressure = self._draw_pressure(home_odds, draw_odds, away_odds, gap) / 100.0
        state = self.league_state()

        lam_home = self.p.base_home_goals + gap / 18.0 + context.home_form * 0.18 - context.away_form * 0.05
        lam_away = self.p.base_away_goals - gap / 20.0 + context.away_form * 0.14 - context.home_form * 0.04

        # Round pressure and state.
        if state == "CHAOTIC":
            lam_home += 0.10
            lam_away += 0.10
        elif state == "UNSTABLE":
            lam_home += 0.05
            lam_away += 0.05
        else:
            lam_home -= 0.02
            lam_away -= 0.02

        # Score expansion / collapse dynamics
        if dvf >= self.p.dvf_high:
            lam_home += 0.25
            lam_away += 0.25
        if caf >= self.p.caf_high:
            # One side collapses more than the other.
            if gap >= 0:
                lam_home += 0.20
                lam_away -= 0.10
            else:
                lam_away += 0.20
                lam_home -= 0.10
        if ase >= 0.60:
            lam_away += 0.20
            lam_home -= 0.05
        if draw_pressure >= 0.60:
            lam_home -= 0.08
            lam_away -= 0.08
        elif draw_pressure <= 0.30:
            lam_home += 0.08
            lam_away += 0.02

        lam_home = clamp(lam_home, 0.20, 3.40)
        lam_away = clamp(lam_away, 0.15, 3.20)
        return lam_home, lam_away, {"gap": gap, "dvf": dvf, "caf": caf, "ase": ase, "draw_pressure": draw_pressure}

    def _simulate_scores(
        self,
        home_prob: float,
        draw_prob: float,
        away_prob: float,
        home_rating: float,
        away_rating: float,
        home_odds: float,
        draw_odds: float,
        away_odds: float,
        context: Optional[MatchContext] = None,
    ) -> Tuple[int, int, List[Tuple[str, float]]]:
        context = context or MatchContext()
        lam_home, lam_away, features = self._score_lambdas(
            home_rating, away_rating, home_odds, draw_odds, away_odds, context
        )

        # Dynamic score line category based on V13 logic.
        dvf = features["dvf"]
        caf = features["caf"]
        ase = features["ase"]
        draw_pressure = features["draw_pressure"]

        # Generate primary sample.
        hg = poisson_sample(lam_home, self.rng)
        ag = poisson_sample(lam_away, self.rng)

        # Clamp to realistic range.
        hg = clamp(hg, 0, self.p.goal_cap)
        ag = clamp(ag, 0, self.p.goal_cap)

        # V13/V14 style correction passes.
        if caf >= self.p.caf_high:
            # Collapse match tends to be more decisive.
            if home_prob >= away_prob:
                if hg < 2:
                    hg += 1
                if ag > 1:
                    ag -= 1
            else:
                if ag < 2:
                    ag += 1
                if hg > 1:
                    hg -= 1

        if dvf >= self.p.dvf_high:
            # Both teams scoring is more likely.
            if hg == 0:
                hg += 1
            if ag == 0:
                ag += 1

        if ase >= 0.60:
            # Away sharpness can force away goals and away wins.
            if ag < 1:
                ag += 1
            if home_prob > away_prob and hg <= ag:
                hg = max(0, hg - 1)

        if draw_pressure >= 0.60 and abs(hg - ag) > 1:
            # Draw-heavy games should naturally close up.
            if hg > ag:
                hg -= 1
            else:
                ag -= 1

        # Re-clamp after corrections.
        hg = int(clamp(hg, 0, self.p.goal_cap))
        ag = int(clamp(ag, 0, self.p.goal_cap))

        # Scoreline distribution (heuristic probabilities)
        score_dist = self._score_distribution(home_prob, draw_prob, away_prob, hg, ag, dvf, caf, ase)
        return hg, ag, score_dist

    def _score_distribution(
        self,
        home_prob: float,
        draw_prob: float,
        away_prob: float,
        hg: int,
        ag: int,
        dvf: float,
        caf: float,
        ase: float,
    ) -> List[Tuple[str, float]]:
        """Return a ranked list of plausible scorelines."""
        # Candidate scores depend on the predicted type.
        candidates: List[Tuple[str, float]] = []
        goal_bias = 1.0 + 0.6 * dvf + 0.4 * caf

        def add(score: str, p: float) -> None:
            candidates.append((score, max(0.0, p)))

        # Winner-based core scores.
        if home_prob >= away_prob:
            add("1-0", 0.12 * goal_bias)
            add("2-0", 0.14 * goal_bias)
            add("2-1", 0.18 * goal_bias)
            add("3-0", 0.09 * goal_bias)
            add("3-1", 0.10 * goal_bias)
            add("1-1", 0.12 * (1.2 - dvf * 0.4))
            add("2-2", 0.06 * dvf)
            if ase >= 0.60:
                add("0-1", 0.08 * ase)
                add("0-2", 0.06 * ase)
                add("1-2", 0.10 * ase)
        else:
            add("0-1", 0.12 * goal_bias)
            add("0-2", 0.14 * goal_bias)
            add("1-2", 0.18 * goal_bias)
            add("0-3", 0.09 * goal_bias)
            add("1-3", 0.10 * goal_bias)
            add("1-1", 0.12 * (1.2 - dvf * 0.4))
            add("2-2", 0.06 * dvf)
            if ase >= 0.60:
                add("2-0", 0.08 * ase)
                add("2-1", 0.10 * ase)
                add("3-1", 0.06 * ase)

        # Chaos / blowout enhancement.
        if caf >= 0.68:
            add(f"{max(hg, 3)}-{ag}", 0.11 * caf)
            add(f"{hg}-{max(ag, 3)}", 0.08 * caf)
        if dvf >= 0.68:
            add("3-2", 0.10 * dvf)
            add("2-3", 0.08 * dvf)
            add("2-2", 0.10 * dvf)
        if draw_prob >= 0.35:
            add("0-0", 0.07 * draw_prob)
            add("1-1", 0.13 * draw_prob)
            add("2-2", 0.08 * draw_prob)

        # Normalize and sort.
        total = sum(p for _, p in candidates)
        if total <= 0:
            return [(f"{hg}-{ag}", 1.0)]

        normalized = [(s, p / total) for s, p in candidates]
        normalized.sort(key=lambda x: x[1], reverse=True)
        # Keep top 6 to stay readable.
        return normalized[:6]

    # -----------------------------
    # Public API
    # -----------------------------

    def predict_match(
        self,
        home_rating: float,
        away_rating: float,
        home_odds: float,
        draw_odds: float,
        away_odds: float,
        context: Optional[MatchContext] = None,
    ) -> Prediction:
        context = context or MatchContext()

        # Update round state if recent results are provided.
        if context.recent_results:
            self.update_round_pressure(context.recent_results)
            self.update_season_chaos(context.recent_results)

        home_prob, draw_prob, away_prob, gap = self._base_1x2_probs(
            home_rating, away_rating, home_odds, draw_odds, away_odds, context
        )

        trap = self._trap_index(home_odds, draw_odds, away_odds)
        draw_pressure = self._draw_pressure(home_odds, draw_odds, away_odds, gap)
        stability = self._stability_score(home_odds, draw_odds, away_odds)
        dvf = self._dvf(home_odds, draw_odds, away_odds)
        caf = self._caf(home_odds, draw_odds, away_odds)
        ase = self._ase(home_odds, draw_odds, away_odds)
        udi = self._udi(home_odds, draw_odds, away_odds)
        market_pressure = self._market_pressure(home_odds, draw_odds, away_odds)

        script = self._script_type(home_rating, away_rating, home_odds, draw_odds, away_odds, context)

        hg, ag, score_dist = self._simulate_scores(
            home_prob,
            draw_prob,
            away_prob,
            home_rating,
            away_rating,
            home_odds,
            draw_odds,
            away_odds,
            context,
        )

        if hg > ag:
            predicted = "HOME_WIN"
        elif ag > hg:
            predicted = "AWAY_WIN"
        else:
            predicted = "DRAW"

        flags: List[str] = []
        if script == "FIXED_DRAW":
            flags.append("draw_anchor")
        if script == "COLLAPSE":
            flags.append("collapse_match")
        if script == "CHAOS":
            flags.append("chaos_match")
        if script == "UPSET":
            flags.append("upset_match")
        if ase >= 60:
            flags.append("away_sharpness")
        if trap >= 65:
            flags.append("high_trap")
        if caf >= 68:
            flags.append("blowout_risk")
        if dvf >= 68:
            flags.append("goal_exchange")

        return Prediction(
            home_prob=round(home_prob, 3),
            draw_prob=round(draw_prob, 3),
            away_prob=round(away_prob, 3),
            predicted_result=predicted,
            most_likely_score=f"{hg}-{ag}",
            scoreline_distribution=[(s, round(p, 3)) for s, p in score_dist],
            metrics={
                "gap": round(gap, 2),
                "market_pressure": round(market_pressure, 3),
                "trap_index": round(trap, 1),
                "draw_pressure": round(draw_pressure, 1),
                "stability": round(stability, 1),
                "dvf": round(dvf, 1),
                "caf": round(caf, 1),
                "ase": round(ase, 1),
                "udi": round(udi, 1),
                "round_pressure": round(self.round_pressure, 3),
                "season_chaos": round(self.season_chaos, 2),
            },
            flags=flags,
        )


# -----------------------------
# Example helpers
# -----------------------------

def pretty_print_prediction(title: str, pred: Prediction) -> None:
    print(f"\n=== {title} ===")
    print(f"Home Win: {pred.home_prob:.3f}")
    print(f"Draw    : {pred.draw_prob:.3f}")
    print(f"Away Win: {pred.away_prob:.3f}")
    print(f"Result  : {pred.predicted_result}")
    print(f"Score   : {pred.most_likely_score}")
    print("Metrics :")
    for k, v in pred.metrics.items():
        print(f"  - {k}: {v}")
    if pred.flags:
        print(f"Flags   : {', '.join(pred.flags)}")
    print("Top scorelines:")
    for s, p in pred.scoreline_distribution:
        print(f"  - {s}: {p:.3f}")


# -----------------------------
# Example usage
# -----------------------------

if __name__ == "__main__":
    engine = VirtualLeagueMasterEngine(seed=42)

    # Example 1: odds-only prediction using assumed neutral ratings.
    # You can replace these ratings with your actual team ratings.
    sample_context = MatchContext(recent_results=[(2, 1), (1, 1), (0, 2), (3, 0)])
    pred1 = engine.predict_match(
        home_rating=40.0,
        away_rating=35.0,
        home_odds=2.06,
        draw_odds=3.28,
        away_odds=3.66,
        context=sample_context,
    )
    pretty_print_prediction("Sample Match 1", pred1)

    pred2 = engine.predict_match(
        home_rating=38.0,
        away_rating=46.0,
        home_odds=3.58,
        draw_odds=3.92,
        away_odds=1.89,
        context=sample_context,
    )
    pretty_print_prediction("Sample Match 2", pred2)
