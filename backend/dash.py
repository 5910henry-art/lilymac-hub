#!/usr/bin/env python3
import asyncio
import asyncpg
from datetime import datetime, UTC
from decimal import Decimal

from config2 import DATABASE_URL


# ----------------------
# Helpers
# ----------------------
def confidence_label(prob, market_type="3-way"):
    market = (market_type or "").strip().lower()

    if market in ("3-way", "3way", "home", "draw", "away"):
        low, high = 0.7, 0.8
    elif market == "btts":
        low, high = 0.6, 0.75
    elif market.startswith("o"):
        low, high = 0.65, 0.8
    else:
        low, high = 0.7, 0.8

    if prob >= high:
        return "High"
    if prob >= low:
        return "Medium"
    return "Low"


def safe_float(v, default=0.0):
    try:
        if isinstance(v, Decimal):
            return float(v)
        return float(v) if v is not None else default
    except Exception:
        return default


def ensure_utc_naive(dt):
    """Convert any datetime to naive UTC."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def rec_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def eq_fuzzy(a, b, places=3):
    a = ensure_utc_naive(a)
    b = ensure_utc_naive(b)

    if a is None and b is None:
        return True
    try:
        return round(float(a), places) == round(float(b), places)
    except Exception:
        return a == b


def rows_differ(existing, new_values):
    numeric_cols = {"odds", "weighted_score", "expected_value", "hybrid_score"}

    for k, newv in new_values.items():
        oldv = rec_get(existing, k)

        if k in numeric_cols:
            if not eq_fuzzy(oldv, newv):
                return True
        else:
            oldv_n = ensure_utc_naive(oldv)
            newv_n = ensure_utc_naive(newv)

            if (oldv_n is None and newv_n in (None, "", "-")) or (newv_n is None and oldv_n in (None, "", "-")):
                continue

            if oldv_n != newv_n:
                return True

    return False


def compute_weighted_score(prob, conf_label, odds, market_type):
    conf_map = {"High": 3, "Medium": 2, "Low": 1}
    conf_val = conf_map.get(conf_label, 2)

    market = (market_type or "").strip().lower()
    if market in ("3-way", "3way", "home", "draw", "away"):
        market_weight = 1.0
    elif market == "btts":
        market_weight = 1.1
    elif market.startswith("o"):
        market_weight = 1.05
    else:
        market_weight = 1.0

    base_score = (prob or 0) * 0.6 + (conf_val / 3) * 0.3
    weighted_score = base_score * market_weight + (odds or 1.0) / 10
    return round(weighted_score, 3)


def compute_expected_value(prob, odds, conf_label):
    conf_order = {"High": 0.3, "Medium": 0.2, "Low": 0.1}
    conf_adj = conf_order.get(conf_label, 0.2)
    prob_value = prob if prob and 0 < prob <= 1 else 0.5
    ev = prob_value * (odds - 1) + conf_adj if odds else prob_value
    return round(ev, 3)


def compute_result(status, prediction, threshold, home_score, away_score):
    if status is None or (isinstance(status, str) and status.lower() != "finished"):
        return "pending"

    home_score = home_score or 0
    away_score = away_score or 0
    total_goals = home_score + away_score
    sel = (prediction or "").upper()

    if sel in ("HOME", "AWAY", "DRAW"):
        winner = "HOME" if home_score > away_score else "AWAY" if home_score < away_score else "DRAW"
        return "won" if sel == winner else "lost"

    if sel in ("YES", "NO"):
        both = home_score > 0 and away_score > 0
        return "won" if (sel == "YES" and both) or (sel == "NO" and not both) else "lost"

    if sel == "OVER":
        try:
            th = float(threshold)
            return "won" if total_goals > th else "lost"
        except Exception:
            return "lost"

    return "lost"


async def deduplicate_over_markets(conn):
    await conn.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY match_id
                    ORDER BY hybrid_score DESC NULLS LAST, last_updated DESC, id DESC
                ) AS rn
            FROM dashboard
            WHERE UPPER(prediction) = 'OVER'
        )
        DELETE FROM dashboard d
        USING ranked r
        WHERE d.id = r.id
          AND r.rn > 1
        """
    )


async def keep_top_tip_per_match(conn):
    await conn.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY match_id
                    ORDER BY hybrid_score DESC NULLS LAST, last_updated DESC, id DESC
                ) AS rn
            FROM dashboard
        )
        DELETE FROM dashboard d
        USING ranked r
        WHERE d.id = r.id
          AND r.rn > 1
        """
    )


# ----------------------
# Main
# ----------------------
async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    inserted = updated = skipped = errors = 0

    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard (
                id BIGSERIAL PRIMARY KEY,
                match_id INTEGER NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                prediction TEXT NOT NULL,
                threshold TEXT,
                odds DOUBLE PRECISION,
                confidence TEXT,
                weighted_score DOUBLE PRECISION,
                expected_value DOUBLE PRECISION,
                hybrid_score DOUBLE PRECISION,
                risk_tier TEXT,
                status TEXT,
                match_time TIMESTAMP,
                result TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_id, prediction, threshold)
            )
            """
        )

        acc_rows = await conn.fetch("SELECT * FROM accumulator")

        for row in acc_rows:
            try:
                match_id = rec_get(row, "match_id")
                market = rec_get(row, "market")
                selection = rec_get(row, "selection")
                market_lower = (market or "").strip().lower()
                prob = safe_float(rec_get(row, "probability"), 0.5)

                confidence = confidence_label(prob, market_type=market)

                match = await conn.fetchrow(
                    """
                    SELECT
                        home_team_name,
                        away_team_name,
                        home_score,
                        away_score,
                        status,
                        utcDate AS match_time
                    FROM matches
                    WHERE id = $1
                    """,
                    match_id,
                )
                if not match:
                    skipped += 1
                    continue

                home_team = rec_get(match, "home_team_name")
                away_team = rec_get(match, "away_team_name")
                status = rec_get(match, "status")
                match_time = ensure_utc_naive(rec_get(match, "match_time"))
                home_score = rec_get(match, "home_score") or 0
                away_score = rec_get(match, "away_score") or 0

                odds = None
                threshold = None

                odds_row = await conn.fetchrow(
                    "SELECT * FROM bookmark WHERE match_id = $1",
                    match_id,
                )

                if odds_row:
                    sel_upper = (selection or "").upper()

                    if market_lower == "3-way":
                        if sel_upper == "HOME":
                            odds = safe_float(rec_get(odds_row, "home_odds"), 1.0)
                        elif sel_upper == "DRAW":
                            odds = safe_float(rec_get(odds_row, "draw_odds"), 1.0)
                        elif sel_upper == "AWAY":
                            odds = safe_float(rec_get(odds_row, "away_odds"), 1.0)

                    elif market_lower == "btts":
                        if sel_upper == "YES":
                            odds = safe_float(rec_get(odds_row, "gg_odds"), 1.0)
                        else:
                            odds = safe_float(rec_get(odds_row, "ng_odds"), 1.0)

                    elif market_lower.startswith("o"):
                        threshold = market[1:] if market and len(market) > 1 else "-"
                        col_name = f"over{threshold.replace('.', '')}"
                        odds = safe_float(rec_get(odds_row, col_name), 1.0)

                if threshold is None:
                    threshold = "-"

                weighted_score = compute_weighted_score(prob, confidence, odds or 1.0, market)
                expected_value = compute_expected_value(prob, odds or 1.0, confidence)
                hybrid_score = round(0.6 * weighted_score + 0.4 * expected_value, 3)
                risk_tier = "Safe" if hybrid_score >= 0.85 else "Medium" if hybrid_score >= 0.7 else "High-Risk"
                result = compute_result(status, selection, threshold, home_score, away_score)

                new_values = {
                    "home_team": home_team,
                    "away_team": away_team,
                    "odds": odds,
                    "confidence": confidence,
                    "weighted_score": weighted_score,
                    "expected_value": expected_value,
                    "hybrid_score": hybrid_score,
                    "risk_tier": risk_tier,
                    "status": status,
                    "match_time": match_time,
                    "result": result,
                }

                existing = await conn.fetchrow(
                    """
                    SELECT *
                    FROM dashboard
                    WHERE match_id = $1 AND prediction = $2 AND threshold = $3
                    """,
                    match_id,
                    selection,
                    threshold,
                )

                if not existing:
                    await conn.execute(
                        """
                        INSERT INTO dashboard (
                            match_id, home_team, away_team, prediction, threshold,
                            odds, confidence, weighted_score, expected_value,
                            hybrid_score, risk_tier, status, match_time, result, last_updated
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,CURRENT_TIMESTAMP)
                        """,
                        match_id, home_team, away_team, selection, threshold,
                        odds, confidence, weighted_score, expected_value,
                        hybrid_score, risk_tier, status, match_time, result,
                    )
                    inserted += 1
                elif rows_differ(existing, new_values):
                    await conn.execute(
                        """
                        UPDATE dashboard SET
                            home_team = $1,
                            away_team = $2,
                            odds = $3,
                            confidence = $4,
                            weighted_score = $5,
                            expected_value = $6,
                            hybrid_score = $7,
                            risk_tier = $8,
                            status = $9,
                            match_time = $10,
                            result = $11,
                            last_updated = CURRENT_TIMESTAMP
                        WHERE id = $12
                        """,
                        new_values["home_team"],
                        new_values["away_team"],
                        new_values["odds"],
                        new_values["confidence"],
                        new_values["weighted_score"],
                        new_values["expected_value"],
                        new_values["hybrid_score"],
                        new_values["risk_tier"],
                        new_values["status"],
                        new_values["match_time"],
                        new_values["result"],
                        rec_get(existing, "id"),
                    )
                    updated += 1
                else:
                    skipped += 1

            except Exception as e:
                errors += 1
                print(f"❌ Error on match_id={match_id}: {e}")
                continue

        # Sync existing dashboard rows with latest match results
        dash_rows = await conn.fetch("SELECT * FROM dashboard")
        for row in dash_rows:
            try:
                match_id = rec_get(row, "match_id")
                match = await conn.fetchrow(
                    "SELECT status, home_score, away_score FROM matches WHERE id = $1",
                    match_id,
                )
                if not match:
                    continue

                new_status = rec_get(match, "status")
                home_score = rec_get(match, "home_score") or 0
                away_score = rec_get(match, "away_score") or 0
                new_result = compute_result(
                    new_status,
                    rec_get(row, "prediction"),
                    rec_get(row, "threshold"),
                    home_score,
                    away_score,
                )

                if new_status != rec_get(row, "status") or new_result != rec_get(row, "result"):
                    await conn.execute(
                        """
                        UPDATE dashboard
                        SET status = $1,
                            result = $2,
                            last_updated = CURRENT_TIMESTAMP
                        WHERE id = $3
                        """,
                        new_status,
                        new_result,
                        rec_get(row, "id"),
                    )
                    updated += 1
            except Exception:
                continue

        await deduplicate_over_markets(conn)
        await keep_top_tip_per_match(conn)

        total = await conn.fetchval("SELECT COUNT(*) FROM dashboard")

        print(f"Dashboard total rows: {total}")
        print(f"Rows inserted: {inserted}")
        print(f"Rows updated: {updated}")
        print(f"Rows skipped: {skipped}")
        print(f"Errors: {errors}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
