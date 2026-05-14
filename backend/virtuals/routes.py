# routes.py
import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from virtuals.config_settings import SCHEMA,STATUS_FINISHED
from virtuals.config import db, logger, redis_client
from virtuals.model import Fixture, Event
from virtuals.utils import now_utc, to_utc, compute_match_status, _match_to_dict

bp = Blueprint("routes", __name__)

# ---------------- Constants ----------------
ROUND_INTERVAL = 120
MATCHES_PER_ROUND = 10
TOTAL_ROUNDS = 38
SCHEDULED_ROUNDS = 6

MAX_SELECTIONS_PER_TICKET = 20
MAX_STAKE = 1001
MAX_WIN = 100000

ALLOWED_SELECTIONS = [
    "home",
    "draw",
    "away",
    "over15",
    "under15",
    "over25",
    "under25",
    "btts_yes",
    "btts_no",
]


def table_name(name: str) -> str:
    return f"{SCHEMA}.{name}" if SCHEMA else name


T_FIXTURES = table_name("virtual_fixtures")
T_ODDS = table_name("virtual_odds")
T_EVENTS = table_name("virtual_events")
T_VBETS = table_name("virtual_bets")
T_USER = table_name("user")
T_TRANSACTIONS = table_name("transactions")
T_BAL_HISTORY = table_name("balance_history")


def _active_matches_for_round(round_id: int):
    """Return only non-finished matches for a round."""
    matches = Fixture.query.filter_by(round=round_id).order_by(Fixture.id).all()
    return [m for m in matches if compute_match_status(m) != "FINISHED"]


def _round_status_from_matches(matches):
    """Derive round status from non-finished matches only."""
    if not matches:
        return None

    statuses = [compute_match_status(m) for m in matches]

    if any(s == "RUNNING" for s in statuses):
        return "RUNNING"
    if any(s == "OPEN" for s in statuses):
        return "OPEN"
    return "SCHEDULED"


# ---------------- API endpoints ----------------
@bp.route("/")
def home():
    return {
        "engine": "Virtual PRO+ (production-hardened)",
        "status": "running",
        "round_interval_seconds": ROUND_INTERVAL,
        "matches_per_round": MATCHES_PER_ROUND,
        "total_rounds": TOTAL_ROUNDS,
        "scheduled_rounds_kept": SCHEDULED_ROUNDS,
    }


@bp.route("/bet", methods=["POST"])
@jwt_required()
def place_virtual_bet():
    data = request.json or {}
    user_id = int(get_jwt_identity())

    selections = data.get("selections")
    if selections is None:
        match_id = data.get("match_id")
        selection = data.get("selection")
        stake_val = data.get("stake")

        if match_id is None or selection is None or stake_val is None:
            return jsonify({
                "success": False,
                "error": "match_id, selection and stake required"
            }), 400

        selections = [{
            "match_id": int(match_id),
            "selection": str(selection).lower(),
        }]

    if not isinstance(selections, list) or not selections:
        return jsonify({"success": False, "error": "Selections must be a non-empty list"}), 400

    if len(selections) > MAX_SELECTIONS_PER_TICKET:
        return jsonify({
            "success": False,
            "error": f"Max {MAX_SELECTIONS_PER_TICKET} selections allowed"
        }), 400

    try:
        stake = float(data.get("stake"))
    except Exception:
        return jsonify({"success": False, "error": "Invalid stake"}), 400

    if stake <= 0 or stake > MAX_STAKE:
        return jsonify({
            "success": False,
            "error": f"Stake must be >0 and <= {MAX_STAKE}"
        }), 400

    try:
        with Session(bind=db.engine) as session:
            with session.begin():
                user_row = session.execute(
                    text(f"SELECT id, balance FROM {T_USER} WHERE id = :uid FOR UPDATE"),
                    {"uid": user_id},
                ).fetchone()

                if not user_row:
                    return jsonify({"success": False, "error": "User not found"}), 404

                balance = float(user_row.balance or 0.0)
                if balance < stake:
                    return jsonify({"success": False, "error": "Insufficient balance"}), 400

                total_odds = 1.0
                seen_matches = set()
                odds_map = {}

                for sel in selections:
                    mid = int(sel.get("match_id"))
                    choice = str(sel.get("selection")).lower()

                    if mid in seen_matches:
                        raise ValueError(f"Duplicate match {mid}")
                    seen_matches.add(mid)

                    if choice not in ALLOWED_SELECTIONS:
                        raise ValueError(f"Invalid selection {choice}")

                    mrow = session.execute(
                        text(f"""
                            SELECT id, start_time, open_time
                            FROM {T_FIXTURES}
                            WHERE id = :mid
                            FOR UPDATE
                        """),
                        {"mid": mid},
                    ).fetchone()

                    if not mrow:
                        raise ValueError(f"Match {mid} not found")

                    class Tmp:
                        pass

                    tmp = Tmp()
                    tmp.open_time = mrow.open_time
                    tmp.start_time = mrow.start_time
                    tmp.end_time = None

                    # Allow betting on OPEN and SCHEDULED matches
                    status = compute_match_status(tmp)
                    if status not in ("OPEN", "SCHEDULED"):
                        raise ValueError(
                            f"Match {mid} not available for betting (must be OPEN or SCHEDULED)"
                        )

                    existing = session.execute(
                        text(f"""
                            SELECT 1
                            FROM {T_VBETS}
                            WHERE user_id = :uid
                              AND match_id = :mid
                              AND status = 'OPEN'
                            LIMIT 1
                            FOR UPDATE
                        """),
                        {"uid": user_id, "mid": mid},
                    ).fetchone()

                    if existing:
                        raise ValueError(f"Already have open bet on match {mid}")

                    odds_row = session.execute(
                        text(f"""
                            SELECT home, draw, away, over15, under15, over25, under25, btts_yes, btts_no
                            FROM {T_ODDS}
                            WHERE match_id = :mid
                            ORDER BY created_at DESC
                            LIMIT 1
                        """),
                        {"mid": mid},
                    ).fetchone()

                    if not odds_row:
                        raise ValueError(f"No odds for match {mid}")

                    sel_map = {
                        "home": odds_row.home,
                        "draw": odds_row.draw,
                        "away": odds_row.away,
                        "over15": odds_row.over15,
                        "under15": odds_row.under15,
                        "over25": odds_row.over25,
                        "under25": odds_row.under25,
                        "btts_yes": odds_row.btts_yes,
                        "btts_no": odds_row.btts_no,
                    }

                    sel_odds = sel_map.get(choice)
                    if sel_odds is None:
                        raise ValueError(f"No odds for {choice} on match {mid}")

                    odds_map[mid] = float(sel_odds)
                    total_odds *= float(sel_odds)

                new_balance = round(balance - stake, 2)
                ts_dt = now_utc()
                ts = ts_dt.isoformat()

                # One ticket ID shared by all selections in this accumulator ticket
                ticket_id = f"vb-{user_id}-{int(ts_dt.timestamp())}"

                session.execute(
                    text(f"UPDATE {T_USER} SET balance = :bal WHERE id = :uid"),
                    {"bal": new_balance, "uid": user_id},
                )

                for sel in selections:
                    mid = int(sel["match_id"])
                    choice = sel["selection"]
                    odd = odds_map[mid]

                    session.execute(
                        text(f"""
                            INSERT INTO {T_VBETS}
                            (ticket_id, user_id, match_id, selection, stake, odds, status, created_at)
                            VALUES (:tid, :uid, :mid, :sel, :stk, :od, 'OPEN', :ts)
                        """),
                        {
                            "tid": ticket_id,
                            "uid": user_id,
                            "mid": mid,
                            "sel": choice,
                            "stk": stake,
                            "od": odd,
                            "ts": ts,
                        },
                    )

                    try:
                        redis_client.incrbyfloat(f"virtual:exposure:{mid}:{choice}", stake)
                    except Exception:
                        logger.exception("Redis exposure failed")

                session.execute(
                    text(f"""
                        INSERT INTO {T_TRANSACTIONS}
                        (user_id, type, amount, created_at)
                        VALUES (:uid, 'Withdraw', :amt, :ts)
                    """),
                    {"uid": user_id, "amt": stake, "ts": ts},
                )

                session.execute(
                    text(f"""
                        INSERT INTO {T_BAL_HISTORY}
                        (user_id, balance, created_at)
                        VALUES (:uid, :bal, :ts)
                    """),
                    {"uid": user_id, "bal": new_balance, "ts": ts},
                )

                potential_win = min(MAX_WIN, round(stake * total_odds, 2))

                return jsonify({
                    "success": True,
                    "ticket_id": ticket_id,
                    "potential_win": potential_win,
                    "total_odds": total_odds,
                    "balance": new_balance,
                })

    except ValueError as e:
        logger.warning("Validation error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Bet placement failed")
        return jsonify({
            "success": False,
            "error": "Internal error",
            "detail": str(e),
        }), 500


@bp.route("/bets", methods=["GET"])
@jwt_required()
def my_virtual_bets():
    user_id = int(get_jwt_identity())

    try:
        rows = db.session.execute(
            text(f"""
                SELECT id, ticket_id, match_id, selection, stake, odds, status, created_at
                FROM {T_VBETS}
                WHERE user_id = :uid
                ORDER BY created_at DESC, id DESC
                LIMIT 500
            """),
            {"uid": user_id},
        ).fetchall()
    except Exception:
        return jsonify([])

    tickets_map = {}

    for row in rows:
        bet_id = int(row[0])
        ticket_id = row[1]
        match_id = int(row[2])
        selection = row[3]
        stake = float(row[4])
        odds = float(row[5])
        status = row[6]
        created_at = row[7]

        if not ticket_id:
            ticket_id = f"vb-{user_id}-{bet_id}"

        if ticket_id not in tickets_map:
            tickets_map[ticket_id] = {
                "ticket_id": ticket_id,
                "stake": stake,
                "created_at": created_at,
                "selections": [],
            }

        match_row = db.session.execute(
            text(f"""
                SELECT home, away, home_score, away_score, status
                FROM {T_FIXTURES}
                WHERE id = :mid
            """),
            {"mid": match_id},
        ).fetchone()

        tickets_map[ticket_id]["selections"].append({
            "bet_id": bet_id,
            "match_id": match_id,
            "home_team": match_row[0] if match_row else None,
            "away_team": match_row[1] if match_row else None,
            "home_score": match_row[2] if match_row else None,
            "away_score": match_row[3] if match_row else None,
            "match_status": match_row[4] if match_row else None,
            "selection": selection,
            "odds": odds,
            "status": status,
        })

    out = []
    for ticket in tickets_map.values():
        statuses = [s["status"] for s in ticket["selections"]]

        if all(s == "WON" for s in statuses):
            ticket["status"] = "WON"
        elif any(s == "LOST" for s in statuses):
            ticket["status"] = "LOST"
        else:
            ticket["status"] = "OPEN"

        ticket["selection_count"] = len(ticket["selections"])
        out.append(ticket)

    out.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(out)


@bp.route("/rounds")
def rounds():
    rows = db.session.query(Fixture.round)\
        .filter(Fixture.round.isnot(None))\
        .group_by(Fixture.round)\
        .order_by(func.min(Fixture.open_time)).all()

    now = now_utc()
    out = []

    for r in rows:
        round_id = int(r[0])
        matches = _active_matches_for_round(round_id)

        # Do not include rounds that are fully finished
        if not matches:
            continue

        start_times = [to_utc(m.start_time) for m in matches if m.start_time]
        end_times = [to_utc(m.end_time) for m in matches if m.end_time]
        open_times = [to_utc(m.open_time) for m in matches if m.open_time]

        round_start = min(start_times) if start_times else (min(open_times) if open_times else None)
        round_end = max(end_times) if end_times else None

        round_status = _round_status_from_matches(matches) or "SCHEDULED"

        time_to_start = int((round_start - now).total_seconds()) if round_start else None
        time_to_end = int((round_end - now).total_seconds()) if round_end else None

        out.append({
            "round": round_id,
            "open_time": (min(open_times).isoformat() if open_times else None),
            "status": round_status,
            "time_to_start": time_to_start,
            "time_to_end": time_to_end,
        })

    out.sort(key=lambda x: x.get("round", 0))
    return jsonify(out)


@bp.route("/round/<int:round_id>")
def round_matches(round_id):
    matches = _active_matches_for_round(round_id)

    if not matches:
        return jsonify([])

    now = now_utc()

    start_times = [to_utc(m.start_time) for m in matches if m.start_time]
    end_times = [to_utc(m.end_time) for m in matches if m.end_time]
    open_times = [to_utc(m.open_time) for m in matches if m.open_time]

    round_start = min(start_times) if start_times else (min(open_times) if open_times else None)
    round_end = max(end_times) if end_times else None

    round_status = _round_status_from_matches(matches) or "SCHEDULED"

    round_meta = {
        "round": round_id,
        "status": round_status,
        "open_time": (min(open_times).isoformat() if open_times else None),
        "time_to_start": int((round_start - now).total_seconds()) if round_start else None,
        "time_to_end": int((round_end - now).total_seconds()) if round_end else None,
    }

    return jsonify({
        "round": round_meta,
        "matches": [_match_to_dict(x) for x in matches],
    })

@bp.route("/finished")
def finished_matches():
    fixtures = (
        Fixture.query
        .filter(Fixture.status == STATUS_FINISHED)
        .order_by(Fixture.end_time.desc())
        .limit(30)
        .all()
    )

    return jsonify([
        {
            "id": m.id,
            "home": m.home,
            "away": m.away,
            "home_score": m.home_score,
            "away_score": m.away_score,
            "start_time": m.start_time.isoformat(),
            "end_time": m.updated_at.isoformat()
        }
        for m in fixtures
    ])
@bp.route("/events/<int:match_id>", methods=["GET"])
def get_virtual_event(match_id):
    try:
        redis_key = f"virtual:events:match:{match_id}"
        recent = []

        try:
            raw = redis_client.lrange(redis_key, 0, -1)
            if raw:
                recent = [json.loads(x) for x in raw]
                recent.reverse()
        except Exception:
            logger.exception("Redis read failed for %s", redis_key)

        db_events = Event.query\
            .filter_by(match_id=match_id)\
            .order_by(Event.minute)\
            .all()

        db_list = [{
            "id": e.id,
            "minute": e.minute,
            "team": e.team,
            "type": e.type,
            "description": e.description,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in db_events]

        if recent:
            seen = set()
            merged = []

            for e in db_list:
                seen.add(e.get("id"))
                merged.append(e)

            for e in recent:
                if e.get("id") in seen:
                    continue
                merged.append(e)

            return jsonify(merged), 200

        return jsonify(db_list), 200

    except Exception as ex:
        logger.exception("Error fetching events for match %s", match_id)
        return jsonify({
            "error": "Internal server error",
            "detail": str(ex),
        }), 500

@bp.route("/table")
def league_table():
    season_id = request.args.get("season_id", type=int)

    # If not provided, use latest completed season
    if not season_id:
        latest = (
            db.session.query(Fixture.season)
            .filter(Fixture.status == "FINISHED")
            .order_by(Fixture.season.desc())
            .first()
        )

        if not latest:
            return jsonify({"season_id": None, "table": []})

        season_id = latest[0]

    #  Fetch fixtures for THAT season
    fixtures = (
        Fixture.query
        .filter(
            Fixture.status == "FINISHED",
            Fixture.season == season_id
        )
        .order_by(Fixture.end_time.asc())
        .all()
    )

    table = {}

    for f in fixtures:
        home = f.home
        away = f.away

        h = int(f.home_score or 0)
        a = int(f.away_score or 0)

        # Init teams
        for team in [home, away]:
            if team not in table:
                table[team] = {
                    "team": team,
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "gf": 0,
                    "ga": 0,
                    "points": 0,
                    "form": []
                }

        # Played
        table[home]["played"] += 1
        table[away]["played"] += 1

        # Goals
        table[home]["gf"] += h
        table[home]["ga"] += a

        table[away]["gf"] += a
        table[away]["ga"] += h

        # Result
        if h > a:
            table[home]["wins"] += 1
            table[home]["points"] += 3
            table[away]["losses"] += 1

            table[home]["form"].append("W")
            table[away]["form"].append("L")

        elif a > h:
            table[away]["wins"] += 1
            table[away]["points"] += 3
            table[home]["losses"] += 1

            table[away]["form"].append("W")
            table[home]["form"].append("L")

        else:
            table[home]["draws"] += 1
            table[away]["draws"] += 1
            table[home]["points"] += 1
            table[away]["points"] += 1

            table[home]["form"].append("D")
            table[away]["form"].append("D")

    # Keep last 5 form
    for team in table.values():
        team["form"] = team["form"][-5:]

    standings = list(table.values())

    standings.sort(
        key=lambda x: (x["points"], x["gf"] - x["ga"], x["gf"]),
        reverse=True,
    )

    for i, team in enumerate(standings, start=1):
        team["rank"] = i
        team["goal_difference"] = team["gf"] - team["ga"]

    return jsonify({
        "season_id": season_id,
        "table": standings
    })
