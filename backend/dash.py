#!/usr/bin/env python3

import asyncio
import asyncpg
from datetime import datetime, UTC
from decimal import Decimal

from config2 import DATABASE_URL, DB_SCHEMA


# ============================================================
# DATABASE URL
# ============================================================

ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql+psycopg://",
    "postgresql://",
    1,
)


# ============================================================
# HELPERS
# ============================================================

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

    numeric_cols = {
        "odds",
        "weighted_score",
        "expected_value",
        "hybrid_score",
    }

    for key, new_value in new_values.items():

        old_value = rec_get(existing, key)

        if key in numeric_cols:

            if not eq_fuzzy(old_value, new_value):
                return True

        else:

            old_value = ensure_utc_naive(old_value)
            new_value = ensure_utc_naive(new_value)

            if (
                old_value is None
                and new_value in (None, "", "-")
            ):
                continue

            if (
                new_value is None
                and old_value in (None, "", "-")
            ):
                continue

            if old_value != new_value:
                return True

    return False


# ============================================================
# SCORING
# ============================================================

def compute_weighted_score(
    prob,
    conf_label,
    odds,
    market_type,
):

    conf_map = {
        "High": 3,
        "Medium": 2,
        "Low": 1,
    }

    conf_val = conf_map.get(conf_label, 2)

    market = (market_type or "").strip().lower()

    if market in (
        "3-way",
        "3way",
        "home",
        "draw",
        "away",
    ):
        market_weight = 1.0

    elif market == "btts":
        market_weight = 1.1

    elif market.startswith("o"):
        market_weight = 1.05

    else:
        market_weight = 1.0

    base_score = (
        (prob or 0) * 0.6
        + (conf_val / 3) * 0.3
    )

    weighted_score = (
        base_score * market_weight
        + (odds or 1.0) / 10
    )

    return round(weighted_score, 3)


def compute_expected_value(
    prob,
    odds,
    conf_label,
):

    conf_order = {
        "High": 0.3,
        "Medium": 0.2,
        "Low": 0.1,
    }

    conf_adj = conf_order.get(
        conf_label,
        0.2,
    )

    prob_value = (
        prob
        if prob and 0 < prob <= 1
        else 0.5
    )

    ev = (
        prob_value * (odds - 1) + conf_adj
        if odds
        else prob_value
    )

    return round(ev, 3)


def compute_result(
    status,
    prediction,
    threshold,
    home_score,
    away_score,
):

    if (
        status is None
        or (
            isinstance(status, str)
            and status.lower() != "finished"
        )
    ):
        return "pending"

    home_score = home_score or 0
    away_score = away_score or 0

    total_goals = home_score + away_score

    selection = (prediction or "").upper()

    # --------------------------
    # 3-WAY
    # --------------------------

    if selection in (
        "HOME",
        "AWAY",
        "DRAW",
    ):

        winner = (
            "HOME"
            if home_score > away_score
            else "AWAY"
            if home_score < away_score
            else "DRAW"
        )

        return (
            "won"
            if selection == winner
            else "lost"
        )

    # --------------------------
    # BTTS
    # --------------------------

    if selection in ("YES", "NO"):

        both = (
            home_score > 0
            and away_score > 0
        )

        if (
            selection == "YES"
            and both
        ) or (
            selection == "NO"
            and not both
        ):
            return "won"

        return "lost"

    # --------------------------
    # OVER
    # --------------------------

    if selection == "OVER":

        try:
            threshold_value = float(threshold)

            return (
                "won"
                if total_goals > threshold_value
                else "lost"
            )

        except Exception:
            return "lost"

    return "lost"


# ============================================================
# DEDUPLICATION
# ============================================================

async def deduplicate_over_markets(conn):

    await conn.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY match_id
                    ORDER BY
                        hybrid_score DESC NULLS LAST,
                        last_updated DESC,
                        id DESC
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
                    ORDER BY
                        hybrid_score DESC NULLS LAST,
                        last_updated DESC,
                        id DESC
                ) AS rn
            FROM dashboard
        )
        DELETE FROM dashboard d
        USING ranked r
        WHERE d.id = r.id
          AND r.rn > 1
        """
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print("========================================")
    print(" DASHBOARD UPDATE STARTING")
    print("========================================")

    conn = await asyncpg.connect(
        ASYNC_DATABASE_URL
    )

    try:

        # ----------------------------------------------------
        # FORCE CORRECT SCHEMA
        # ----------------------------------------------------

        await conn.execute(
            f'SET search_path TO "{DB_SCHEMA}", public'
        )

        print(f"[DATABASE] Schema: {DB_SCHEMA}")

        # ----------------------------------------------------
        # ENSURE DASHBOARD EXISTS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ONE QUERY:
        #
        # accumulator
        # + matches
        # + bookmark
        #
        # No more 2,652 individual match queries.
        # No more 2,652 individual bookmark queries.
        # ----------------------------------------------------

        print("[FETCH] Loading accumulator + matches + bookmarks...")

        source_rows = await conn.fetch(
            """
            SELECT
                a.match_id,
                a.market,
                a.selection,
                a.probability,

                m.home_team_name,
                m.away_team_name,
                m.home_score,
                m.away_score,
                m.status,
                m."utcdate" AS match_time,

                b.home_odds,
                b.draw_odds,
                b.away_odds,
                b.gg_odds,
                b.ng_odds,
                b.over15,
                b.over25,
                b.over35

            FROM accumulator a

            INNER JOIN matches m
                ON m.id = a.match_id

            LEFT JOIN bookmark b
                ON b.match_id = a.match_id

            ORDER BY a.match_id DESC
            """
        )

        print(
            f"[FETCH] Source rows: {len(source_rows)}"
        )

        # ----------------------------------------------------
        # LOAD EXISTING DASHBOARD ONCE
        # ----------------------------------------------------

        existing_rows = await conn.fetch(
            """
            SELECT *
            FROM dashboard
            """
        )

        existing_map = {
            (
                rec_get(row, "match_id"),
                rec_get(row, "prediction"),
                rec_get(row, "threshold"),
            ): row
            for row in existing_rows
        }

        print(
            f"[FETCH] Existing dashboard rows: "
            f"{len(existing_rows)}"
        )

        # ----------------------------------------------------
        # CALCULATE EVERYTHING LOCALLY
        # ----------------------------------------------------

        dashboard_rows = []

        inserted = 0
        updated = 0
        skipped = 0
        errors = 0

        for row in source_rows:

            try:

                match_id = rec_get(
                    row,
                    "match_id",
                )

                market = rec_get(
                    row,
                    "market",
                )

                selection = rec_get(
                    row,
                    "selection",
                )

                market_lower = (
                    market or ""
                ).strip().lower()

                probability = safe_float(
                    rec_get(row, "probability"),
                    0.5,
                )

                confidence = confidence_label(
                    probability,
                    market,
                )

                home_team = rec_get(
                    row,
                    "home_team_name",
                )

                away_team = rec_get(
                    row,
                    "away_team_name",
                )

                status = rec_get(
                    row,
                    "status",
                )

                match_time = ensure_utc_naive(
                    rec_get(
                        row,
                        "match_time",
                    )
                )

                home_score = (
                    rec_get(row, "home_score")
                    or 0
                )

                away_score = (
                    rec_get(row, "away_score")
                    or 0
                )

                odds = None
                threshold = "-"

                # ------------------------------------------------
                # 3-WAY
                # ------------------------------------------------

                if market_lower == "3-way":

                    selection_upper = (
                        selection or ""
                    ).upper()

                    if selection_upper == "HOME":

                        odds = safe_float(
                            rec_get(
                                row,
                                "home_odds",
                            ),
                            1.0,
                        )

                    elif selection_upper == "DRAW":

                        odds = safe_float(
                            rec_get(
                                row,
                                "draw_odds",
                            ),
                            1.0,
                        )

                    elif selection_upper == "AWAY":

                        odds = safe_float(
                            rec_get(
                                row,
                                "away_odds",
                            ),
                            1.0,
                        )

                # ------------------------------------------------
                # BTTS
                # ------------------------------------------------

                elif market_lower == "btts":

                    selection_upper = (
                        selection or ""
                    ).upper()

                    if selection_upper == "YES":

                        odds = safe_float(
                            rec_get(
                                row,
                                "gg_odds",
                            ),
                            1.0,
                        )

                    else:

                        odds = safe_float(
                            rec_get(
                                row,
                                "ng_odds",
                            ),
                            1.0,
                        )

                # ------------------------------------------------
                # OVER
                # ------------------------------------------------

                elif market_lower.startswith("o"):

                    threshold = (
                        market[1:]
                        if market
                        and len(market) > 1
                        else "-"
                    )

                    over_map = {
                        "1.5": "over15",
                        "2.5": "over25",
                        "3.5": "over35"
                    }

                    odds_column = over_map.get(
                        threshold
                    )

                    if odds_column:

                        odds = safe_float(
                            rec_get(
                                row,
                                odds_column,
                            ),
                            1.0,
                        )

                # ------------------------------------------------
                # SCORES
                # ------------------------------------------------

                weighted_score = compute_weighted_score(
                    probability,
                    confidence,
                    odds or 1.0,
                    market,
                )

                expected_value = compute_expected_value(
                    probability,
                    odds or 1.0,
                    confidence,
                )

                hybrid_score = round(
                    0.6 * weighted_score
                    + 0.4 * expected_value,
                    3,
                )

                risk_tier = (
                    "Safe"
                    if hybrid_score >= 0.85
                    else "Medium"
                    if hybrid_score >= 0.7
                    else "High-Risk"
                )

                result = compute_result(
                    status,
                    selection,
                    threshold,
                    home_score,
                    away_score,
                )

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

                key = (
                    match_id,
                    selection,
                    threshold,
                )

                existing = existing_map.get(key)

                if existing is None:

                    inserted += 1

                elif rows_differ(
                    existing,
                    new_values,
                ):

                    updated += 1

                else:

                    skipped += 1

                dashboard_rows.append(
                    (
                        match_id,
                        home_team,
                        away_team,
                        selection,
                        threshold,
                        odds,
                        confidence,
                        weighted_score,
                        expected_value,
                        hybrid_score,
                        risk_tier,
                        status,
                        match_time,
                        result,
                    )
                )

            except Exception as exc:

                errors += 1

                print(
                    f"❌ Error processing "
                    f"match_id={rec_get(row, 'match_id')}: "
                    f"{exc}"
                )

        print(
            f"[CALCULATE] Rows prepared: "
            f"{len(dashboard_rows)}"
        )

        # ----------------------------------------------------
        # BULK LOAD INTO STAGING TABLE
        # ----------------------------------------------------

        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{DB_SCHEMA}".dashboard_stage (
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
                result TEXT
            )
            """
        )

        await conn.execute(
            f'TRUNCATE TABLE "{DB_SCHEMA}".dashboard_stage'
        )

        if dashboard_rows:

            await conn.copy_records_to_table(
                  "dashboard_stage",
                records=dashboard_rows,
                schema_name=DB_SCHEMA,
                columns=[
                    "match_id",
                    "home_team",
                    "away_team",
                    "prediction",
                    "threshold",
                    "odds",
                    "confidence",
                    "weighted_score",
                    "expected_value",
                    "hybrid_score",
                    "risk_tier",
                    "status",
                    "match_time",
                    "result",
                ],
            )

        print(
            "[DATABASE] Bulk staging complete."
        )
        # ----------------------------------------------------
        # ONE UPSERT
        # ----------------------------------------------------

        await conn.execute(
            """
            INSERT INTO dashboard (
                match_id,
                home_team,
                away_team,
                prediction,
                threshold,
                odds,
                confidence,
                weighted_score,
                expected_value,
                hybrid_score,
                risk_tier,
                status,
                match_time,
                result,
                last_updated
            )

            SELECT
                match_id,
                home_team,
                away_team,
                prediction,
                threshold,
                odds,
                confidence,
                weighted_score,
                expected_value,
                hybrid_score,
                risk_tier,
                status,
                match_time,
                result,
                CURRENT_TIMESTAMP

            FROM dashboard_stage

            ON CONFLICT (
                match_id,
                prediction,
                threshold
            )

            DO UPDATE SET

                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                odds = EXCLUDED.odds,
                confidence = EXCLUDED.confidence,
                weighted_score = EXCLUDED.weighted_score,
                expected_value = EXCLUDED.expected_value,
                hybrid_score = EXCLUDED.hybrid_score,
                risk_tier = EXCLUDED.risk_tier,
                status = EXCLUDED.status,
                match_time = EXCLUDED.match_time,
                result = EXCLUDED.result,
                last_updated = CURRENT_TIMESTAMP

            WHERE
                dashboard.home_team IS DISTINCT FROM EXCLUDED.home_team
                OR dashboard.away_team IS DISTINCT FROM EXCLUDED.away_team
                OR dashboard.odds IS DISTINCT FROM EXCLUDED.odds
                OR dashboard.confidence IS DISTINCT FROM EXCLUDED.confidence
                OR dashboard.weighted_score IS DISTINCT FROM EXCLUDED.weighted_score
                OR dashboard.expected_value IS DISTINCT FROM EXCLUDED.expected_value
                OR dashboard.hybrid_score IS DISTINCT FROM EXCLUDED.hybrid_score
                OR dashboard.risk_tier IS DISTINCT FROM EXCLUDED.risk_tier
                OR dashboard.status IS DISTINCT FROM EXCLUDED.status
                OR dashboard.match_time IS DISTINCT FROM EXCLUDED.match_time
                OR dashboard.result IS DISTINCT FROM EXCLUDED.result
            """
        )

        print(
            "[DATABASE] Bulk dashboard upsert complete."
        )

        # ----------------------------------------------------
        # SYNC RESULTS IN ONE QUERY
        # ----------------------------------------------------

        await conn.execute(
            """
            UPDATE dashboard d

            SET
                status = m.status,
                result =
                    CASE

                        WHEN LOWER(m.status) != 'finished'
                        THEN 'pending'

                        WHEN UPPER(d.prediction)
                            IN ('HOME', 'AWAY', 'DRAW')

                        THEN
                            CASE
                                WHEN UPPER(d.prediction) = 'HOME'
                                     AND m.home_score > m.away_score
                                THEN 'won'

                                WHEN UPPER(d.prediction) = 'AWAY'
                                     AND m.away_score > m.home_score
                                THEN 'won'

                                WHEN UPPER(d.prediction) = 'DRAW'
                                     AND m.home_score = m.away_score
                                THEN 'won'

                                ELSE 'lost'
                            END

                        WHEN UPPER(d.prediction) = 'YES'
                        THEN
                            CASE
                                WHEN m.home_score > 0
                                 AND m.away_score > 0
                                THEN 'won'
                                ELSE 'lost'
                            END

                        WHEN UPPER(d.prediction) = 'NO'
                        THEN
                            CASE
                                WHEN m.home_score = 0
                                  OR m.away_score = 0
                                THEN 'won'
                                ELSE 'lost'
                            END

                        WHEN UPPER(d.prediction) = 'OVER'
                        THEN
                            CASE
                                WHEN (
                                    m.home_score
                                    + m.away_score
                                ) > NULLIF(d.threshold, '-')::DOUBLE PRECISION
                                THEN 'won'
                                ELSE 'lost'
                            END

                        ELSE 'lost'

                    END,

                last_updated = CURRENT_TIMESTAMP

            FROM matches m

            WHERE m.id = d.match_id
              AND (
                    d.status IS DISTINCT FROM m.status
                    OR d.result IS DISTINCT FROM
                        CASE

                            WHEN LOWER(m.status) != 'finished'
                            THEN 'pending'

                            WHEN UPPER(d.prediction) = 'HOME'
                            THEN
                                CASE
                                    WHEN m.home_score > m.away_score
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            WHEN UPPER(d.prediction) = 'AWAY'
                            THEN
                                CASE
                                    WHEN m.away_score > m.home_score
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            WHEN UPPER(d.prediction) = 'DRAW'
                            THEN
                                CASE
                                    WHEN m.home_score = m.away_score
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            WHEN UPPER(d.prediction) = 'YES'
                            THEN
                                CASE
                                    WHEN m.home_score > 0
                                     AND m.away_score > 0
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            WHEN UPPER(d.prediction) = 'NO'
                            THEN
                                CASE
                                    WHEN m.home_score = 0
                                      OR m.away_score = 0
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            WHEN UPPER(d.prediction) = 'OVER'
                            THEN
                                CASE
                                    WHEN (
                                        m.home_score
                                        + m.away_score
                                    ) > NULLIF(d.threshold, '-')::DOUBLE PRECISION
                                    THEN 'won'
                                    ELSE 'lost'
                                END

                            ELSE 'lost'

                        END
                )
            """
        )

        # ----------------------------------------------------
        # DEDUPLICATION
        # ----------------------------------------------------

        await deduplicate_over_markets(conn)

        await keep_top_tip_per_match(conn)

        # ----------------------------------------------------
        # FINAL COUNT
        # ----------------------------------------------------

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM dashboard"
        )

        print("")
        print("========================================")
        print(" DASHBOARD UPDATE COMPLETE")
        print("========================================")
        print(f"Dashboard total rows: {total}")
        print(f"Rows inserted:       {inserted}")
        print(f"Rows changed:        {updated}")
        print(f"Rows unchanged:      {skipped}")
        print(f"Errors:              {errors}")
        print("========================================")

    finally:

        await conn.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
