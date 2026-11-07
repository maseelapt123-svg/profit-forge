# Iteration 20: market scan (Simular -> Vários pares), Robô 2 API, log separation, mt_bot selector
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}


def _rule_ok(r):
    return (r["wr"] > 55 and r["test"] >= 6) or r["test"] > 25


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    x.headers.update(H)
    return x


@pytest.fixture(scope="module")
def originals(s):
    """Snapshot main bot + Robô 2 to restore at the end."""
    main = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    b2 = s.get(f"{BASE_URL}/api/bot2").json()["bot"]
    yield main, b2
    s.put(f"{BASE_URL}/api/bot2", json={"enabled": b2["enabled"], "risk_pct": b2["risk_pct"], "setups": b2["setups"]})
    body = {k: v for k, v in main.items() if k not in ("user_id", "updated_at", "live_until", "fixes", "last_run")}
    s.put(f"{BASE_URL}/api/bot", json=body)


# ---- scan ----
class TestScan:
    def test_scan_no_tfs_400(self, s):
        r = s.post(f"{BASE_URL}/api/scan", json={"category": "stocks", "tfs": []})
        assert r.status_code == 400

    def test_scan_bad_category_422(self, s):
        r = s.post(f"{BASE_URL}/api/scan", json={"category": "xyz", "tfs": ["1d"]})
        assert r.status_code == 422

    def test_scan_full_run(self, s):
        r = s.post(f"{BASE_URL}/api/scan", json={"category": "stocks", "tfs": ["1d"]})
        if r.status_code == 429:
            pytest.skip("a scan is already running")
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        # second start while running -> 429
        r2 = s.post(f"{BASE_URL}/api/scan", json={"category": "stocks", "tfs": ["1d"]})
        assert r2.status_code == 429
        job = None
        for _ in range(60):
            job = s.get(f"{BASE_URL}/api/scan/current").json()["job"]
            assert job["job_id"] == jid
            assert "_id" not in job
            if job["status"] == "done":
                break
            time.sleep(4)
        assert job["status"] == "done", f"scan not finished: step {job['step']}/{job['total']}"
        assert job["step"] == job["total"]
        assert not job.get("error")
        res = job["results"]
        keys = {"symbol", "display", "tf", "strategy", "rr", "sl_atr", "test", "wr", "dd", "trades", "train", "score"}
        for x in res:
            assert keys <= set(x), x
            assert _rule_ok(x), x
        scores = [x["score"] for x in res]
        assert scores == sorted(scores, reverse=True)
        pytest.job = job


# ---- Robô 2 ----
class TestBot2:
    def test_get_bot2_shape(self, s, originals):
        d = s.get(f"{BASE_URL}/api/bot2").json()
        assert set(d["bot"]) == {"enabled", "risk_pct", "setups", "last_run"}
        assert isinstance(d["mt"], bool)
        assert all(l.get("scope") == "bot2" for l in d["logs"])
        assert {"trades", "pnl", "wins", "open"} <= set(d["stats"])
        assert isinstance(d["positions"], list)

    def test_add_wrong_job_404(self, s):
        r = s.post(f"{BASE_URL}/api/bot2/add", json={"job_id": "nope000000", "keys": ["TSLA|1d"]})
        assert r.status_code == 404

    def test_add_no_keys_400(self, s):
        job = s.get(f"{BASE_URL}/api/scan/current").json()["job"]
        r = s.post(f"{BASE_URL}/api/bot2/add", json={"job_id": job["job_id"], "keys": ["ZZZ|1d"]})
        assert r.status_code == 400

    def test_add_and_replace(self, s, originals):
        job = s.get(f"{BASE_URL}/api/scan/current").json()["job"]
        if not job["results"]:
            pytest.skip("scan has no results")
        r0 = job["results"][0]
        key = f"{r0['symbol']}|{r0['tf']}"
        r = s.post(f"{BASE_URL}/api/bot2/add", json={"job_id": job["job_id"], "keys": [key]})
        assert r.status_code == 200 and r.json()["added"] == 1
        r = s.post(f"{BASE_URL}/api/bot2/add", json={"job_id": job["job_id"], "keys": [key]})
        assert r.status_code == 200
        setups = s.get(f"{BASE_URL}/api/bot2").json()["bot"]["setups"]
        same = [x for x in setups if x["symbol"] == r0["symbol"] and x["tf"] == r0["tf"]]
        assert len(same) == 1 and same[0]["strategy"] == r0["strategy"]
        assert r.json()["total"] == len(setups)

    def test_put_enabled_no_setups_400(self, s):
        r = s.put(f"{BASE_URL}/api/bot2", json={"enabled": True, "risk_pct": 1.0, "setups": []})
        assert r.status_code == 400

    def test_put_invalid_setup_400(self, s):
        r = s.put(f"{BASE_URL}/api/bot2", json={"enabled": False, "risk_pct": 1.0, "setups": [
            {"symbol": "NOPE", "tf": "1d", "strategy": "ema_cross", "sl_atr": 2, "rr": 2}]})
        assert r.status_code in (400, 422)

    def test_put_risk_out_of_range_422(self, s):
        r = s.put(f"{BASE_URL}/api/bot2", json={"enabled": False, "risk_pct": 9, "setups": []})
        assert r.status_code == 422

    def test_put_persist_risk(self, s, originals):
        _, b2 = originals
        setups = s.get(f"{BASE_URL}/api/bot2").json()["bot"]["setups"]
        r = s.put(f"{BASE_URL}/api/bot2", json={"enabled": False, "risk_pct": 1.5, "setups": setups})
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/bot2").json()["bot"]["risk_pct"] == 1.5

    def test_run_cycle(self, s):
        r = s.post(f"{BASE_URL}/api/bot2/run", timeout=120)
        assert r.status_code == 200, r.text
        assert isinstance(r.json()["opened"], int)
        d = s.get(f"{BASE_URL}/api/bot2").json()
        assert d["bot"]["last_run"]
        assert all(p.get("source", "bot2") for p in d["positions"])

    def test_logs_separated(self, s):
        main_logs = s.get(f"{BASE_URL}/api/bot").json()["logs"]
        assert not any(l.get("scope") == "bot2" for l in main_logs)
        assert not any("Robô 2" in l["msg"] or "no Robô 2" in l["msg"] for l in main_logs)


# ---- mt_bot selector ----
class TestMtBot:
    def test_get_default(self, s):
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"].get("mt_bot") in ("main", "bot2")

    def _body(self, s, **kw):
        b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
        body = {k: v for k, v in b.items() if k not in ("user_id", "updated_at", "live_until", "fixes", "last_run")}
        body.update(kw)
        assert body.get("live_mode") != "metatrader"
        return body

    def test_invalid_422(self, s, originals):
        r = s.put(f"{BASE_URL}/api/bot", json=self._body(s, mt_bot="xyz"))
        assert r.status_code == 422

    def test_set_bot2_then_main(self, s, originals):
        r = s.put(f"{BASE_URL}/api/bot", json=self._body(s, mt_bot="bot2"))
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["mt_bot"] == "bot2"
        assert s.get(f"{BASE_URL}/api/bot2").json()["mt"] is False  # paper mode -> not MT
        r = s.put(f"{BASE_URL}/api/bot", json=self._body(s, mt_bot="main"))
        assert r.status_code == 200
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["mt_bot"] == "main"
