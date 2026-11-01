# Iteration 13 (report iteration_8): gap coverage — full plugin catalogue, c12_tf validation, confirm12 min range, bot GET shape
# Run: set -a; . /app/backend/.env; . /app/frontend/.env; set +a; EXPO_BACKEND_URL=$EXPO_PUBLIC_BACKEND_URL pytest -n 0 tests/test_iter13_review.py
import os

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"
NEW_PLUGINS = ["pullback", "supertrend", "stoch_rsi", "adx", "donchian", "fvg", "sweep", "choch", "ote", "breaker",
               "eq_liquidity", "sweep_choch", "killzone", "ichimoku", "vwap", "psar", "williams_r", "cci", "keltner",
               "pin_bar", "engulfing", "inside_bar"]


def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    db = mdb()
    bot_bak = db.bots.find_one({"user_id": UID}, {"_id": 0})
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    if bot_bak:
        bot_bak["enabled"] = False
        db.bots.replace_one({"user_id": UID}, bot_bak, upsert=True)


def bot_body(s, **patch):
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    body = {k: v for k, v in b.items() if k not in ("user_id", "last_bar", "fixes", "fix_ts", "last_run", "updated_at")}
    body.update({"enabled": False, **patch})
    return body


# --- plugins catalogue: all new plugins (incl. 5 extra SMC) with meta
class TestPluginCatalogue:
    def test_all_new_plugins_present_with_meta(self, s):
        d = s.get(f"{BASE_URL}/api/plugins").json()
        blob = str(d)
        missing = [k for k in NEW_PLUGINS if f"'{k}'" not in blob]
        assert not missing, f"missing plugins: {missing}"

    def test_plugin_toggle_persists(self, s):
        d = s.get(f"{BASE_URL}/api/plugins").json()
        plugins = d.get("plugins", d)
        assert "killzone" in plugins
        cur = plugins["killzone"].get("enabled", True)
        # PUT replaces the whole map -> send full plugins dict
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": {**plugins, "killzone": {**plugins["killzone"], "enabled": not cur}}})
        assert r.status_code == 200, r.text
        d2 = s.get(f"{BASE_URL}/api/plugins").json()
        assert d2["plugins"]["killzone"]["enabled"] == (not cur)
        assert d2["plugins"]["smc"] == plugins["smc"]  # others untouched
        s.put(f"{BASE_URL}/api/plugins", json={"plugins": plugins})


# --- c12_tf must be a valid TF and not 1m-3m (chooser excludes them; bug fix aim)
class TestC12TfValidation:
    def test_c12_tf_garbage_rejected(self, s):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf="xyz"))
        assert r.status_code in (400, 422), f"c12_tf='xyz' accepted: {r.status_code}"

    @pytest.mark.parametrize("tf", ["1m", "2m", "3m"])
    def test_c12_tf_small_rejected(self, s, tf):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf=tf))
        assert r.status_code in (400, 422), f"c12_tf={tf} accepted: {r.status_code}"

    def test_c12_tf_4h_ok(self, s):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_body(s, c12_tf="4h"))
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["c12_tf"] == "4h"


# --- confirm12 endpoint: min within 6..12
class TestConfirm12Min:
    @pytest.mark.parametrize("m", [0, 13])
    def test_min_out_of_range(self, s, m):
        r = s.get(f"{BASE_URL}/api/confirm12?symbol=BTC-USD&tf=1h&min={m}", timeout=90)
        assert r.status_code in (400, 422), f"min={m} accepted: {r.status_code}"

    def test_twelve_checks(self, s):
        d = s.get(f"{BASE_URL}/api/confirm12?symbol=BTC-USD&tf=1h&min=10", timeout=90).json()
        assert len(d["checks"]) == 12 and d["up"] + d["down"] <= 12
        assert d["signal"] in (None, "BUY", "SELL")
