#!/usr/bin/env python3
"""Full virtual league forensic analyzer.

Reads a results file like results.txt, reconstructs league tables and team
strength from outcomes, and optionally compares actual results against a
trained market-clone / latent-strength model saved as model.json.

Outputs:
- league table
- home/away split
- team attack/defense proxies
- Elo-style inferred strength from results only
- upset / surprise report
- calibration report versus model.json, if present
- JSON report on disk

Expected results.txt format:

WEEK 1
Team A 2-1 Team B
Team C 0-0 Team D
...

Notes:
- Team aliases are normalized for common short forms.
- The analyzer is intentionally conservative: it infers structure from
  observed results rather than predicting future matches.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass, asdict
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

EPS = 1e-12
SMOOTH_EPS = 1e-8

TEAM_ALIAS = {
    "Barca": "Barcelona",
    "Barsa": "Barcelona",
    "Barcelona": "Barcelona",
    "R. Madrid": "Real Madrid",
    "A. Madrid": "Atletico Madrid",
    "A. Bilbao": "Athletic Bilbao",
    "Gra": "Granada",
    "Esp": "Espanyol",
    "Osa": "Osasuna",
    "R. Sociedad": "Real Sociedad",
    "Villareal": "Villarreal",
}


@dataclass(frozen=True)
class Match:
    week: int
    home: str
    away: str
    home_goals: int
    away_goals: int

    @property
    def goal_diff(self) -> int:
        return self.home_goals - self.away_goals

    @property
    def result(self) -> str:
        if self.home_goals > self.away_goals:
            return "H"
        if self.home_goals < self.away_goals:
            return "A"
        return "D"


@dataclass
class TeamSummary:
    team: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    gf: int = 0
    ga: int = 0
    home_played: int = 0
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    away_played: int = 0
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0

    @property
    def points(self) -> int:
        return self.wins * 3 + self.draws

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    @property
    def avg_gf(self) -> float:
        return self.gf / self.played if self.played else 0.0

    @property
    def avg_ga(self) -> float:
        return self.ga / self.played if self.played else 0.0


@dataclass
class EloState:
    rating: float = 1500.0
    games: int = 0
    last_week: int = 0


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def normalize_team_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    m = re.search(r"\(([^)]+)\)", name)
    if m:
        name = m.group(1).strip()
    return TEAM_ALIAS.get(name, name)


def parse_result_line(line: str) -> Optional[Tuple[str, int, int, str]]:
    line = line.strip()
    if not line:
        return None
    m = re.match(r"(.+?)\s+(\d+)-(\d+)\s+(.+)$", line)
    if not m:
        return None
    home = normalize_team_name(m.group(1))
    hg = int(m.group(2))
    ag = int(m.group(3))
    away = normalize_team_name(m.group(4))
    return home, hg, ag, away


def load_results(path: str) -> List[Match]:
    matches: List[Match] = []
    week = 0

    week_header = re.compile(r"^WEEK\s+(\d+)\s*$", re.IGNORECASE)

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            wm = week_header.match(line)
            if wm:
                week = int(wm.group(1))
                continue

            parsed = parse_result_line(line)
            if parsed is None:
                continue

            home, hg, ag, away = parsed
            matches.append(Match(week=week, home=home, away=away, home_goals=hg, away_goals=ag))

    return matches


# ---------------------------------------------------------------------------
# Basic league stats
# ---------------------------------------------------------------------------

def build_team_summaries(matches: Sequence[Match]) -> Dict[str, TeamSummary]:
    teams: Dict[str, TeamSummary] = {}

    def get(team: str) -> TeamSummary:
        if team not in teams:
            teams[team] = TeamSummary(team=team)
        return teams[team]

    for m in matches:
        h = get(m.home)
        a = get(m.away)

        h.played += 1
        a.played += 1
        h.gf += m.home_goals
        h.ga += m.away_goals
        a.gf += m.away_goals
        a.ga += m.home_goals

        h.home_played += 1
        a.away_played += 1

        if m.home_goals > m.away_goals:
            h.wins += 1
            a.losses += 1
            h.home_wins += 1
            a.away_losses += 1
        elif m.home_goals < m.away_goals:
            h.losses += 1
            a.wins += 1
            h.home_losses += 1
            a.away_wins += 1
        else:
            h.draws += 1
            a.draws += 1
            h.home_draws += 1
            a.away_draws += 1

    return teams


def league_table(teams: Dict[str, TeamSummary]) -> List[TeamSummary]:
    return sorted(
        teams.values(),
        key=lambda t: (t.points, t.gd, t.gf, -t.ga, t.team),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Elo-style inference from results only
# ---------------------------------------------------------------------------

def expected_home_prob_elo(r_home: float, r_away: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(r_home + home_adv - r_away) / 400.0))


def run_elo_inference(
    matches: Sequence[Match],
    k_factor: float = 18.0,
    home_adv: float = 65.0,
    initial_rating: float = 1500.0,
    draw_as_half: bool = True,
) -> Dict[str, EloState]:
    teams = sorted({m.home for m in matches} | {m.away for m in matches})
    state = {t: EloState(rating=initial_rating) for t in teams}

    for m in matches:
        rh = state[m.home].rating
        ra = state[m.away].rating
        ph = expected_home_prob_elo(rh, ra, home_adv)

        if m.home_goals > m.away_goals:
            sh, sa = 1.0, 0.0
        elif m.home_goals < m.away_goals:
            sh, sa = 0.0, 1.0
        else:
            sh = sa = 0.5 if draw_as_half else 0.0

        state[m.home].rating = rh + k_factor * (sh - ph)
        state[m.away].rating = ra + k_factor * (sa - (1.0 - ph))
        state[m.home].games += 1
        state[m.away].games += 1
        state[m.home].last_week = m.week
        state[m.away].last_week = m.week

    return state


# ---------------------------------------------------------------------------
# Goal-based strength proxies
# ---------------------------------------------------------------------------

def goal_strength_report(teams: Dict[str, TeamSummary]) -> List[dict]:
    rows = []
    for t in teams.values():
        attack = t.avg_gf
        defense = t.avg_ga
        net = attack - defense
        rows.append(
            {
                "team": t.team,
                "attack_per_game": round(attack, 3),
                "defense_per_game": round(defense, 3),
                "net_goals_per_game": round(net, 3),
                "home_ppg": round((t.home_wins * 3 + t.home_draws) / t.home_played, 3) if t.home_played else 0.0,
                "away_ppg": round((t.away_wins * 3 + t.away_draws) / t.away_played, 3) if t.away_played else 0.0,
            }
        )
    rows.sort(key=lambda r: (r["net_goals_per_game"], r["attack_per_game"], r["team"]), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Model comparison helpers
# ---------------------------------------------------------------------------

def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def predict_probs(r_home, r_away, home_adv, base_draw, draw_k):
    diff = (r_home + home_adv) - r_away
    gap = math.sqrt(diff * diff + SMOOTH_EPS)

    p_home_core = sigmoid(diff)
    p_draw = base_draw * math.exp(-draw_k * gap)
    p_draw = min(max(p_draw, EPS), 1.0 - EPS)
    rem = 1.0 - p_draw
    p_home = rem * p_home_core
    p_away = rem * (1.0 - p_home_core)

    probs = np.array([p_home, p_draw, p_away], dtype=float)
    probs = np.clip(probs, EPS, 1.0)
    probs = probs / probs.sum()
    return probs


def load_model(model_path: str) -> Optional[dict]:
    if not model_path:
        return None
    if not os.path.exists(model_path):
        return None
    with open(model_path, "r", encoding="utf-8") as f:
        return json.load(f)


def outcome_vector(m: Match) -> np.ndarray:
    if m.home_goals > m.away_goals:
        return np.array([1.0, 0.0, 0.0], dtype=float)
    if m.home_goals < m.away_goals:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return np.array([0.0, 1.0, 0.0], dtype=float)


def entropy(p: np.ndarray) -> float:
    p = np.clip(p, EPS, 1.0)
    return float(-np.sum(p * np.log(p)))


def softmax_like_gap(score_home: float, score_away: float) -> float:
    return float(score_home - score_away)


# ---------------------------------------------------------------------------
# Forensic metrics
# ---------------------------------------------------------------------------

def compute_match_metrics(matches: Sequence[Match], teams: Dict[str, TeamSummary], model: Optional[dict] = None) -> dict:
    total = len(matches)
    home_wins = sum(1 for m in matches if m.home_goals > m.away_goals)
    draws = sum(1 for m in matches if m.home_goals == m.away_goals)
    away_wins = total - home_wins - draws
    total_goals = sum(m.home_goals + m.away_goals for m in matches)
    avg_goals = total_goals / total if total else 0.0

    # Upset definition based on model ratings if present; otherwise goal-diff surprise.
    upset_count = 0
    surprise_sum = 0.0
    calibration = []
    brier_sum = 0.0
    nll_sum = 0.0

    if model and "ratings" in model:
        ratings = {normalize_team_name(k): float(v) for k, v in model["ratings"].items()}
        home_adv = float(model.get("home_adv", 0.25))
        base_draw = float(model.get("base_draw", 0.27))
        draw_k = float(model.get("draw_k", 0.05))

        for m in matches:
            rh = ratings.get(m.home, 0.0)
            ra = ratings.get(m.away, 0.0)
            pred = predict_probs(rh, ra, home_adv, base_draw, draw_k)
            actual = outcome_vector(m)

            brier_sum += float(np.sum((pred - actual) ** 2))
            nll_sum += -math.log(float(np.dot(pred, actual)) + EPS)
            calibration.append(
                {
                    "week": m.week,
                    "home": m.home,
                    "away": m.away,
                    "pred_home": round(float(pred[0]), 4),
                    "pred_draw": round(float(pred[1]), 4),
                    "pred_away": round(float(pred[2]), 4),
                    "actual": m.result,
                    "actual_home_goals": m.home_goals,
                    "actual_away_goals": m.away_goals,
                }
            )

            fav = int(np.argmax(pred))  # 0=home,1=draw,2=away
            actual_idx = 0 if m.result == "H" else 1 if m.result == "D" else 2
            if fav != actual_idx:
                upset_count += 1
                surprise_sum += 1.0 - float(pred[actual_idx])

    else:
        # No model file: use goal-difference surprise proxy.
        for m in matches:
            gd = abs(m.goal_diff)
            if gd >= 2:
                surprise_sum += 0.5
            if gd >= 3:
                upset_count += 1

    return {
        "matches": total,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "home_win_rate": round(home_wins / total, 4) if total else 0.0,
        "draw_rate": round(draws / total, 4) if total else 0.0,
        "away_win_rate": round(away_wins / total, 4) if total else 0.0,
        "total_goals": total_goals,
        "avg_goals_per_match": round(avg_goals, 4),
        "upset_count": upset_count,
        "surprise_sum": round(surprise_sum, 4),
        "brier_score": round(brier_sum / total, 6) if model and total else None,
        "log_loss": round(nll_sum / total, 6) if model and total else None,
        "calibration_sample": calibration[:50] if calibration else [],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_table(rows: Sequence[TeamSummary], limit: Optional[int] = None) -> str:
    out = []
    header = f"{'Team':20s} {'P':>3s} {'W':>3s} {'D':>3s} {'L':>3s} {'GF':>4s} {'GA':>4s} {'GD':>4s} {'Pts':>4s}"
    out.append(header)
    out.append("-" * len(header))
    for t in rows[:limit]:
        out.append(
            f"{t.team:20s} {t.played:3d} {t.wins:3d} {t.draws:3d} {t.losses:3d} {t.gf:4d} {t.ga:4d} {t.gd:4d} {t.points:4d}"
        )
    return "\n".join(out)


def format_elo_table(state: Dict[str, EloState], limit: Optional[int] = None) -> str:
    rows = sorted(state.items(), key=lambda kv: (kv[1].rating, kv[0]), reverse=True)
    out = []
    out.append(f"{'Team':20s} {'Elo':>8s} {'Games':>6s}")
    out.append("-" * 38)
    for team, st in rows[:limit]:
        out.append(f"{team:20s} {st.rating:8.2f} {st.games:6d}")
    return "\n".join(out)


def format_goal_table(rows: Sequence[dict], limit: Optional[int] = None) -> str:
    out = []
    out.append(f"{'Team':20s} {'Att/G':>6s} {'Def/G':>6s} {'Net/G':>6s} {'HPPG':>6s} {'APPG':>6s}")
    out.append("-" * 55)
    for r in rows[:limit]:
        out.append(
            f"{r['team']:20s} {r['attack_per_game']:6.2f} {r['defense_per_game']:6.2f} {r['net_goals_per_game']:6.2f} {r['home_ppg']:6.2f} {r['away_ppg']:6.2f}"
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a virtual league from results.txt")
    parser.add_argument("results", nargs="?", default="results.txt", help="Path to results.txt")
    parser.add_argument("--model", default="model.json", help="Path to learned model.json (optional)")
    parser.add_argument("--elo-k", type=float, default=18.0, help="Elo K-factor")
    parser.add_argument("--elo-home-adv", type=float, default=65.0, help="Elo home advantage in rating points")
    parser.add_argument("--report", default="forensic_report.json", help="Output JSON report path")
    parser.add_argument("--top", type=int, default=20, help="How many rows to print in leaderboards")
    args = parser.parse_args()

    matches = load_results(args.results)
    if not matches:
        raise SystemExit(f"No matches parsed from {args.results}")

    teams = build_team_summaries(matches)
    table = league_table(teams)
    elo_state = run_elo_inference(matches, k_factor=args.elo_k, home_adv=args.elo_home_adv)
    goal_rows = goal_strength_report(teams)
    model = load_model(args.model)
    metrics = compute_match_metrics(matches, teams, model=model)

    # Additional league-wide indicators.
    total_home_points = sum(t.home_wins * 3 + t.home_draws for t in teams.values())
    total_away_points = sum(t.away_wins * 3 + t.away_draws for t in teams.values())
    total_home_games = sum(t.home_played for t in teams.values())
    total_away_games = sum(t.away_played for t in teams.values())
    home_ppg = total_home_points / total_home_games if total_home_games else 0.0
    away_ppg = total_away_points / total_away_games if total_away_games else 0.0
    home_edge_ppg = home_ppg - away_ppg

    report = {
        "source": os.path.abspath(args.results),
        "teams": len(teams),
        "matches": len(matches),
        "weeks": sorted({m.week for m in matches if m.week}),
        "summary": {
            "home_ppg": round(home_ppg, 4),
            "away_ppg": round(away_ppg, 4),
            "home_edge_ppg": round(home_edge_ppg, 4),
        },
        "metrics": metrics,
        "league_table": [asdict(t) | {"points": t.points, "gd": t.gd} for t in table],
        "elo_table": [
            {"team": team, "elo": round(st.rating, 3), "games": st.games}
            for team, st in sorted(elo_state.items(), key=lambda kv: (kv[1].rating, kv[0]), reverse=True)
        ],
        "goal_table": goal_rows,
    }

    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\nFULL VIRTUAL LEAGUE FORENSIC ANALYZER")
    print("=" * 44)
    print(f"Matches: {len(matches)}")
    print(f"Teams:   {len(teams)}")
    print(f"Weeks:   {len(report['weeks'])}")
    print()
    print("MATCH ENVIRONMENT")
    print(f"Home PPG : {home_ppg:.3f}")
    print(f"Away PPG : {away_ppg:.3f}")
    print(f"Home edge: {home_edge_ppg:.3f}")
    print(f"Home wins: {metrics['home_wins']}  Draws: {metrics['draws']}  Away wins: {metrics['away_wins']}")
    print(f"Goals/match: {metrics['avg_goals_per_match']:.3f}")
    print(f"Upsets flagged: {metrics['upset_count']}")
    print(f"Surprise mass: {metrics['surprise_sum']}")
    if metrics.get("brier_score") is not None:
        print(f"Brier score vs model: {metrics['brier_score']:.6f}")
        print(f"Log loss vs model:   {metrics['log_loss']:.6f}")
    print()
    print("LEAGUE TABLE")
    print(format_table(table, limit=args.top))
    print()
    print("ELO-INFERRED STRENGTH")
    print(format_elo_table(elo_state, limit=args.top))
    print()
    print("GOAL-BASED STRENGTH PROXIES")
    print(format_goal_table(goal_rows, limit=args.top))
    print()
    print(f"Report saved to {args.report}")


if __name__ == "__main__":
    main()
