SET search_path TO henry_schema;

-- 🔥 FULL RESET (FAST)
TRUNCATE TABLE 
    virtual_odds,
    virtual_events,
    virtual_fixtures,
    virtual_bets
RESTART IDENTITY CASCADE;

-- 🧹 CLEAN OLD DATA (14 DAYS)
DELETE FROM bet_selection
WHERE created < NOW() - INTERVAL '14 days';

DELETE FROM bet_slip
WHERE created < NOW() - INTERVAL '14 days';

DELETE FROM bet
WHERE created < NOW() - INTERVAL '14 days';

DELETE FROM transaction
WHERE created < NOW() - INTERVAL '14 days';

DELETE FROM transactions
WHERE created_at < NOW() - INTERVAL '14 days';
