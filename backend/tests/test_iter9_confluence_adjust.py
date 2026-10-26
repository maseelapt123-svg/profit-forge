# Iteration 9: new main-bot plugins, weighted confluence strategy, AI daily adjustments (generate + apply)
import json
import os
import sys
from datetime import datetime, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import manual_seed_adjust as seedmod  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NEW = ["pullback", "supertrend", "stoch_rsi", "adx", "donchian"]
FAKE_DATE = "2001-01-01"


@pytest.fixture(scope="module")
def s():
    seedmod.backup()
    seedmod.seed()
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    seedmod.db().daily_summaries.delete_many({"user_id": seedmod.UID, "date": FAKE_DATE})
    seedmod.clean()
    seedmod.restore()


# --- plugins meta + save/validation
class TestPlugins:
    def test_meta_has_new_plugins(self, s):
        d = s.get(f"{BASE_URL}/api/plugins").json()
        for k in NEW:
            assert k in d["meta"] and d["meta"][k]["label"], k
            assert k in d["plugins"]

    def test_save_new_plugin_params(self, s):
        cur = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        cur["supertrend"].update({"enabled": True, "atr_len": 12, "st_mult": 2.5})
        cur["adx"].update({"enabled": True, "threshold": 25})
        cur["donchian"].update({"enabled": True, "length": 30})
        cur["pullback"].update({"enabled": True, "ema": 20, "trend": 60})
        cur["stoch_rsi"].update({"enabled": True, "lvl": 15})
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": cur})
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        assert g["supertrend"]["enabled"] and g["supertrend"]["st_mult"] == 2.5 and g["supertrend"]["atr_len"] == 12
        assert g["adx"]["threshold"] == 25 and g["donchian"]["length"] == 30 and g["pullback"]["trend"] == 60
        assert g["stoch_rsi"]["lvl"] == 15

    @pytest.mark.parametrize("k,p,v", [("supertrend", "st_mult", 10), ("adx", "threshold", 5), ("stoch_rsi", "lvl", 60),
                                       ("pullback", "ema", 1), ("supertrend", "atr_len", 100)])
    def test_range_validation(self, s, k, p, v):
        cur = s.get(f"{BASE_URL}/api/plugins").json()["plugins"]
        cur[k][p] = v
        r = s.put(f"{BASE_URL}/api/plugins", json={"plugins": cur})
        assert r.status_code == 400, r.text


# --- backtest new strategies + confluence
class TestBacktest:
    @pytest.mark.parametrize("strat", NEW + ["confluence"])
    def test_backtest(self, s, strat):
        body = {"symbol": "BTC-USD", "tf": "1h", "strategy": strat}
        if strat == "confluence":
            body.update({"conf_votes": 2, "conf_score": 50})
        r = s.post(f"{BASE_URL}/api/backtest", json=body, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["strategy"] == strat and "metrics" in d and isinstance(d.get("trades", []), list)

    def test_backtest_conf_votes_invalid(self, s):
        r = s.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTC-USD", "tf": "1h", "strategy": "confluence", "conf_votes": 11})
        assert r.status_code == 422


# --- confluence live detail
class TestConfluence:
    def test_shape(self, s):
        r = s.get(f"{BASE_URL}/api/confluence?symbol=BTC-USD&tf=1h&votes=2&score=55", timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("votes_up", "votes_dn", "score_up", "score_dn", "trend", "plugins", "signal"):
            assert k in d, k
        assert d["min_votes"] == 2 and d["min_score"] == 55
        enabled = {p["plugin"] for p in d["plugins"]}
        assert set(NEW) <= enabled  # enabled in TestPlugins
        for p in d["plugins"]:
            assert p["vote"] in (-1, 0, 1) and 0 <= p["weight"] <= 100 and p["label"]

    @pytest.mark.parametrize("q", ["symbol=FOO&tf=1h", "symbol=BTC-USD&tf=7x"])
    def test_invalid(self, s, q):
        assert s.get(f"{BASE_URL}/api/confluence?{q}").status_code == 400


# --- main bot config confluence + setups with new strategies
class TestBotConfig:
    def test_put_confluence(self, s):
        bot = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: bot[k] for k in ("enabled", "symbols", "tf", "risk_pct", "sl_atr", "rr", "max_positions", "trend_filter", "mtf", "ai_filter")}
        body.update({"enabled": False, "strategy": "confluence", "conf_votes": 3, "conf_score": 62,
                     "setups": [{"symbol": bot["symbols"][0], "tf": "1h", "strategy": "supertrend"}]})
        r = s.put(f"{BASE_URL}/api/bot", json=body)
        assert r.status_code == 200, r.text
        g = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        assert g["strategy"] == "confluence" and g["conf_votes"] == 3 and g["conf_score"] == 62
        assert g["setups"][0]["strategy"] == "supertrend"

    @pytest.mark.parametrize("patch", [{"conf_votes": 0}, {"conf_votes": 11}, {"conf_score": 30}, {"conf_score": 95}, {"strategy": "nope"}])
    def test_put_invalid(self, s, patch):
        bot = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: bot[k] for k in ("enabled", "symbols", "tf", "strategy", "conf_votes", "conf_score")}
        body.update(patch)
        assert s.put(f"{BASE_URL}/api/bot", json=body).status_code in (400, 422)


# --- deterministic apply logic using a fixed adjustments doc
class TestApplyDeterministic:
    def test_apply(self, s):
        d = seedmod.db()
        bot = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        hb = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
        new_risk = 0.5 if bot["risk_pct"] != 0.5 else 0.7
        new_mph = 5 if hb["max_per_hour"] != 5 else 6
        adjs = [{"scope": "bot", "field": "risk_pct", "value": new_risk, "label": "Risco", "from": str(bot["risk_pct"]), "to": str(new_risk), "reason": "t", "applied": False},
                {"scope": "bot", "field": "plugin_off", "value": "donchian", "label": "Plugin", "from": "ligado", "to": "desligado", "reason": "t", "applied": False},
                {"scope": "hfx", "field": "max_per_hour", "value": new_mph, "label": "Máx", "from": "x", "to": "y", "reason": "t", "applied": False},
                {"scope": "bot", "field": "conf_votes", "value": 4, "label": "Conf", "from": "3", "to": "4", "reason": "t", "applied": False}]
        d.daily_summaries.update_one({"user_id": seedmod.UID, "date": FAKE_DATE}, {"$set": {"text": "x", "adjustments": adjs}}, upsert=True)
        r = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": FAKE_DATE, "ids": [0, 1, 2, 3]})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["applied"] == 4, j
        assert all(a["applied"] for a in j["adjustments"])
        g = s.get(f"{BASE_URL}/api/bot").json()
        assert g["bot"]["risk_pct"] == new_risk and g["bot"]["conf_votes"] == 4
        assert any("Ajuste IA aplicado" in l["msg"] for l in g["logs"])
        assert s.get(f"{BASE_URL}/api/plugins").json()["plugins"]["donchian"]["enabled"] is False
        h = s.get(f"{BASE_URL}/api/hfx/bot").json()
        assert h["bot"]["max_per_hour"] == new_mph
        assert any("Ajuste IA aplicado" in l["msg"] for l in h["logs"])

    def test_reapply_zero(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": FAKE_DATE, "ids": [0, 1]})
        assert r.status_code == 200 and r.json()["applied"] == 0

    def test_unknown_date(self, s):
        assert s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": "1999-01-01", "ids": [0]}).status_code == 404


# --- real LLM daily summary -> adjustments -> apply
class TestDailyLLM:
    def test_generate_and_apply(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": TODAY}, stream=True, timeout=180)
        assert r.status_code == 200, r.text
        chunks, statuses, errors, done = [], [], [], False
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                done = True
                break
            j = json.loads(data)
            chunks.append(j.get("t", ""))
            if "status" in j:
                statuses.append(j["status"])
            if "error" in j:
                errors.append(j["error"])
        assert done and not errors, errors
        assert "adjustments" in statuses and len("".join(chunks)) > 100
        docs = s.get(f"{BASE_URL}/api/ai/daily-summaries").json()
        doc = next(x for x in docs if x["date"] == TODAY)
        adjs = doc.get("adjustments")
        assert isinstance(adjs, list)
        print("ADJUSTMENTS:", json.dumps(adjs, ensure_ascii=False))
        if not adjs:
            pytest.skip("LLM returned no adjustments")
        for a in adjs:
            for k in ("scope", "field", "value", "label", "from", "to", "reason", "applied"):
                assert k in a, k
            assert a["applied"] is False and a["scope"] in ("hfx", "bot")
        r2 = s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": TODAY, "ids": [0]})
        assert r2.status_code == 200, r2.text
        assert r2.json()["applied"] == 1 and r2.json()["adjustments"][0]["applied"] is True
        assert s.post(f"{BASE_URL}/api/ai/daily-summary/apply", json={"date": TODAY, "ids": [0]}).json()["applied"] == 0
