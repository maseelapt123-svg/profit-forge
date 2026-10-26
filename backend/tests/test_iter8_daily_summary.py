# Iteration 8: Daily AI Summary — /api/ai/daily-stats, /api/ai/daily-summary (SSE), /api/ai/daily-summaries
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import manual_seed_daily as seedmod  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
H = {"Authorization": "Bearer test_token_123", "Content-Type": "application/json"}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
EMPTY = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def s():
    seedmod.seed()
    ss = requests.Session()
    ss.headers.update(H)
    yield ss
    seedmod.clean()


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


# --- daily-stats aggregation
class TestDailyStats:
    def test_default_today_shape(self, s):
        r = s.get(f"{BASE_URL}/api/ai/daily-stats")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["date"] == TODAY
        for k in ("trades", "wins", "winrate", "pnl", "groups", "bad_hours", "ai_rejected", "fix_skipped", "breakeven"):
            assert k in d["hfx"], k
        for k in ("trades", "wins", "winrate", "pnl", "groups", "bad_hours", "ai_rejected"):
            assert k in d["bot"], k
        assert "config" not in d["hfx"] and "fixes" not in d["bot"]

    def test_today_values(self, s):
        d = s.get(f"{BASE_URL}/api/ai/daily-stats?date={TODAY}").json()
        assert d["hfx"]["trades"] == 6 and d["hfx"]["wins"] == 3  # manual + open excluded
        assert abs(d["hfx"]["pnl"] - (-4.5)) < 1e-6
        assert abs(d["hfx"]["winrate"] - 50) < 1e-6
        assert d["bot"]["trades"] == 3 and d["bot"]["wins"] == 2
        assert abs(d["bot"]["pnl"] - (-2.5)) < 1e-6
        assert d["total_trades"] == 9 and abs(d["total_pnl"] - (-7.0)) < 1e-6
        assert any("EUR/USD" in g["label"] for g in d["hfx"]["groups"]), d["hfx"]["groups"]
        assert d["bot"]["groups"][0]["label"].startswith("BTC")
        assert "h (" in d["hfx"]["bad_hours"]

    def test_yesterday_values(self, s):
        d = s.get(f"{BASE_URL}/api/ai/daily-stats?date={YDAY}").json()
        assert d["date"] == YDAY
        assert d["hfx"]["trades"] == 4 and d["bot"]["trades"] == 2
        assert d["total_trades"] == 6 and abs(d["total_pnl"] - (-18.0)) < 1e-6

    def test_empty_day(self, s):
        d = s.get(f"{BASE_URL}/api/ai/daily-stats?date={EMPTY}").json()
        assert d["total_trades"] == 0 and d["total_pnl"] == 0 and d["hfx"]["winrate"] == 0

    @pytest.mark.parametrize("bad", ["2026-13-01", "abc", "2026/01/01", "01-01-2026"])
    def test_invalid_date(self, s, bad):
        r = s.get(f"{BASE_URL}/api/ai/daily-stats", params={"date": bad})
        assert r.status_code == 400
        assert "Data inválida" in r.json()["detail"]

    def test_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/ai/daily-stats").status_code == 401


# --- daily-summary SSE generation + persistence
class TestDailySummary:
    def test_no_trades_400(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": EMPTY})
        assert r.status_code == 400
        assert r.json()["detail"] == "Os robôs não fecharam operações neste dia"

    def test_invalid_date_400(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": "xx"})
        assert r.status_code == 400

    def test_requires_auth(self):
        assert requests.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": TODAY}).status_code == 401

    def test_stream_today(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": TODAY}, stream=True, timeout=120)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text, errors, done, n = read_sse(r)
        assert not errors, errors
        assert done and n > 3 and len(text) > 200
        assert "Ajustes para amanhã" in text, text[:500]
        assert "`" not in text
        pytest.today_text = text

    def test_stream_yesterday_default_body(self, s):
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={"date": YDAY}, stream=True, timeout=120)
        text, errors, done, _ = read_sse(r)
        assert done and not errors and len(text) > 100

    def test_history_sorted_and_shape(self, s):
        h = s.get(f"{BASE_URL}/api/ai/daily-summaries").json()
        assert [x["date"] for x in h] == [TODAY, YDAY]
        for x in h:
            assert set(("date", "text", "stats", "created_at")) <= set(x) and "_id" not in x and "user_id" not in x
        assert h[0]["text"] == pytest.today_text
        assert h[0]["stats"]["total_trades"] == 9 and h[1]["stats"]["total_trades"] == 6
        assert "config" not in h[0]["stats"]["hfx"]

    def test_regenerate_upserts_one_per_date(self, s):
        before = s.get(f"{BASE_URL}/api/ai/daily-summaries").json()[0]["created_at"]
        r = s.post(f"{BASE_URL}/api/ai/daily-summary", json={}, stream=True, timeout=120)  # default = today
        _, errors, done, _ = read_sse(r)
        assert done and not errors
        h = s.get(f"{BASE_URL}/api/ai/daily-summaries").json()
        assert [x["date"] for x in h].count(TODAY) == 1 and len(h) == 2
        assert h[0]["created_at"] > before
