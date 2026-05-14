# settlement.py
import logging
from sqlalchemy import func, text
from virtuals.config import db, app
from virtuals.utils import safe_commit, match_lock
from virtuals.model import Fixture, VirtualBet
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("settlement")
from virtuals.config_settings import SCHEMA

# ---------------- Helper ----------------
def table(name: str) -> str:
    return f"{SCHEMA}.{name}" if SCHEMA else name


def is_win(selection: str, home: int, away: int) -> bool:
    total = home + away
    sel = (selection or "").lower()

    return {
        "home": home > away,
        "away": away > home,
        "draw": home == away,
        "over25": total > 2,
        "under25": total < 3,
        "btts_yes": home > 0 and away > 0,
        "btts_no": home == 0 or away == 0,
        "over15": total > 1,
        "under15": total < 2,
        "over35": total > 3,
        "under35": total < 4,
    }.get(sel, False)


# ---------------- Executor ----------------
settlement_executor = ThreadPoolExecutor(max_workers=8)


def settle_virtual_bets_async(match_id: int):
    """Public async entrypoint"""
    settlement_executor.submit(_settle_virtual_bets, match_id)


# ---------------- Core Settlement ----------------
def _settle_virtual_bets(match_id: int) -> int:
    try:
        with app.app_context():
            session = db.session

            with match_lock(match_id):
                match = (
                    session.query(Fixture)
                    .filter(Fixture.id == match_id)
                    .with_for_update()
                    .first()
                )

                if not match:
                    logger.warning("Match not found: %s", match_id)
                    return 0

                if (match.status or "").upper() != "FINISHED":
                    return 0

                if getattr(match, "is_settled", False):
                    logger.debug("Already settled: %s", match_id)
                    return 0

                home_score = int(match.home_score or 0)
                away_score = int(match.away_score or 0)

                # Fetch OPEN bets (locked)
                open_bets = (
                    session.query(VirtualBet)
                    .filter(
                        VirtualBet.match_id == match_id,
                        func.upper(VirtualBet.status) == "OPEN",
                    )
                    .with_for_update()
                    .all()
                )

                if not open_bets:
                    match.is_settled = True
                    session.add(match)
                    safe_commit(session)
                    return 0

                logger.info("Settling %d bets for match %s", len(open_bets), match_id)

                # Group by ticket
                tickets = {}
                for vb in open_bets:
                    if vb.ticket_id:
                        tickets.setdefault(vb.ticket_id, []).append(vb)

                user_table = table("user")
                txn_table = table("transaction")

                # Lock all involved users upfront
                user_ids = list({vb.user_id for vb in open_bets})

                user_balances = {}
                if user_ids:
                    rows = session.execute(
                        text(f"""
                            SELECT id, balance 
                            FROM {user_table}
                            WHERE id = ANY(:uids)
                            FOR UPDATE
                        """),
                        {"uids": user_ids},
                    ).fetchall()

                    user_balances = {
                        row[0]: float(row[1] or 0)
                        for row in rows
                    }

                processed = 0

                # ---- PROCESS EACH TICKET ----
                for ticket_id, ticket_bets in tickets.items():
                    user_id = ticket_bets[0].user_id
                    stake = float(ticket_bets[0].stake or 0)

                    # Resolve bets for this match
                    for vb in ticket_bets:
                        vb.status = (
                            "WON" if is_win(vb.selection, home_score, away_score)
                            else "LOST"
                        )
                        session.add(vb)

                    # Check entire ticket (all matches)
                    full_ticket = (
                        session.query(VirtualBet)
                        .filter(VirtualBet.ticket_id == ticket_id)
                        .all()
                    )

                    # Skip if still pending matches
                    if any((b.status or "").upper() == "OPEN" for b in full_ticket):
                        processed += len(ticket_bets)
                        continue

                    # Determine win
                    all_win = all((b.status or "").upper() == "WON" for b in full_ticket)

                    if all_win:
                        total_odds = 1.0
                        for b in full_ticket:
                            total_odds *= float(b.odds or 1)

                        payout = round(stake * total_odds, 2)

                        current_balance = user_balances.get(user_id, 0)
                        new_balance = round(current_balance + payout, 2)

                        # Update balance
                        session.execute(
                            text(f"""
                                UPDATE {user_table}
                                SET balance = :bal
                                WHERE id = :uid
                            """),
                            {"bal": new_balance, "uid": user_id},
                        )

                        # Insert transaction
                        session.execute(
                            text(f"""
                                INSERT INTO {txn_table}
                                (user_id, amount, type, balance_after, created)
                                VALUES (:uid, :amount, 'WIN', :bal, NOW())
                            """),
                            {
                                "uid": user_id,
                                "amount": payout,
                                "bal": new_balance,
                            },
                        )

                        user_balances[user_id] = new_balance

                        logger.info(
                            "✅ Ticket %s WON | user=%s | payout=%.2f",
                            ticket_id, user_id, payout
                        )
                    else:
                        logger.info("❌ Ticket %s LOST", ticket_id)

                    processed += len(ticket_bets)

                # Mark match settled (CRITICAL)
                match.is_settled = True
                session.add(match)

                safe_commit(session)

                logger.info("🏁 Settlement complete: %d bets", processed)
                return processed

    except Exception:
        logger.exception("[settle_task] Failed for match %s", match_id)
        raise


# alias
settle_virtual_bets = _settle_virtual_bets
