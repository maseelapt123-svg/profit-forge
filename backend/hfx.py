"""HFX: 1 & 3 minute up/down (binary-style) trading on paper account, real forex 1m or simulated 24/7 OTC feed."""
import asyncio
import math
import time
import uuid
import zlib
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import ai
from strategies import ema, rsi

logger = logging.getLogger("hfx")

PAIRS = [
    ("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"), ("AUDUSD=X", "AUD/USD"),
    ("USDCHF=X", "USD/CHF"), ("EURJPY=X", "EUR/JPY"), ("USDCAD=X", "USD/CAD"), ("EURGBP=X", "EUR/GBP"),
]
PAIR_NAME = dict(PAIRS)
DEFAULT_ANCHOR = {"EURUSD=X": 1.10, "GBPUSD=X": 1.30, "USDJPY=X": 150.0, "AUDUSD=X": 0.66, "USDCHF=X": 0.88,
                  "EURJPY=X": 165.0, "USDCAD=X": 1.37, "EURGBP=X": 0.85}
PAYOUT = {"otc": 0.85, "real": 0.82}
EXPIRIES = (1, 3)
HFX_PLUGIN_DEFAULTS = {
    "bb_rsi": {"enabled": True, "bb_len": 20, "bb_mult": 2.0, "rsi_len": 7, "rsi_lvl": 75.0},
    "rsi2": {"enabled": True, "lower": 5.0, "upper": 95.0},
    "stoch": {"enabled": True, "k": 14, "d": 3, "lvl": 20.0},
    "ema_mom": {"enabled": False, "fast": 5, "slow": 13},
    "engolfo": {"enabled": False},
    "pinbar": {"enabled": True, "wick": 2.0},
    "streak": {"enabled": False, "n": 4},
}
HFX_PLUGIN_META = {
    "bb_rsi": {"label": "Reversão BB + RSI", "desc": "Fecho fora da banda de Bollinger com RSI extremo → reversão",
               "params": {"bb_len": "Período BB", "bb_mult": "Desvios", "rsi_len": "RSI", "rsi_lvl": "Nível RSI"}},
    "rsi2": {"label": "RSI(2) Extremo", "desc": "RSI de 2 períodos abaixo/acima do limite → reversão",
             "params": {"lower": "Inferior", "upper": "Superior"}},
    "stoch": {"label": "Estocástico", "desc": "%K cruza %D dentro da zona extrema",
              "params": {"k": "%K", "d": "%D", "lvl": "Zona"}},
    "ema_mom": {"label": "Momentum EMA", "desc": "EMA rápida cruza a lenta → continuação",
                "params": {"fast": "Rápida", "slow": "Lenta"}},
    "engolfo": {"label": "Engolfo", "desc": "Vela engole a anterior → direção da vela", "params": {}},
    "pinbar": {"label": "Rejeição Pin Bar", "desc": "Pavio longo de rejeição → direção oposta ao pavio",
               "params": {"wick": "Pavio/corpo"}},
    "streak": {"label": "Exaustão de Sequência", "desc": "N velas seguidas da mesma cor → reversão",
               "params": {"n": "Velas"}},
}
HFX_PARAM_RANGES = {"bb_len": (5, 100), "bb_mult": (1, 4), "rsi_len": (2, 30), "rsi_lvl": (55, 95), "lower": (1, 40),
                    "upper": (60, 99), "k": (3, 50), "d": (2, 10), "lvl": (5, 40), "fast": (2, 50), "slow": (3, 100),
                    "wick": (1, 6), "n": (2, 10)}
RULES = {k: v["label"] for k, v in HFX_PLUGIN_META.items()}


def decimals(p: float) -> int:
    return 3 if p >= 20 else 5


def pair_display(pair: str, source: str) -> str:
    return PAIR_NAME[pair] + (" OTC" if source == "otc" else "")


# ------------------------------------------------------------------ simulated OTC feed
class OtcFeed:
    """Deterministic per-second random walk (mean-reverting to the last real price). 24/7, like broker OTC."""
    SIGMA = 3.0e-5  # per-second log volatility
    KAPPA = 1 / 5400  # mean reversion speed
    HISTORY = 6 * 3600

    def __init__(self):
        self.s: Dict[str, dict] = {}
        self.anchors: Dict[str, float] = dict(DEFAULT_ANCHOR)

    def set_anchor(self, pair: str, price: float):
        if price and price > 0:
            self.anchors[pair] = price

    @staticmethod
    def _z(pair: str, hour: int) -> np.ndarray:
        return np.random.default_rng(zlib.crc32(f"{pair}:{hour}".encode())).standard_normal(3600)

    def _extend(self, pair: str, upto: int):
        st = self.s.get(pair)
        if st is None:
            t0 = upto - self.HISTORY
            st = {"t0": t0, "x": [0.0], "anchor": math.log(self.anchors[pair])}
            self.s[pair] = st
        x = st["x"]
        last_t = st["t0"] + len(x) - 1
        a = 1 - self.KAPPA
        cache_h, z = None, None
        for t in range(last_t + 1, upto + 1):
            h = t // 3600
            if h != cache_h:
                z, cache_h = self._z(pair, h), h
            x.append(a * x[-1] + self.SIGMA * z[t % 3600])
        # trim history
        extra = len(x) - (self.HISTORY + 600)
        if extra > 0:
            del x[:extra]
            st["t0"] += extra

    def price_at(self, pair: str, ts: int) -> float:
        self._extend(pair, int(time.time()))
        st = self.s[pair]
        i = int(ts) - st["t0"]
        i = max(0, min(i, len(st["x"]) - 1))
        return float(math.exp(st["anchor"] + st["x"][i]))

    def candles(self, pair: str, minutes: int = 300) -> pd.DataFrame:
        now = int(time.time())
        self._extend(pair, now)
        st = self.s[pair]
        start = max(st["t0"], (now // 60 - minutes + 1) * 60)
        i0 = start - st["t0"]
        x = np.array(st["x"][i0:])
        p = np.exp(st["anchor"] + x)
        ts = np.arange(start, start + len(p))
        df = pd.DataFrame({"p": p}, index=pd.to_datetime(ts, unit="s", utc=True))
        g = df["p"].resample("1min")
        out = pd.DataFrame({"open": g.first(), "high": g.max(), "low": g.min(), "close": g.last()}).dropna()
        out["volume"] = 0.0
        return out


feed = OtcFeed()

# ------------------------------------------------------------------ real forex 1m
_real_cache: Dict[str, tuple] = {}


def _dl_1m(pair: str) -> pd.DataFrame:
    df = yf.Ticker(pair).history(period="5d", interval="1m")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.columns = ["open", "high", "low", "close", "volume"]
    return df


async def real_candles(pair: str) -> pd.DataFrame:
    hit = _real_cache.get(pair)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    df = await asyncio.to_thread(_dl_1m, pair)
    if df.empty:
        raise HTTPException(502, "Sem dados de forex")
    _real_cache[pair] = (time.time(), df)
    feed.set_anchor(pair, float(df["close"].iloc[-1]))
    return df


def market_open(df: pd.DataFrame) -> bool:
    return (time.time() - df.index[-1].timestamp()) < 10 * 60


async def get_candles(pair: str, source: str) -> pd.DataFrame:
    if pair not in PAIR_NAME:
        raise HTTPException(404, "Par desconhecido")
    if source == "otc":
        return feed.candles(pair)
    if source == "real":
        return await real_candles(pair)
    raise HTTPException(400, "Fonte inválida")


async def current_price(pair: str, source: str) -> float:
    if source == "otc":
        return feed.price_at(pair, int(time.time()))
    df = await real_candles(pair)
    return float(df["close"].iloc[-1])


# ------------------------------------------------------------------ signal rules (1m candles)
def plugin_signal(df: pd.DataFrame, name: str, cfg: dict) -> np.ndarray:
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    if name == "bb_rsi":
        n = int(cfg["bb_len"])
        mid, sd = c.rolling(n).mean(), c.rolling(n).std()
        r = rsi(c, int(cfg["rsi_len"]))
        lvl = float(cfg["rsi_lvl"])
        put = (c > mid + cfg["bb_mult"] * sd) & (r > lvl)
        call = (c < mid - cfg["bb_mult"] * sd) & (r < 100 - lvl)
        return np.where(call, 1, np.where(put, -1, 0))
    if name == "rsi2":
        r = rsi(c, 2)
        return np.where(r < cfg["lower"], 1, np.where(r > cfg["upper"], -1, 0))
    if name == "stoch":
        k = int(cfg["k"])
        ll, hh = l.rolling(k).min(), h.rolling(k).max()
        pk = ((c - ll) / (hh - ll).replace(0, np.nan) * 100).fillna(50)
        pd_ = pk.rolling(int(cfg["d"])).mean()
        lvl = float(cfg["lvl"])
        up = (pk > pd_) & (pk.shift() <= pd_.shift()) & (pd_ < lvl)
        dn = (pk < pd_) & (pk.shift() >= pd_.shift()) & (pd_ > 100 - lvl)
        return np.where(up, 1, np.where(dn, -1, 0))
    if name == "ema_mom":
        f, s_ = ema(c, int(cfg["fast"])), ema(c, int(cfg["slow"]))
        up = (f > s_) & (f.shift() <= s_.shift())
        dn = (f < s_) & (f.shift() >= s_.shift())
        return np.where(up, 1, np.where(dn, -1, 0))
    if name == "engolfo":
        po, pc = o.shift(), c.shift()
        bull = (pc < po) & (c > o) & (c >= po) & (o <= pc)
        bear = (pc > po) & (c < o) & (c <= po) & (o >= pc)
        return np.where(bull, 1, np.where(bear, -1, 0))
    if name == "pinbar":
        body = (c - o).abs().replace(0, 1e-12)
        upper = h - np.maximum(c, o)
        lower = np.minimum(c, o) - l
        w = float(cfg["wick"])
        call = (lower >= w * body) & (upper <= body)
        put = (upper >= w * body) & (lower <= body)
        return np.where(call, 1, np.where(put, -1, 0))
    if name == "streak":
        n = int(cfg["n"])
        green = (c > o).astype(int)
        red = (c < o).astype(int)
        g = green.rolling(n).sum() == n
        r_ = red.rolling(n).sum() == n
        return np.where(r_, 1, np.where(g, -1, 0))
    raise ValueError(name)


def outcomes(df: pd.DataFrame, expiry: int) -> np.ndarray:
    c = df["close"].to_numpy()
    out = np.zeros(len(c))
    out[:-expiry] = np.sign(c[expiry:] - c[:-expiry])
    return out


def stats_of(sig: np.ndarray, out: np.ndarray, lo: int, hi: int) -> dict:
    s, o = sig[lo:hi], out[lo:hi]
    m = s != 0
    res = s[m] * o[m]
    wins, losses = int((res > 0).sum()), int((res < 0).sum())
    n = wins + losses
    wr = wins / n if n else 0.0
    # Wilson 95% lower bound -> how sure we are the edge is real
    z = 1.96
    lb = ((wr + z * z / (2 * n) - z * math.sqrt((wr * (1 - wr) + z * z / (4 * n)) / n)) / (1 + z * z / n)) if n else 0.0
    return {"wins": wins, "losses": losses, "samples": n, "winrate": wr * 100, "lower_bound": lb * 100}


def combo_signal(sigs: Dict[str, np.ndarray], rule: str, min_votes: int = 2) -> np.ndarray:
    """rule = plugin | 'a+b' (both agree) | 'confluence' (>= min_votes of enabled plugins agree, none opposite)."""
    if rule == "confluence":
        arr = np.array(list(sigs.values()))
        up, dn = (arr > 0).sum(0), (arr < 0).sum(0)
        return np.where((up >= min_votes) & (dn == 0), 1, np.where((dn >= min_votes) & (up == 0), -1, 0))
    if "+" in rule:
        a, b = rule.split("+")
        return np.where(sigs[a] == sigs[b], sigs[a], 0)
    return sigs[rule]


def rule_label(rule: str, min_votes: int = 2) -> str:
    if rule == "confluence":
        return f"Confluência ({min_votes}+ plugins)"
    return " + ".join(HFX_PLUGIN_META[p]["label"] for p in rule.split("+"))


def analyze_pair(df: pd.DataFrame, source: str, expiry: int, closed_only: bool, plugins: Optional[dict] = None,
                 forced_rule: Optional[str] = None, min_votes: int = 2) -> dict:
    """Pick the rule with the best recent win rate (or a forced/optimized rule); signal only on the last CLOSED candle
    and only if that rule beats the payout break-even."""
    plugins = plugins or HFX_PLUGIN_DEFAULTS
    last_closed = len(df) - 2 if closed_only else len(df) - 1
    payout = PAYOUT[source]
    breakeven = 1 / (1 + payout) * 100
    names = [k for k, v in plugins.items() if v.get("enabled")] or list(HFX_PLUGIN_DEFAULTS)
    needed = set(names) | (set(forced_rule.split("+")) - {"confluence"} if forced_rule else set())
    sigs = {k: plugin_signal(df, k, plugins.get(k, HFX_PLUGIN_DEFAULTS[k])) for k in needed}
    out = outcomes(df, expiry)
    lo, hi = max(0, last_closed - 400), last_closed - expiry + 1
    candidates = [forced_rule] if forced_rule else names + (["confluence"] if len(names) >= 2 else [])
    rules, best = [], None
    for rule in candidates:
        sig = combo_signal({k: sigs[k] for k in names} if rule == "confluence" else sigs, rule, min_votes)
        st = stats_of(sig, out, lo, hi)
        st.update({"rule": rule, "label": rule_label(rule, min_votes), "fires": int(sig[last_closed])})
        rules.append(st)
        if (forced_rule or st["samples"] >= 30) and (best is None or st["winrate"] > best["winrate"]):
            best = st
    signal = None
    if best and best["fires"] != 0 and best["winrate"] > breakeven:
        signal = "CALL" if best["fires"] > 0 else "PUT"
    return {"signal": signal, "best": best, "rules": rules, "breakeven": breakeven, "payout": payout,
            "bar_ts": df.index[last_closed].isoformat()}


def hfx_optimize(df: pd.DataFrame, plugins: dict, payout: float, expiry: int, split: float = 0.7) -> dict:
    """Walk-forward: rank single plugins, 2-plugin combos and confluence on the first 70% of the 1m history,
    then confirm on the unseen 30%. Winner: train win rate > break-even with 95% lower bound > 50%, and test win rate >
    break-even. 'strength' = forte when the TEST 95% lower bound also beats break-even (edge statistically confirmed)."""
    breakeven = 1 / (1 + payout) * 100
    names = list(HFX_PLUGIN_DEFAULTS)
    sigs = {k: plugin_signal(df, k, plugins.get(k, HFX_PLUGIN_DEFAULTS[k])) for k in names}
    out = outcomes(df, expiry)
    cut = int(len(df) * split)
    rules = names + [f"{a}+{b}" for i, a in enumerate(names) for b in names[i + 1:]] + ["confluence"]
    res = []
    for rule in rules:
        sig = combo_signal(sigs, rule, 2)
        tr = stats_of(sig, out, 50, cut)
        te = stats_of(sig, out, cut, len(df) - expiry)
        if tr["samples"] < 40:
            continue
        res.append({"rule": rule, "label": rule_label(rule), "train": tr, "test": te})
    res.sort(key=lambda r: r["train"]["lower_bound"], reverse=True)
    best = None
    for r in res[:10]:
        if (r["train"]["winrate"] > breakeven and r["train"]["lower_bound"] > 50 and r["test"]["samples"] >= 20
                and r["test"]["winrate"] > breakeven):
            best = {**r, "strength": "forte" if r["test"]["lower_bound"] > breakeven else "moderada"}
            break
    return {"best": best, "top": res[:5], "breakeven": breakeven, "bars": len(df), "tested": len(res)}


# ------------------------------------------------------------------ router
class TradeIn(BaseModel):
    pair: str
    source: str = "otc"
    direction: str
    amount: float = Field(gt=0, le=10000)
    expiry: int = 1


class HfxBotIn(BaseModel):
    enabled: bool
    source: str = "otc"
    pairs: List[str]
    expiry: int = 1
    amount: float = Field(10, ge=1, le=1000)
    min_winrate: float = Field(56, ge=50, le=90)
    daily_stop: float = Field(100, ge=1, le=100000)
    daily_target: float = Field(200, ge=1, le=100000)
    max_per_hour: int = Field(10, ge=1, le=60)
    strategy: str = "auto"  # auto | plugins | optimized
    min_votes: int = Field(2, ge=1, le=7)
    setups: Dict[str, Dict[str, Any]] = {}
    ai_filter: bool = False


class HfxPluginsIn(BaseModel):
    plugins: Dict[str, Dict[str, Any]]


class HfxOptIn(BaseModel):
    expiry: int = 1


HFX_BOT_DEFAULT = {"enabled": False, "source": "otc", "pairs": ["EURUSD=X", "GBPUSD=X", "USDJPY=X"], "expiry": 1,
                   "amount": 10.0, "min_winrate": 56.0, "daily_stop": 100.0, "daily_target": 200.0, "max_per_hour": 10,
                   "strategy": "auto", "min_votes": 2, "setups": {}, "auto_fix": True, "fixes": {}, "ai_filter": False}


_bot_minute: Dict[str, int] = {}


def entry_context(df: pd.DataFrame, direction: str) -> dict:
    """Market context at entry, used later to explain losses."""
    c = df["close"]
    e50 = ema(c, 50)
    slope = float(e50.iloc[-1] - e50.iloc[-6]) if len(e50) > 6 else 0.0
    trend = 1 if slope > 0 else -1
    d = 1 if direction == "CALL" else -1
    rng = (df["high"] - df["low"]).iloc[-60:]
    vol_pct = float((rng.iloc[-1] >= rng).mean() * 100) if len(rng) else 50.0
    return {"aligned": trend == d, "rsi": round(float(rsi(c, 14).iloc[-1]), 1), "vol_pct": round(vol_pct),
            "hour": datetime.now(timezone.utc).hour}


DIAG = {
    "hour": "Perdas concentradas às {k}h UTC — horário com pouca qualidade. Correção: bloquear esta hora.",
    "pair_rule": "{k}: a estratégia deixou de funcionar neste par. Correção: pôr este par/estratégia em quarentena.",
    "against": "Entradas contra a tendência (EMA50 de 1m) perdem mais. Correção: só entrar a favor da tendência.",
    "low_vol": "Entradas em velas de baixa volatilidade perdem mais (mercado parado). Correção: ignorar volatilidade baixa.",
    "high_vol": "Entradas em velas de volatilidade extrema perdem mais (spikes). Correção: ignorar volatilidade extrema.",
}


def loss_analysis(trades: List[dict], breakeven: float, min_n: int = 6) -> dict:
    """Group closed trades by context; any group whose win rate is below break-even becomes a diagnosed problem."""
    groups: Dict[tuple, list] = {}
    for t in trades:
        if t.get("status") not in ("won", "lost"):
            continue
        ctx = t.get("ctx") or {}
        won = t["status"] == "won"
        keys = [("pair_rule", f"{pair_display(t['pair'], t['source'])} · {t.get('rule_label') or 'manual'}", t["pair"] + "|" + (t.get("rule") or "manual"))]
        if "hour" in ctx:
            keys.append(("hour", str(ctx["hour"]), ctx["hour"]))
        if "aligned" in ctx:
            keys.append(("against" if not ctx["aligned"] else "aligned", "", None))
        if "vol_pct" in ctx:
            v = ctx["vol_pct"]
            keys.append(("low_vol" if v < 25 else "high_vol" if v > 90 else "mid_vol", "", None))
        for kind, label, val in keys:
            groups.setdefault((kind, label, val), []).append(won)
    closed = [t for t in trades if t.get("status") in ("won", "lost")]
    total_wr = sum(1 for t in closed if t["status"] == "won") / len(closed) * 100 if closed else 0.0
    problems = []
    for (kind, label, val), res in groups.items():
        if kind not in DIAG or len(res) < min_n:
            continue
        wr = sum(res) / len(res) * 100
        if wr < breakeven:
            problems.append({"kind": kind, "key": val, "label": label, "n": len(res), "losses": len(res) - sum(res),
                             "winrate": wr, "text": DIAG[kind].format(k=label)})
    problems.sort(key=lambda x: (x["winrate"], -x["n"]))
    return {"trades": len(closed), "winrate": total_wr, "losses": sum(1 for t in closed if t["status"] == "lost"),
            "breakeven": breakeven, "problems": problems}


def fixes_from(problems: List[dict]) -> dict:
    f = {"hours": [], "pair_rules": [], "trend_align": False, "skip_low_vol": False, "skip_high_vol": False}
    for p in problems:
        if p["kind"] == "hour":
            f["hours"].append(int(p["key"]))
        elif p["kind"] == "pair_rule" and not str(p["key"]).endswith("|manual"):
            f["pair_rules"].append(p["key"])
        elif p["kind"] == "against":
            f["trend_align"] = True
        elif p["kind"] == "low_vol":
            f["skip_low_vol"] = True
        elif p["kind"] == "high_vol":
            f["skip_high_vol"] = True
    return f


def blocked_by(fixes: dict, pair: str, rule: str, ctx: dict) -> Optional[str]:
    if not fixes:
        return None
    if ctx["hour"] in fixes.get("hours", []):
        return f"hora {ctx['hour']}h bloqueada"
    if f"{pair}|{rule}" in fixes.get("pair_rules", []):
        return "par/estratégia em quarentena"
    if fixes.get("trend_align") and not ctx["aligned"]:
        return "contra a tendência"
    if fixes.get("skip_low_vol") and ctx["vol_pct"] < 25:
        return "volatilidade baixa"
    if fixes.get("skip_high_vol") and ctx["vol_pct"] > 90:
        return "volatilidade extrema"
    return None


def build_router(db, get_user: Callable, get_account: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/hfx")

    async def log(uid: str, kind: str, msg: str):
        await db.bot_logs.insert_one({"log_id": uuid.uuid4().hex[:16], "user_id": uid, "kind": kind, "msg": msg,
                                      "scope": "hfx", "created_at": datetime.now(timezone.utc).isoformat()})

    async def open_trade(uid: str, pair: str, source: str, direction: str, amount: float, expiry: int, origin: str,
                         rule: Optional[str] = None, rule_lbl: Optional[str] = None) -> dict:
        if pair not in PAIR_NAME:
            raise HTTPException(404, "Par desconhecido")
        if source not in PAYOUT:
            raise HTTPException(400, "Fonte inválida")
        if direction not in ("CALL", "PUT"):
            raise HTTPException(400, "Direção inválida")
        if expiry not in EXPIRIES:
            raise HTTPException(400, "Expiração tem de ser 1 ou 3 minutos")
        if source == "real":
            df = await real_candles(pair)
            if not market_open(df):
                raise HTTPException(400, "Mercado forex fechado — usa os pares OTC")
        acc = await get_account(uid)
        if amount > acc["balance"]:
            raise HTTPException(400, "Saldo insuficiente")
        price = await current_price(pair, source)
        now = time.time()
        t = {"trade_id": uuid.uuid4().hex[:16], "user_id": uid, "pair": pair, "source": source, "direction": direction,
             "amount": float(amount), "payout": PAYOUT[source], "expiry": expiry, "entry_price": price,
             "opened_ts": now, "expires_ts": now + expiry * 60, "status": "open", "origin": origin,
             "opened_at": datetime.now(timezone.utc).isoformat(), "rule": rule, "rule_label": rule_lbl}
        try:
            t["ctx"] = entry_context(await get_candles(pair, source), direction)
        except HTTPException:
            pass
        await db.accounts.update_one({"user_id": uid}, {"$inc": {"balance": -float(amount)}})
        await db.hfx_trades.insert_one(dict(t))
        t.pop("_id", None)
        return t

    async def settle_due():
        now = time.time()
        due = await db.hfx_trades.find({"status": "open", "expires_ts": {"$lte": now}}, {"_id": 0}).to_list(500)
        for t in due:
            try:
                if t["source"] == "otc":
                    px = feed.price_at(t["pair"], int(t["expires_ts"]))
                else:
                    df = await real_candles(t["pair"])
                    if df.index[-1].timestamp() + 60 < t["expires_ts"] and now - t["expires_ts"] < 300:
                        continue  # wait for the candle covering expiry
                    px = float(df["close"].iloc[-1])
            except HTTPException:
                continue
            diff = px - t["entry_price"]
            if diff == 0:
                status, credit = "tie", t["amount"]
            elif (diff > 0) == (t["direction"] == "CALL"):
                status, credit = "won", t["amount"] * (1 + t["payout"])
            else:
                status, credit = "lost", 0.0
            profit = credit - t["amount"]
            res = await db.hfx_trades.update_one({"trade_id": t["trade_id"], "status": "open"}, {"$set": {
                "status": status, "exit_price": px, "profit": profit, "closed_at": datetime.now(timezone.utc).isoformat()}})
            if res.modified_count and credit:
                await db.accounts.update_one({"user_id": t["user_id"]}, {"$inc": {"balance": credit}})
            if res.modified_count and t["origin"] == "bot":
                await log(t["user_id"], "close", f"HFX {pair_display(t['pair'], t['source'])} {t['direction']} {t['expiry']}m: "
                                                 f"{'GANHOU' if status == 'won' else 'PERDEU' if status == 'lost' else 'EMPATE'} {profit:+.2f} $")

    async def user_plugins(uid: str) -> dict:
        doc = await db.hfx_plugins.find_one({"user_id": uid}, {"_id": 0})
        merged = {k: dict(v) for k, v in HFX_PLUGIN_DEFAULTS.items()}
        for k, v in ((doc or {}).get("plugins") or {}).items():
            if k in merged:
                merged[k].update(v)
        return merged

    async def today_profit(uid: str) -> float:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        docs = await db.hfx_trades.find({"user_id": uid, "origin": "bot", "status": {"$in": ["won", "lost", "tie"]},
                                         "opened_ts": {"$gte": start}}, {"_id": 0, "profit": 1}).to_list(5000)
        return sum(d["profit"] for d in docs)

    async def auto_fix(uid: str, bot: dict, force: bool = False) -> Optional[dict]:
        """Analyse the bot's last 200 closed trades and apply corrections for every losing pattern."""
        if not force and time.time() - bot.get("fix_ts", 0) < 600:
            return None
        # last 24h only -> quarantines/blocks expire by themselves once the losing pattern stops trading
        trades = await db.hfx_trades.find({"user_id": uid, "origin": "bot", "status": {"$in": ["won", "lost"]},
                                           "opened_ts": {"$gte": time.time() - 86400}},
                                          {"_id": 0}).sort("expires_ts", -1).to_list(200)
        an = loss_analysis(trades, 1 / (1 + PAYOUT[bot["source"]]) * 100)
        fx = fixes_from(an["problems"])
        old = bot.get("fixes") or {}
        await db.hfx_bots.update_one({"user_id": uid}, {"$set": {"fixes": fx, "fix_ts": time.time()}})
        if fx != old and an["problems"]:
            await log(uid, "fix", f"Análise de perdas: {len(an['problems'])} problema(s) corrigido(s) — " +
                      "; ".join(p["text"].split(" Correção")[0] for p in an["problems"][:3]))
        return {"analysis": an, "fixes": fx}

    async def run_bot(bot: dict):
        uid = bot["user_id"]
        if bot.get("auto_fix", True):
            await auto_fix(uid, bot)
        pnl = await today_profit(uid)
        if pnl <= -bot["daily_stop"] or pnl >= bot["daily_target"]:
            await db.hfx_bots.update_one({"user_id": uid}, {"$set": {"enabled": False}})
            await log(uid, "status", f"Robô HFX parado: {'stop diário atingido' if pnl < 0 else 'meta diária atingida'} ({pnl:+.2f} $)")
            return
        hour_ago = time.time() - 3600
        n_hour = await db.hfx_trades.count_documents({"user_id": uid, "origin": "bot", "opened_ts": {"$gte": hour_ago}})
        last_bar = bot.get("last_bar", {})
        plugins = await user_plugins(uid)
        for pair in bot["pairs"]:
            if n_hour >= bot["max_per_hour"]:
                break
            try:
                df = await get_candles(pair, bot["source"])
            except HTTPException:
                continue
            if bot["source"] == "real" and not market_open(df):
                continue
            if len(df) < 60:
                continue
            expiry, forced = bot["expiry"], None
            if bot["strategy"] == "plugins":
                forced = "confluence"
            elif bot["strategy"] == "optimized":
                stp = (bot.get("setups") or {}).get(pair.replace(".", "_"))
                if not stp:
                    continue
                forced, expiry = stp["rule"], int(stp["expiry"])
            a = await asyncio.to_thread(analyze_pair, df, bot["source"], expiry, True, plugins, forced, bot["min_votes"])
            if last_bar.get(pair.replace(".", "_")) == a["bar_ts"]:
                continue
            # only act on the candle that JUST closed (avoid late entries)
            if time.time() - (pd.Timestamp(a["bar_ts"]).timestamp() + 60) > 20:
                await db.hfx_bots.update_one({"user_id": uid}, {"$set": {f"last_bar.{pair.replace('.', '_')}": a["bar_ts"]}})
                continue
            await db.hfx_bots.update_one({"user_id": uid}, {"$set": {f"last_bar.{pair.replace('.', '_')}": a["bar_ts"]}})
            if not a["signal"] or a["best"]["winrate"] < bot["min_winrate"]:
                continue
            busy = await db.hfx_trades.find_one({"user_id": uid, "pair": pair, "status": "open", "origin": "bot"})
            if busy:
                continue
            ctx = entry_context(df, a["signal"])
            reason = blocked_by(bot.get("fixes") or {}, pair, a["best"]["rule"], ctx)
            if reason:
                await log(uid, "skip", f"HFX {pair_display(pair, bot['source'])} {a['signal']} ignorado pela correção automática: {reason}")
                continue
            ai_note = ""
            if bot.get("ai_filter"):
                closes = ", ".join(f"{x:.{decimals(x)}f}" for x in df["close"].iloc[-15:])
                v = await ai.ai_filter(
                    f"Opção binária {a['signal']} ({'sobe' if a['signal'] == 'CALL' else 'desce'}) em {pair_display(pair, bot['source'])}, "
                    f"expiração {expiry} min, payout {PAYOUT[bot['source']] * 100:.0f}% (equilíbrio {a['breakeven']:.1f}%).\n"
                    f"Estratégia: {a['best']['label']} — acerto recente {a['best']['winrate']:.1f}% em {a['best']['samples']} sinais "
                    f"(limite inferior 95%: {a['best']['lower_bound']:.1f}%).\n"
                    f"Contexto: {'a favor' if ctx['aligned'] else 'CONTRA'} a tendência EMA50 1m, RSI14 {ctx['rsi']}, "
                    f"volatilidade da vela no percentil {ctx['vol_pct']}, hora {ctx['hour']}h UTC.\n"
                    f"Últimos 15 fechos 1m: {closes}", timeout=8)
                if time.time() - (pd.Timestamp(a["bar_ts"]).timestamp() + 60) > 30:
                    await log(uid, "skip", f"HFX {pair_display(pair, bot['source'])}: resposta da IA demasiado tarde, entrada cancelada")
                    continue
                if not v["approve"]:
                    await log(uid, "ai", f"IA rejeitou HFX {a['signal']} {pair_display(pair, bot['source'])}: {v['reason']} ({v['confidence']}%)")
                    continue
                ai_note = f" · IA ✓ {v['confidence']}%: {v['reason']}"
            try:
                t = await open_trade(uid, pair, bot["source"], a["signal"], bot["amount"], expiry, "bot", a["best"]["rule"], a["best"]["label"])
            except HTTPException as e:
                await log(uid, "skip", f"HFX {pair_display(pair, bot['source'])}: {e.detail}")
                continue
            n_hour += 1
            await log(uid, "open", f"HFX {t['direction']} {pair_display(pair, bot['source'])} {expiry}m · "
                                   f"{a['best']['label']} ({a['best']['winrate']:.0f}% em {a['best']['samples']}) · {bot['amount']:.2f} ${ai_note}")

    async def loop():
        for p, _ in PAIRS:  # anchor OTC feed to the latest real forex price
            try:
                await real_candles(p)
            except Exception:
                logger.warning("no real anchor for %s", p)
        tick = 0
        while True:
            try:
                await settle_due()
                if tick % 5 == 0:
                    bots = await db.hfx_bots.find({"enabled": True}, {"_id": 0}).to_list(500)
                    minute = int(time.time() // 60)
                    for b in bots:
                        if _bot_minute.get(b["user_id"]) == minute and int(time.time()) % 60 > 25:
                            continue  # nothing new this minute
                        _bot_minute[b["user_id"]] = minute
                        try:
                            await run_bot({**HFX_BOT_DEFAULT, **b})
                        except Exception:
                            logger.exception("hfx bot")
            except Exception:
                logger.exception("hfx loop")
            tick += 1
            await asyncio.sleep(1)

    r.loop = loop  # type: ignore[attr-defined]

    @r.get("/pairs")
    async def pairs(source: str = "otc"):
        if source not in PAYOUT:
            raise HTTPException(400, "Fonte inválida")
        out = []
        for p, name in PAIRS:
            try:
                df = await get_candles(p, source)
            except HTTPException:
                continue
            last = float(df["close"].iloc[-1])
            ref = float(df["close"].iloc[-60]) if len(df) > 60 else float(df["close"].iloc[0])
            out.append({"pair": p, "display": pair_display(p, source), "price": last, "decimals": decimals(last),
                        "change_pct": (last - ref) / ref * 100, "open": source == "otc" or market_open(df)})
        return out

    @r.get("/candles")
    async def candles(pair: str, source: str = "otc", limit: int = 60):
        df = await get_candles(pair, source)
        price = await current_price(pair, source) if source == "otc" else float(df["close"].iloc[-1])
        d = df.iloc[-limit:]
        return {"pair": pair, "display": pair_display(pair, source), "source": source, "price": price, "decimals": decimals(price),
                "payout": PAYOUT[source], "open": source == "otc" or market_open(df), "server_ts": time.time(),
                "candles": [{"t": int(ix.timestamp()), "o": float(x.open), "h": float(x.high), "l": float(x.low), "c": float(x.close)}
                            for ix, x in d.iterrows()]}

    @r.get("/signals")
    async def signals(request: Request, source: str = "otc", expiry: int = 1):
        u = await get_user(request)
        plugins = await user_plugins(u["user_id"])
        if expiry not in EXPIRIES:
            raise HTTPException(400, "Expiração tem de ser 1 ou 3 minutos")
        out = []
        for p, _ in PAIRS:
            try:
                df = await get_candles(p, source)
            except HTTPException:
                continue
            if len(df) < 60:
                continue
            a = await asyncio.to_thread(analyze_pair, df, source, expiry, True, plugins)
            last = float(df["close"].iloc[-1])
            out.append({"pair": p, "display": pair_display(p, source), "price": last, "decimals": decimals(last),
                        "open": source == "otc" or market_open(df), **a})
        out.sort(key=lambda x: (x["signal"] is None, -(x["best"]["winrate"] if x["best"] else 0)))
        return out

    @r.post("/trade")
    async def trade(body: TradeIn, request: Request):
        u = await get_user(request)
        return await open_trade(u["user_id"], body.pair, body.source, body.direction, body.amount, body.expiry, "manual")

    @r.get("/trades")
    async def trades(request: Request):
        u = await get_user(request)
        uid = u["user_id"]
        open_t = await db.hfx_trades.find({"user_id": uid, "status": "open"}, {"_id": 0}).sort("expires_ts", 1).to_list(100)
        for t in open_t:
            try:
                px = await current_price(t["pair"], t["source"])
            except HTTPException:
                px = t["entry_price"]
            t["current_price"] = px
            t["winning"] = (px > t["entry_price"]) == (t["direction"] == "CALL") and px != t["entry_price"]
            t["display"] = pair_display(t["pair"], t["source"])
            t["decimals"] = decimals(px)
        closed = await db.hfx_trades.find({"user_id": uid, "status": {"$ne": "open"}}, {"_id": 0}).sort("expires_ts", -1).to_list(40)
        for t in closed:
            t["display"] = pair_display(t["pair"], t["source"])
            t["decimals"] = decimals(t["entry_price"])
        agg = await db.hfx_trades.aggregate([
            {"$match": {"user_id": uid, "status": {"$in": ["won", "lost"]}}},
            {"$group": {"_id": None, "n": {"$sum": 1}, "wins": {"$sum": {"$cond": [{"$eq": ["$status", "won"]}, 1, 0]}},
                        "profit": {"$sum": "$profit"}}}]).to_list(1)
        g = agg[0] if agg else {"n": 0, "wins": 0, "profit": 0.0}
        acc = await get_account(uid)
        return {"open": open_t, "closed": closed, "server_ts": time.time(), "balance": acc["balance"],
                "stats": {"trades": g["n"], "wins": g["wins"], "winrate": g["wins"] / g["n"] * 100 if g["n"] else 0,
                          "profit": g["profit"]}}

    @r.get("/analysis")
    async def analysis(request: Request, scope: str = "bot"):
        u = await get_user(request)
        if scope not in ("bot", "manual", "all"):
            raise HTTPException(400, "Âmbito inválido")
        q = {"user_id": u["user_id"], "status": {"$in": ["won", "lost"]}}
        if scope in ("bot", "manual"):
            q["origin"] = scope
        if scope == "bot":
            q["opened_ts"] = {"$gte": time.time() - 86400}
        trades = await db.hfx_trades.find(q, {"_id": 0}).sort("expires_ts", -1).to_list(200)
        bot = await db.hfx_bots.find_one({"user_id": u["user_id"]}, {"_id": 0}) or {}
        src = bot.get("source", "otc")
        an = loss_analysis(trades, 1 / (1 + PAYOUT[src]) * 100)
        recent = [{"display": pair_display(t["pair"], t["source"]), "direction": t["direction"], "expiry": t["expiry"],
                   "rule": t.get("rule_label") or "manual", "ctx": t.get("ctx"), "profit": t["profit"], "closed_at": t.get("closed_at")}
                  for t in trades if t["status"] == "lost"][:15]
        return {**an, "recent_losses": recent, "fixes": bot.get("fixes") or {}, "auto_fix": bot.get("auto_fix", True)}

    @r.post("/analysis/apply")
    async def analysis_apply(request: Request):
        u = await get_user(request)
        bot = await db.hfx_bots.find_one({"user_id": u["user_id"]}, {"_id": 0})
        if not bot:
            raise HTTPException(400, "Configura o robô HFX primeiro")
        res = await auto_fix(u["user_id"], {**HFX_BOT_DEFAULT, **bot}, force=True)
        return res

    @r.post("/analysis/reset")
    async def analysis_reset(request: Request):
        u = await get_user(request)
        await db.hfx_bots.update_one({"user_id": u["user_id"]}, {"$set": {"fixes": {}, "fix_ts": time.time()}})
        await log(u["user_id"], "fix", "Correções automáticas removidas")
        return {"ok": True}

    @r.get("/plugins")
    async def plugins_get(request: Request):
        u = await get_user(request)
        return {"plugins": await user_plugins(u["user_id"]), "meta": HFX_PLUGIN_META}

    @r.put("/plugins")
    async def plugins_put(body: HfxPluginsIn, request: Request):
        u = await get_user(request)
        clean = {}
        for k, v in body.plugins.items():
            if k not in HFX_PLUGIN_DEFAULTS:
                continue
            clean[k] = {"enabled": bool(v.get("enabled", False))}
            for p_, dv in HFX_PLUGIN_DEFAULTS[k].items():
                if p_ == "enabled" or p_ not in v:
                    continue
                try:
                    val = type(dv)(v[p_])
                except (TypeError, ValueError):
                    raise HTTPException(400, f"Parâmetro inválido: {k}.{p_}")
                lo, hi = HFX_PARAM_RANGES[p_]
                if not (lo <= val <= hi):
                    raise HTTPException(400, f"{HFX_PLUGIN_META[k]['params'][p_]} deve estar entre {lo} e {hi}")
                clean[k][p_] = val
        if "ema_mom" in clean and clean["ema_mom"].get("fast", 5) >= clean["ema_mom"].get("slow", 13):
            raise HTTPException(400, "A EMA rápida tem de ser menor que a lenta")
        await db.hfx_plugins.update_one({"user_id": u["user_id"]}, {"$set": {"plugins": clean}}, upsert=True)
        return {"plugins": await user_plugins(u["user_id"])}

    @r.post("/optimize")
    async def optimize_ep(body: HfxOptIn, request: Request):
        u = await get_user(request)
        if body.expiry not in EXPIRIES:
            raise HTTPException(400, "Expiração tem de ser 1 ou 3 minutos")
        plugins = await user_plugins(u["user_id"])
        out = []
        for p_, _ in PAIRS:
            try:
                df = await real_candles(p_)
            except HTTPException:
                continue
            res = await asyncio.to_thread(hfx_optimize, df, plugins, PAYOUT["real"], body.expiry)
            out.append({"pair": p_, "display": PAIR_NAME[p_], **res})
        out.sort(key=lambda x: (x["best"] is None, -(x["best"]["test"]["winrate"] if x["best"] else 0)))
        return {"expiry": body.expiry, "payout": PAYOUT["real"], "results": out}

    @r.get("/bot")
    async def bot_get(request: Request):
        u = await get_user(request)
        doc = await db.hfx_bots.find_one({"user_id": u["user_id"]}, {"_id": 0, "last_bar": 0, "fix_ts": 0})
        bot = {**HFX_BOT_DEFAULT, **(doc or {})}
        bot.pop("user_id", None)
        logs = await db.bot_logs.find({"user_id": u["user_id"], "scope": "hfx"}, {"_id": 0}).sort("created_at", -1).to_list(40)
        return {"bot": bot, "logs": logs, "today": await today_profit(u["user_id"]),
                "pairs": [{"pair": p, "name": n} for p, n in PAIRS]}

    @r.put("/bot")
    async def bot_put(body: HfxBotIn, request: Request):
        u = await get_user(request)
        if body.source not in PAYOUT:
            raise HTTPException(400, "Fonte inválida")
        if body.expiry not in EXPIRIES:
            raise HTTPException(400, "Expiração tem de ser 1 ou 3 minutos")
        pairs_ok = [p for p in body.pairs if p in PAIR_NAME]
        if body.strategy not in ("auto", "plugins", "optimized"):
            raise HTTPException(400, "Estratégia inválida")
        valid_rules = set(HFX_PLUGIN_DEFAULTS) | {"confluence"}
        setups = {}
        for k, v in body.setups.items():
            pair = k.replace("_", ".")
            rule = str(v.get("rule", ""))
            parts = rule.split("+")
            try:
                exp = int(v.get("expiry", 0))
            except (TypeError, ValueError):
                exp = 0
            if pair not in PAIR_NAME or exp not in EXPIRIES or not all(x in valid_rules for x in parts) or len(parts) > 2:
                raise HTTPException(400, f"Setup inválido para {k}")
            setups[pair.replace(".", "_")] = {"rule": rule, "expiry": exp, "label": rule_label(rule)}
        if body.strategy == "optimized" and body.enabled and not setups:
            raise HTTPException(400, "Corre o otimizador e envia setups para o robô primeiro")
        if body.enabled and not pairs_ok:
            raise HTTPException(400, "Escolhe pelo menos um par")
        if body.enabled:
            pnl = await today_profit(u["user_id"])
            if pnl <= -body.daily_stop or pnl >= body.daily_target:
                raise HTTPException(400, f"Limite diário já atingido ({pnl:+.2f} $). Ajusta o stop/meta ou volta amanhã.")
        prev = await db.hfx_bots.find_one({"user_id": u["user_id"]}, {"_id": 0, "enabled": 1}) or {}
        data = {**body.model_dump(), "pairs": pairs_ok, "setups": setups, "user_id": u["user_id"]}
        await db.hfx_bots.update_one({"user_id": u["user_id"]}, {"$set": data}, upsert=True)
        if body.enabled != prev.get("enabled", False):
            await log(u["user_id"], "status", "Robô HFX ativado" if body.enabled else "Robô HFX parado")
        return {"ok": True}

    return r
