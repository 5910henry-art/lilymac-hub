# reverse_engine_ai.py
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple
import json
import math
import re

import numpy as np


# -----------------------------
# DATA MODELS
# -----------------------------

@dataclass
class Match:
    home: str
    away: str
    home_goals: int
    away_goals: int


@dataclass
class TeamRating:
    attack: float = 1.0   # higher = scores more
    defense: float = 1.0  # higher = harder to score against


# -----------------------------
# NAME NORMALIZATION
# -----------------------------

ALIASES = {
    "a. madrid": "atletico madrid",
    "a madrid": "atletico madrid",
    "atletico": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "a. bilbao": "athletic bilbao",
    "a bilbao": "athletic bilbao",
    "athletic bilbao": "athletic bilbao",
    "r. sociedad": "real sociedad",
    "r sociedad": "real sociedad",
    "real sociedad": "real sociedad",
    "barca": "barcelona",
    "fc barcelona": "barcelona",
    "barcelona": "barcelona",
    "esp": "espanyol",
    "espanyol": "espanyol",
    "osa": "osasuna",
    "osasuna": "osasuna",
    "gra": "granada",
    "granada": "granada",
    "villareal": "villarreal",
    "villarreal": "villarreal",
    "real madrid": "real madrid",
    "getafe": "getafe",
    "almeria": "almeria",
    "alaves": "alaves",
    "betis": "betis",
    "mallorca": "mallorca",
    "sevilla": "sevilla",
    "levante": "levante",
    "leganes": "leganes",
    "valencia": "valencia",
    "valladolid": "valladolid",
    "celta vigo": "celta vigo",
}


def normalize_team(name: str) -> str:
    name = name.strip().lower()
    name = name.replace("(", " ").replace(")", " ")
    name = name.replace(".", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return ALIASES.get(name, name)


def parse_matches(text: str) -> List[Match]:
    """
    Parses lines like:
      Real Madrid 2 - 1 Barca
      A. Madrid 4 â€“ 0 Leganes
    """
    pat = re.compile(
        r"^(?P<home>.+?)\s+(?P<hs>\d+)\s*[-â€“]\s*(?P<as>\d+)\s+(?P<away>.+?)\s*$"
    )
    matches: List[Match] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        low = line.lower()
        if any(
            k in low
            for k in ["week", "time", "home team", "away team", "score", "results", "matchday", "ref:"]
        ):
            continue

        m = pat.match(line)
        if not m:
            continue

        home = normalize_team(m.group("home"))
        away = normalize_team(m.group("away"))
        hs = int(m.group("hs"))
        aw = int(m.group("as"))

        if home and away:
            matches.append(Match(home, away, hs, aw))

    return matches


# -----------------------------
# POISSON HELPERS
# -----------------------------

def poisson_logpmf(k: int, lam: float) -> float:
    lam = max(lam, 1e-12)
    return k * math.log(lam) - lam - math.lgamma(k + 1)


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(poisson_logpmf(k, lam))


def expected_draw_probability(lam_h: float, lam_a: float, max_goals: int = 10) -> float:
    p = 0.0
    for k in range(max_goals + 1):
        p += poisson_pmf(k, lam_h) * poisson_pmf(k, lam_a)
    return p


# -----------------------------
# REVERSE ENGINE AI
# -----------------------------

class ReverseEngineAI:
    """
    Learns a football simulation profile from historical results.

    What it estimates:
      - team attack / defense strengths
      - home advantage
      - draw tendency
      - upset rate
      - score compression
      - likely engine type

    Optional extras:
      - recency-weighted learning from chronological results
      - lightweight form influence (disabled by default)
    """

    def __init__(
        self,
        seed: int = 42,
        epochs: int = 60,
        lr: float = 0.08,
        reg: float = 0.03,
        recency_decay: float = 0.0,
        form_weight: float = 0.0,
        form_window: int = 5,
        noise_strength: float = 0.18,
        swap_prob: float = 0.07,
        draw_gravity_prob: float = 0.18,
        compression_prob: float = 0.55,
    ):
        self.rng = np.random.default_rng(seed)
        self.epochs = epochs
        self.lr = lr
        self.reg = reg

        self.recency_decay = max(0.0, float(recency_decay))
        self.form_weight = float(form_weight)
        self.form_window = max(1, int(form_window))

        self.noise_strength = float(noise_strength)
        self.swap_prob = float(swap_prob)
        self.draw_gravity_prob = float(draw_gravity_prob)
        self.compression_prob = float(compression_prob)

        self.ratings: Dict[str, TeamRating] = {}
        self.home_advantage: float = 1.08
        self.profile: Dict[str, float] = {}

        self.form_history: Dict[str, Deque[int]] = defaultdict(
            lambda: deque(maxlen=self.form_window)
        )

    # -------------------------
    # FIT TEAM STRENGTHS
    # -------------------------

    def fit(self, matches: List[Match]) -> "ReverseEngineAI":
        if not matches:
            raise ValueError("No matches provided.")

        teams = sorted({m.home for m in matches} | {m.away for m in matches})
        self.ratings = {t: TeamRating(attack=1.0, defense=1.0) for t in teams}
        self.form_history = defaultdict(lambda: deque(maxlen=self.form_window))

        # initial home bias from observed raw averages
        avg_home = sum(m.home_goals for m in matches) / len(matches)
        avg_away = sum(m.away_goals for m in matches) / len(matches)
        self.home_advantage = float(np.clip((avg_home + 1e-9) / (avg_away + 1e-9), 0.95, 1.20))

        eps = 1e-9
        total = len(matches)

        for _ in range(self.epochs):
            for idx, m in enumerate(matches):
                w = self._recency_weight(idx, total)
                mu_h, mu_a = self.expected_goals(m.home, m.away)

                err_h = m.home_goals - mu_h
                err_a = m.away_goals - mu_a

                step = self.lr * w

                # Multiplicative updates are stable for Poisson-style models.
                self.ratings[m.home].attack *= math.exp(step * err_h / max(mu_h, 0.35))
                self.ratings[m.away].attack *= math.exp(step * err_a / max(mu_a, 0.35))

                self.ratings[m.home].defense *= math.exp(step * (mu_a - m.away_goals) / max(mu_a, 0.35))
                self.ratings[m.away].defense *= math.exp(step * (mu_h - m.home_goals) / max(mu_h, 0.35))

                self._clip(m.home)
                self._clip(m.away)

                # Update form history after the current match is processed.
                self.form_history[m.home].append(self._match_points(m.home_goals, m.away_goals))
                self.form_history[m.away].append(self._match_points(m.away_goals, m.home_goals))

            self._renormalize()
            self._shrink_to_center()

            # Home advantage update from overall home scoring edge.
            # Kept intentionally small to avoid over-correction.
            mu_home_total = 0.0
            obs_home_total = 0.0
            for idx, m in enumerate(matches):
                w = self._recency_weight(idx, total)
                mu_h, _ = self.expected_goals(m.home, m.away)
                mu_home_total += mu_h * w
                obs_home_total += m.home_goals * w

            if mu_home_total > eps:
                ratio = obs_home_total / mu_home_total
                self.home_advantage *= math.exp(0.25 * self.lr * (ratio - 1.0))
                self.home_advantage = float(np.clip(self.home_advantage, 0.90, 1.30))

            # mild regularization to stop ratings from drifting too far
            if self.reg > 0:
                for r in self.ratings.values():
                    r.attack *= (1.0 - min(self.reg, 0.10) * 0.02)
                    r.defense *= (1.0 - min(self.reg, 0.10) * 0.02)

        self.profile = self.analyze(matches)
        return self

    # -------------------------
    # MODEL
    # -------------------------

    def expected_goals(self, home: str, away: str) -> Tuple[float, float]:
        home = normalize_team(home)
        away = normalize_team(away)

        if home not in self.ratings or away not in self.ratings:
            raise KeyError(f"Unknown team(s): {home}, {away}")

        rh = self.ratings[home]
        ra = self.ratings[away]

        # Ratio model: stable, low-scoring, works well for compact leagues.
        mu_h = self.home_advantage * (rh.attack / max(ra.defense, 1e-9))
        mu_a = (ra.attack / max(rh.defense, 1e-9))

        # Optional lightweight form adjustment.
        if self.form_weight != 0.0:
            home_form = self._form_signal(home)
            away_form = self._form_signal(away)
            form_gap = home_form - away_form

            home_mult = 1.0 + (self.form_weight * form_gap)
            away_mult = 1.0 - (self.form_weight * form_gap * 0.5)

            mu_h *= float(np.clip(home_mult, 0.80, 1.25))
            mu_a *= float(np.clip(away_mult, 0.80, 1.25))

        # realistic clipping
        mu_h = float(np.clip(mu_h, 0.15, 4.50))
        mu_a = float(np.clip(mu_a, 0.15, 4.50))
        return mu_h, mu_a

    def simulate_match(self, home: str, away: str) -> Tuple[int, int]:
        home = normalize_team(home)
        away = normalize_team(away)

        mu_h, mu_a = self.expected_goals(home, away)

        # STEP 1: Inject noise into expected goals
        mu_h = max(0.1, mu_h + self.rng.uniform(-self.noise_strength, self.noise_strength))
        mu_a = max(0.1, mu_a + self.rng.uniform(-self.noise_strength, self.noise_strength))

        # STEP 2: Base Poisson generation
        gh = int(self.rng.poisson(mu_h))
        ga = int(self.rng.poisson(mu_a))

        # STEP 3: Outcome-level randomness
        if self.rng.random() < self.swap_prob:
            gh, ga = ga, gh

        # STEP 4: Draw gravity (reduced so draws don't dominate)
        if abs(mu_h - mu_a) < 0.25:
            if self.rng.random() < self.draw_gravity_prob:
                gh = ga

        # STEP 5: Score compression
        if gh + ga >= 5 and self.rng.random() < self.compression_prob:
            if gh > ga and gh > 0:
                gh -= 1
            elif ga > gh and ga > 0:
                ga -= 1

        return gh, ga

    def predict(self, home: str, away: str, sims: int = 4000) -> Dict[str, float]:
        home = normalize_team(home)
        away = normalize_team(away)

        counts = defaultdict(int)
        hw = dr = aw = 0

        for _ in range(sims):
            gh, ga = self.simulate_match(home, away)
            counts[(gh, ga)] += 1
            if gh > ga:
                hw += 1
            elif gh < ga:
                aw += 1
            else:
                dr += 1

        best = max(counts.items(), key=lambda x: x[1])[0]
        mu_h, mu_a = self.expected_goals(home, away)

        return {
            "home": home,
            "away": away,
            "lambda_home": round(mu_h, 3),
            "lambda_away": round(mu_a, 3),
            "most_likely_score": f"{best[0]}-{best[1]}",
            "home_win_prob": round(hw / sims, 4),
            "draw_prob": round(dr / sims, 4),
            "away_win_prob": round(aw / sims, 4),
        }

    # -------------------------
    # ANALYTICS / REVERSE ENGINEERING
    # -------------------------

    def analyze(self, matches: List[Match]) -> Dict[str, float]:
        total = len(matches)
        if total == 0:
            return {}

        home_wins = sum(1 for m in matches if m.home_goals > m.away_goals)
        draws = sum(1 for m in matches if m.home_goals == m.away_goals)
        away_wins = total - home_wins - draws

        home_goals = [m.home_goals for m in matches]
        away_goals = [m.away_goals for m in matches]
        totals = [m.home_goals + m.away_goals for m in matches]
        diffs = [abs(m.home_goals - m.away_goals) for m in matches]

        low_scoring = sum(1 for t in totals if t <= 2)
        moderate = sum(1 for t in totals if t in (3, 4))
        blowouts = sum(1 for t in totals if t >= 5)

        upset_count = 0
        close_draw_count = 0
        for m in matches:
            mu_h, mu_a = self.expected_goals(m.home, m.away)
            if abs(mu_h - mu_a) < 0.25 and m.home_goals == m.away_goals:
                close_draw_count += 1

            predicted_home = mu_h >= mu_a
            actual_home_win = m.home_goals > m.away_goals

            # upset if lower-expected-goals side wins
            if predicted_home and not actual_home_win and m.home_goals < m.away_goals:
                upset_count += 1
            elif (not predicted_home) and actual_home_win:
                upset_count += 1

        upset_rate = upset_count / total
        draw_gravity = close_draw_count / max(1, draws)

        avg_home = float(np.mean(home_goals))
        avg_away = float(np.mean(away_goals))
        avg_total = float(np.mean(totals))
        avg_diff = float(np.mean(diffs))
        goal_std = float(np.std(totals))

        exp_draws = []
        for m in matches:
            mu_h, mu_a = self.expected_goals(m.home, m.away)
            exp_draws.append(expected_draw_probability(mu_h, mu_a))
        expected_draw = float(np.mean(exp_draws))
        draw_bias_index = (draws / total) / max(expected_draw, 1e-9)

        randomness_index = goal_std / max(avg_total, 1e-9)
        score_compression = (low_scoring + moderate) / total
        high_score_scarcity = blowouts / total

        engine_guess = self._guess_engine_type(
            draw_rate=draws / total,
            score_compression=score_compression,
            upset_rate=upset_rate,
            home_bias=self.home_advantage,
            randomness_index=randomness_index,
        )

        return {
            "matches": total,
            "home_win_rate": round(home_wins / total, 4),
            "draw_rate": round(draws / total, 4),
            "away_win_rate": round(away_wins / total, 4),
            "avg_home_goals": round(avg_home, 4),
            "avg_away_goals": round(avg_away, 4),
            "avg_total_goals": round(avg_total, 4),
            "avg_goal_difference": round(avg_diff, 4),
            "goal_std": round(goal_std, 4),
            "score_compression_index": round(score_compression, 4),
            "high_score_scarcity": round(high_score_scarcity, 4),
            "upset_rate": round(upset_rate, 4),
            "close_draw_rate": round(draw_gravity, 4),
            "expected_draw_rate": round(expected_draw, 4),
            "draw_bias_index": round(draw_bias_index, 4),
            "randomness_index": round(randomness_index, 4),
            "home_advantage": round(self.home_advantage, 4),
            "engine_guess": engine_guess,
        }

    def _guess_engine_type(
        self,
        draw_rate: float,
        score_compression: float,
        upset_rate: float,
        home_bias: float,
        randomness_index: float,
    ) -> str:
        """
        Rule-of-thumb classification from the observed profile.
        """
        if draw_rate >= 0.28 and score_compression >= 0.65 and home_bias >= 1.08:
            if upset_rate >= 0.10:
                return "Low-lambda Poisson simulator with home bias, draw gravity, and upset noise"
            return "Low-lambda Poisson simulator with home bias and draw gravity"
        if randomness_index > 0.80 and upset_rate >= 0.15:
            return "Balanced stochastic simulator with strong variance"
        if home_bias >= 1.15 and draw_rate < 0.20:
            return "Home-advantaged simulator with moderate randomness"
        return "Hybrid football simulator with ratings + random outcome layer"

    # -------------------------
    # DETECT UPSETS AND PATTERNS
    # -------------------------

    def upset_matches(self, matches: List[Match]) -> List[Dict[str, object]]:
        out = []
        for m in matches:
            mu_h, mu_a = self.expected_goals(m.home, m.away)
            predicted_favored = m.home if mu_h >= mu_a else m.away
            actual_winner = "draw"
            if m.home_goals > m.away_goals:
                actual_winner = m.home
            elif m.away_goals > m.home_goals:
                actual_winner = m.away

            if actual_winner != "draw" and actual_winner != predicted_favored:
                out.append(
                    {
                        "home": m.home,
                        "away": m.away,
                        "score": f"{m.home_goals}-{m.away_goals}",
                        "favored": predicted_favored,
                        "winner": actual_winner,
                        "lambda_home": round(mu_h, 3),
                        "lambda_away": round(mu_a, 3),
                    }
                )
        return out

    def team_table(self, matches: List[Match]) -> List[Dict[str, object]]:
        table = defaultdict(
            lambda: {
                "team": "",
                "played": 0,
                "w": 0,
                "d": 0,
                "l": 0,
                "gf": 0,
                "ga": 0,
                "gd": 0,
                "pts": 0,
            }
        )

        for m in matches:
            for t in (m.home, m.away):
                table[t]["team"] = t

            table[m.home]["played"] += 1
            table[m.away]["played"] += 1

            table[m.home]["gf"] += m.home_goals
            table[m.home]["ga"] += m.away_goals
            table[m.away]["gf"] += m.away_goals
            table[m.away]["ga"] += m.home_goals

            if m.home_goals > m.away_goals:
                table[m.home]["w"] += 1
                table[m.away]["l"] += 1
                table[m.home]["pts"] += 3
            elif m.home_goals < m.away_goals:
                table[m.away]["w"] += 1
                table[m.home]["l"] += 1
                table[m.away]["pts"] += 3
            else:
                table[m.home]["d"] += 1
                table[m.away]["d"] += 1
                table[m.home]["pts"] += 1
                table[m.away]["pts"] += 1

        rows = []
        for team, r in table.items():
            r["gd"] = r["gf"] - r["ga"]
            rows.append(r)

        rows.sort(key=lambda x: (x["pts"], x["gd"], x["gf"]), reverse=True)
        return rows

    def ratings_report(self) -> Dict[str, Dict[str, float]]:
        return {
            team: {
                "attack": round(r.attack, 4),
                "defense": round(r.defense, 4),
            }
            for team, r in sorted(self.ratings.items())
        }

    def report_json(self) -> str:
        return json.dumps(
            {
                "home_advantage": round(self.home_advantage, 4),
                "profile": self.profile,
                "ratings": self.ratings_report(),
            },
            indent=2,
        )

    # -------------------------
    # INTERNAL STABILITY
    # -------------------------

    def _clip(self, team: str) -> None:
        self.ratings[team].attack = float(np.clip(self.ratings[team].attack, 0.50, 3.00))
        self.ratings[team].defense = float(np.clip(self.ratings[team].defense, 0.50, 3.00))

    def _renormalize(self) -> None:
        attacks = np.array([r.attack for r in self.ratings.values()], dtype=float)
        defenses = np.array([r.defense for r in self.ratings.values()], dtype=float)

        a_mean = float(np.mean(attacks))
        d_mean = float(np.mean(defenses))

        if a_mean > 0:
            for r in self.ratings.values():
                r.attack /= a_mean
        if d_mean > 0:
            for r in self.ratings.values():
                r.defense /= d_mean

    def _shrink_to_center(self) -> None:
        """
        Prevents rating collapse and keeps separation stable.
        """
        for r in self.ratings.values():
            r.attack = 1.0 + (r.attack - 1.0) * 0.985
            r.defense = 1.0 + (r.defense - 1.0) * 0.985
            r.attack = float(np.clip(r.attack, 0.50, 3.00))
            r.defense = float(np.clip(r.defense, 0.50, 3.00))

    def _match_points(self, goals_for: int, goals_against: int) -> int:
        if goals_for > goals_against:
            return 3
        if goals_for < goals_against:
            return 0
        return 1

    def _form_signal(self, team: str) -> float:
        hist = self.form_history.get(normalize_team(team))
        if not hist:
            return 0.0
        # Map [0, 3] average points to roughly [-0.5, +0.5]
        avg_pts = sum(hist) / len(hist)
        return (avg_pts - 1.5) / 3.0

    def _recency_weight(self, index: int, total: int) -> float:
        """
        Exponential recency weighting.
        0.0 disables recency effects.
        """
        if self.recency_decay <= 0.0 or total <= 1:
            return 1.0
        age = (total - 1) - index
        return float(math.exp(-self.recency_decay * age))


# -----------------------------
# OPTIONAL: DETERMINISM CHECK
# -----------------------------

def detect_determinism(
    engine: ReverseEngineAI,
    home: str,
    away: str,
    runs: int = 50,
) -> Dict[str, object]:
    outcomes = Counter()
    for _ in range(runs):
        outcomes[engine.simulate_match(home, away)] += 1

    unique = len(outcomes)
    top_count = max(outcomes.values()) if outcomes else 0
    dominant_ratio = top_count / runs if runs else 0.0

    if unique == 1:
        label = "fully_deterministic"
    elif dominant_ratio > 0.90:
        label = "semi_deterministic"
    else:
        label = "stochastic"

    return {
        "home": normalize_team(home),
        "away": normalize_team(away),
        "runs": runs,
        "unique_outcomes": unique,
        "dominant_ratio": round(dominant_ratio, 4),
        "label": label,
        "top_outcomes": outcomes.most_common(5),
    }


# -----------------------------
# EXAMPLE RUN
# -----------------------------

if __name__ == "__main__":
    RAW = r"""
    Real Madrid 3 - 1 Leganes
    Esp 2 - 0 Villareal
    Betis 0 - 1 Almeria
    Mallorca 2 - 1 Getafe
    Alaves 3 - 0 Valencia
    Gra 1 - 1 Valladolid
    Osa 3 - 3 Levante
    Celta Vigo 0 - 0 Barca
    R. Sociedad 3 - 1 Sevilla
    A. Bilbao 1 - 0 A. Madrid
    """

    matches = parse_matches(RAW)
    ai = ReverseEngineAI(seed=42).fit(matches)

    print("=== AI ENGINE PROFILE ===")
    print(ai.report_json())

    print("\n=== TEAM TABLE ===")
    for row in ai.team_table(matches):
        print(row)

    print("\n=== UPSETS ===")
    for item in ai.upset_matches(matches):
        print(item)

    print("\n=== PREDICTION ===")
    print(ai.predict("Real Madrid", "Barcelona"))

    print("\n=== DETERMINISM TEST ===")
    print(detect_determinism(ai, "Real Madrid", "Barcelona"))
