# Iteration 18: "> 10% test profit OR > 60% test win rate" rule applied to ALL optimisers, ranked by profit / drawdown
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategies import qualifies, MIN_RETURN, MIN_WINRATE  # noqa: E402


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("EXPO_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}


def _poll(path, timeout=900, every=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE_URL}{path}", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        if d["status"] == "done":
            return d
        time.sleep(every)
    pytest.fail(f"timeout polling {path}")


def _rule(best):
    return qualifies(best["test"]["return_pct"], best["test"]["win_rate"])


# ---- qualifies() unit
class TestQualifiesUnit:
    def test_constants(self):
        assert MIN_RETURN == 10.0 and MIN_WINRATE == 60.0

    @pytest.mark.parametrize("ret,wr,exp", [(10.5, 30, True), (2, 61, True), (9.9, 59.9, False), (10, 60, False),
                                            (-5, 80, False), (0, 90, False), (15, 0, True)])
    def test_rule(self, ret, wr, exp):
        assert qualifies(ret, wr) is exp

    def test_custom_threshold(self):
        assert qualifies(6, 30, 5) is True and qualifies(4, 30, 5) is False and qualifies(4, 65, 5) is True


def _check_optimize_payload(d):
    cands = d["candidates"]
    validated = [c for c in cands if "score" in c]
    for c in validated:
        assert isinstance(c["qualified"], bool)
        assert c["qualified"] == _rule(c)
        dd = max(c["test"]["max_drawdown"], c["train"]["max_drawdown"])
        assert abs(c["score"] - (c["test"]["return_pct"] + c["train"]["return_pct"]) / (1 + dd)) < 1e-6
    keys = [(c["qualified"], c["score"]) for c in validated]
    assert keys == sorted(keys, reverse=True), "candidates not sorted by (qualified, score)"
    b = d["best"]
    if b is not None:
        assert b["qualified"] is True and _rule(b)
        assert validated and validated[0]["score"] == b["score"]
    else:
        assert not any(c["qualified"] for c in validated)


# ---- POST /api/optimize
class TestOptimizeSingle:
    @pytest.mark.parametrize("sym,tf", [("BTC-USD", "1h"), ("ETH-USD", "4h")])
    def test_optimize(self, sym, tf):
        r = requests.post(f"{BASE_URL}/api/optimize", headers=H, json={"symbol": sym, "tf": tf}, timeout=240)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["symbol"] == sym and d["tf"] == tf and d["tested"] > 0
        _check_optimize_payload(d)
        print(sym, tf, "best:", d["best"] and (d["best"]["strategy"], d["best"]["test"]["return_pct"], d["best"]["test"]["win_rate"]))

    def test_optimize_no_auth(self):
        r = requests.post(f"{BASE_URL}/api/optimize", json={"symbol": "BTC-USD", "tf": "1h"}, timeout=30)
        assert r.status_code == 401


# ---- POST /api/optimize/all + GET status
class TestOptimizeAll:
    def test_optimize_all_btc(self):
        r = requests.post(f"{BASE_URL}/api/optimize/all", headers=H, json={"symbol": "BTC-USD"}, timeout=30)
        assert r.status_code == 200, r.text
        d = _poll(f"/api/optimize/all/{r.json()['job_id']}")
        assert len(d["results"]) == d["total"] == 8
        for e in d["results"]:
            print(e["tf"], e.get("error"), e["best"] and (e["best"]["test"]["return_pct"], e["best"]["test"]["win_rate"]))
            if e["best"] is not None:
                assert _rule(e["best"]) and e["best"]["qualified"] is True

    def test_unknown_symbol(self):
        r = requests.post(f"{BASE_URL}/api/optimize/all", headers=H, json={"symbol": "NOPE"}, timeout=30)
        assert r.status_code == 404

    def test_unknown_job(self):
        r = requests.get(f"{BASE_URL}/api/optimize/all/doesnotexist", headers=H, timeout=30)
        assert r.status_code == 404


# ---- POST /api/bot/c20-optimize?kind=c12|c20 (test user bot: symbols=[BTC-USD])
class TestCOptimize:
    @pytest.mark.parametrize("kind", ["c12", "c20"])
    def test_c_optimize(self, kind):
        bot = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()
        thr = float((bot.get("bot") or bot).get("c_min_return", 10))
        r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind={kind}", headers=H, timeout=30)
        assert r.status_code == 200, r.text
        d = _poll(f"/api/bot/c20-optimize/{r.json()['job_id']}")
        assert d["kind"] == kind and d["results"]
        for p in d["results"]:
            print(kind, thr, {k: p.get(k) for k in ("symbol", "tf", "min", "rr", "train", "test", "test_winrate", "score", "qualified", "enabled")})
            if p.get("test") is None:
                assert p["enabled"] is False
                continue
            exp = p["train"] > 0 and qualifies(p["test"], p["test_winrate"], thr)
            assert p["qualified"] == exp
            assert p["enabled"] == exp
        bot2 = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()
        pairs = (bot2.get("bot") or bot2).get(f"{kind}_pairs") or []
        saved = {x["symbol"]: x for x in pairs}
        for p in d["results"]:
            assert saved[p["symbol"]]["enabled"] == p["enabled"]

    def test_bad_kind(self):
        r = requests.post(f"{BASE_URL}/api/bot/c20-optimize?kind=xx", headers=H, timeout=30)
        assert r.status_code == 400


# ---- /api/simulate/optimize-negatives
class TestNegOpt:
    def test_negopt(self):
        items = [{"kind": "setup", "symbol": "BTC-USD", "tf": "1h", "strategy": "smc"},
                 {"kind": "c20", "symbol": "BTC-USD", "tf": "1h"}]
        r = requests.post(f"{BASE_URL}/api/simulate/optimize-negatives", headers=H, json={"items": items}, timeout=30)
        assert r.status_code == 200, r.text
        d = _poll(f"/api/simulate/optimize-negatives/{r.json()['job_id']}")
        assert len(d["results"]) == 2
        for p in d["results"]:
            print("negopt", p["kind"], p["best"])
            if p["best"]:
                assert p["best"]["test"] > 0

    def test_negopt_empty(self):
        r = requests.post(f"{BASE_URL}/api/simulate/optimize-negatives", headers=H, json={"items": []}, timeout=30)
        assert r.status_code == 400


# ---- /api/bot/optimize-all (test user only, BTC-USD)
class TestBotOptimizeAll:
    def test_bot_optimize_all(self):
        r = requests.post(f"{BASE_URL}/api/bot/optimize-all", headers=H, timeout=30)
        assert r.status_code in (200, 429), r.text
        if r.status_code == 429:
            pytest.skip("already running")
        jid = r.json()["job_id"]
        d = _poll(f"/api/bot/optimize-all/{jid}", timeout=1500)
        for x in d["results"]:
            print("botopt", x["tf"], x["best"]["test"]["return_pct"], x["best"]["test"]["win_rate"], x["best"].get("score"))
            assert _rule(x["best"])
        scores = [x["best"]["score"] for x in d["results"]]
        assert scores == sorted(scores, reverse=True)
        bot = requests.get(f"{BASE_URL}/api/bot", headers=H, timeout=30).json()
        setups = (bot.get("bot") or bot).get("setups") or []
        assert {(s["symbol"], s["tf"]) for s in setups} == {(x["symbol"], x["tf"]) for x in d["results"]}
        print("JOB_ID", jid)
