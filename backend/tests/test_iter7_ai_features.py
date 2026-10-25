# Iteration 7: auto_fix persistence bug, ai_filter config, AI loss-review SSE, ai.ai_filter helper
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
UID = "user_test1"
mdb = MongoClient(os.environ.get("MONGO_URL"))[os.environ.get("DB_NAME")]


@pytest.fixture(scope="module")
def s():
    ss = requests.Session()
    ss.headers.update(H)
    return ss


def hfx_cfg(s, **kw):
    b = s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]
    b.update(kw)
    return b


def bot_cfg(s, **kw):
    b = s.get(f"{BASE_URL}/api/bot").json()["bot"]
    b.update(kw)
    return b


def read_sse(resp):
    chunks, errors, done = [], [], False
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data == "[DONE]":
            done = True
            break
        j = json.loads(data)
        if "error" in j:
            errors.append(j["error"])
        if "t" in j:
            chunks.append(j["t"])
    return "".join(chunks), errors, done, len(chunks)


# --- Bug fix: saving HFX bot config must not re-enable auto_fix
class TestAutoFixPersistence:
    def test_hfx_auto_fix_stays_off_after_put(self, s):
        r = s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": "hfx", "enabled": False})
        assert r.status_code == 200
        assert s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]["auto_fix"] is False
        r = s.put(f"{BASE_URL}/api/hfx/bot", json=hfx_cfg(s, enabled=False, auto_fix=True))  # even if client sends True
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]["auto_fix"] is False
        assert s.get(f"{BASE_URL}/api/hfx/analysis?scope=bot").json()["auto_fix"] is False

    def test_bot_auto_fix_stays_off_after_put(self, s):
        assert s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": "bot", "enabled": False}).status_code == 200
        r = s.put(f"{BASE_URL}/api/bot", json=bot_cfg(s, enabled=False))
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["auto_fix"] is False
        assert s.get(f"{BASE_URL}/api/bot/analysis").json()["auto_fix"] is False

    def test_restore_auto_fix(self, s):
        for sc in ("hfx", "bot"):
            assert s.put(f"{BASE_URL}/api/analysis/auto-fix", json={"scope": sc, "enabled": True}).status_code == 200
        assert s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]["auto_fix"] is True
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["auto_fix"] is True


# --- ai_filter flag persisted on both bots
class TestAiFilterConfig:
    @pytest.mark.parametrize("val", [True, False])
    def test_hfx_ai_filter(self, s, val):
        r = s.put(f"{BASE_URL}/api/hfx/bot", json=hfx_cfg(s, enabled=False, ai_filter=val))
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/hfx/bot").json()["bot"]["ai_filter"] is val

    @pytest.mark.parametrize("val", [True, False])
    def test_bot_ai_filter(self, s, val):
        r = s.put(f"{BASE_URL}/api/bot", json=bot_cfg(s, enabled=False, ai_filter=val))
        assert r.status_code == 200, r.text
        assert s.get(f"{BASE_URL}/api/bot").json()["bot"]["ai_filter"] is val

    def test_hfx_ai_filter_invalid_type(self, s):
        r = s.put(f"{BASE_URL}/api/hfx/bot", json=hfx_cfg(s, enabled=False, ai_filter="notabool"))
        assert r.status_code == 422


# --- AI loss review (SSE)
class TestLossReview:
    def test_invalid_scope(self, s):
        r = s.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "xyz"})
        assert r.status_code == 400
        assert "inválido" in r.json()["detail"]

    def test_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "hfx"})
        assert r.status_code == 401

    def test_too_few_trades_hfx(self, s):
        if mdb.hfx_trades.count_documents({"user_id": UID, "status": {"$in": ["won", "lost"]}}) >= 3:
            pytest.skip("user already has >=3 closed hfx trades")
        r = s.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "hfx"})
        assert r.status_code == 400
        assert "Poucas operações" in r.json()["detail"]

    def test_too_few_trades_bot(self, s):
        if mdb.positions.count_documents({"user_id": UID, "status": "closed", "source": "bot"}) >= 3:
            pytest.skip("user already has >=3 closed bot positions")
        r = s.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "bot"})
        assert r.status_code == 400
        assert "Poucas operações" in r.json()["detail"]

    def test_hfx_stream_and_saved(self, s):
        now = time.time()
        docs = []
        for i in range(6):
            ts = now - 600 * (i + 1)
            won = i % 3 == 0
            docs.append({"trade_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "pair": "EURUSD=X", "source": "otc",
                         "direction": "CALL" if i % 2 else "PUT", "amount": 10.0, "payout": 0.85, "expiry": 1,
                         "entry_price": 1.1, "opened_ts": ts, "expires_ts": ts + 60, "status": "won" if won else "lost",
                         "profit": 8.5 if won else -10.0, "origin": "bot", "rule": "rsi", "rule_label": "RSI reversão",
                         "closed_at": datetime.fromtimestamp(ts + 60, timezone.utc).isoformat(),
                         "ctx": {"aligned": i % 2 == 0, "rsi": 72.0, "vol_pct": 90, "hour": 14}})
        mdb.hfx_trades.insert_many(docs)
        try:
            t0 = time.time()
            r = s.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "hfx"}, stream=True, timeout=120)
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            text, errors, done, n = read_sse(r)
            print(f"hfx review: {n} chunks, {len(text)} chars in {time.time() - t0:.1f}s; preview: {text[:200]!r}")
            assert not errors, errors
            assert done
            assert n > 1 and len(text) > 200
            time.sleep(1)
            last = s.get(f"{BASE_URL}/api/ai/loss-review?scope=hfx").json()
            assert last["text"] == text
            assert last["created_at"]
        finally:
            mdb.hfx_trades.delete_many({"trade_id": {"$regex": "^TEST_"}, "user_id": UID})

    def test_bot_stream(self, s):
        docs = []
        for i in range(5):
            ca = (datetime.now(timezone.utc) - timedelta(hours=i + 1)).isoformat()
            pnl = 20.0 if i == 0 else -10.0
            docs.append({"position_id": "TEST_" + uuid.uuid4().hex[:10], "user_id": UID, "symbol": "BTC-USD", "side": "BUY",
                         "qty": 0.01, "entry": 60000.0, "exit": 59000.0, "stop_loss": 59000.0, "take_profit": 62000.0,
                         "status": "closed", "source": "bot", "setup": "BTC-USD|1h", "tf": "1h", "stop_dist": 1000.0,
                         "pnl": pnl, "reason": "take_profit" if pnl > 0 else "stop_loss",
                         "ctx": {"hour": 10, "htf_aligned": False}, "opened_at": ca, "closed_at": ca})
        mdb.positions.insert_many(docs)
        try:
            r = s.post(f"{BASE_URL}/api/ai/loss-review", json={"scope": "bot"}, stream=True, timeout=120)
            assert r.status_code == 200
            text, errors, done, n = read_sse(r)
            print(f"bot review: {n} chunks, {len(text)} chars")
            assert not errors and done and len(text) > 200
            time.sleep(1)
            assert s.get(f"{BASE_URL}/api/ai/loss-review?scope=bot").json()["text"] == text
        finally:
            mdb.positions.delete_many({"position_id": {"$regex": "^TEST_"}, "user_id": UID})


# --- ai.ai_filter helper (direct call, real LLM)
class TestAiFilterHelper:
    def _run(self, ctx, timeout=30):
        sys.path.insert(0, "/app/backend")
        import ai  # noqa
        return asyncio.run(ai.ai_filter(ctx, timeout=timeout))

    def test_returns_shape(self):
        v = self._run("Opção binária CALL em EUR/USD OTC, expiração 1 min, payout 85% (equilíbrio 54.1%). "
                      "Estratégia: RSI — acerto 62% em 80 sinais. Contexto: a favor da tendência, RSI14 48, volatilidade p50.")
        print(v)
        assert set(v) == {"approve", "confidence", "reason"}
        assert isinstance(v["approve"], bool) and isinstance(v["confidence"], int) and v["reason"]
        assert "indisponível" not in v["reason"]

    def test_fails_closed_on_timeout(self):
        v = self._run("teste", timeout=0.01)
        assert v["approve"] is False and v["confidence"] == 0 and "indisponível" in v["reason"]
