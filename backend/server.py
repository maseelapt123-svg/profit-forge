from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import json
import time
import uuid
import asyncio
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

import httpx
import numpy as np
import pandas as pd
import yfinance as yf

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from strategies import STRATEGIES, CONF_DEFAULT, C12_LABELS, C20_LABELS, confirm12_matrix, confirm20_matrix, confirm_signals, simulate, confluence_detail, PLUGIN_DEFAULTS, PLUGIN_META, FEES, compute_signals, smc_analyze, atr, run_backtest, optimize, strategy_signals, trend_filtered, apply_filters, mtf_filtered, htf_trend, ema, rsi, vwap, sr_levels, fib_levels, detect_patterns  # noqa: E402
import hfx  # noqa: E402
import binance_exec  # noqa: E402
import metaapi_exec  # noqa: E402
import ea_gen  # noqa: E402
import httpx  # noqa: E402
import ai  # noqa: E402

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']

app = FastAPI()
logger = logging.getLogger("trading")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}

api = APIRouter(prefix="/api")

# ---------------------------------------------------------------- assets
ASSETS = {
    "crypto": [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
        ("BNB-USD", "BNB"), ("XRP-USD", "XRP"), ("ADA-USD", "Cardano"),
    ],
    "forex": [
        ("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"),
        ("AUDUSD=X", "AUD/USD"), ("USDCHF=X", "USD/CHF"), ("GC=F", "Ouro (XAU)"),
    ],
    "stocks": [
        ("AAPL", "Apple"), ("NVDA", "NVIDIA"), ("TSLA", "Tesla"),
        ("MSFT", "Microsoft"), ("AMZN", "Amazon"), ("META", "Meta"),
    ],
}
ASSET_INFO = {s: {"symbol": s, "name": n, "category": c} for c, lst in ASSETS.items() for s, n in lst}

TIMEFRAMES = {
    # tf: (yf interval, chart period, backtest period, resample rule)
    "1m": ("1m", "2d", "7d", None),
    "2m": ("2m", "3d", "60d", None),
    "3m": ("1m", "3d", "7d", "3min"),
    "5m": ("5m", "2d", "60d", None),
    "15m": ("15m", "5d", "60d", None),
    "1h": ("1h", "15d", "365d", None),
    "4h": ("1h", "60d", "720d", "4h"),
    "1d": ("1d", "1y", "5y", None),
}

_cache: Dict[tuple, tuple] = {}


def display(symbol: str) -> str:
    return symbol.replace("-USD", "/USD").replace("=X", "").replace("=F", "")


def _download(symbol: str, interval: str, period: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.columns = ["open", "high", "low", "close", "volume"]
    return df


async def get_df(symbol: str, tf: str, long: bool = False) -> pd.DataFrame:
    if symbol not in ASSET_INFO:
        raise HTTPException(404, "Ativo desconhecido")
    if tf not in TIMEFRAMES:
        raise HTTPException(400, "Timeframe inválido")
    interval, p_chart, p_bt, rule = TIMEFRAMES[tf]
    period = p_bt if long else p_chart
    key = (symbol, interval, period)
    ttl = 300 if interval == "1d" else 20 if interval == "1m" else 60
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        df = hit[1]
    else:
        df = await asyncio.to_thread(_download, symbol, interval, period)
        if df.empty:
            raise HTTPException(502, "Sem dados de mercado para este ativo")
        _cache[key] = (time.time(), df)
    if rule:
        df = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return df


HTF_MAP = {"1m": "15m", "2m": "15m", "3m": "15m", "5m": "1h", "15m": "4h", "1h": "4h", "4h": "1d", "1d": None}


async def get_htf(symbol: str, tf: str) -> Optional[pd.DataFrame]:
    """Higher timeframe used to confirm trend (e.g. 5m entries need 1H trend)."""
    h = HTF_MAP.get(tf)
    if not h:
        return None
    try:
        return await get_df(symbol, h, long=True)
    except HTTPException:
        return None


def price_decimals(p: float) -> int:
    if p >= 1000:
        return 2
    if p >= 10:
        return 3
    if p >= 1:
        return 4
    return 6

# ---------------------------------------------------------------- auth
class SessionIn(BaseModel):
    session_id: str


async def get_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado")
    token = auth[7:]
    s = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not s:
        raise HTTPException(401, "Sessão inválida")
    exp = s["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise HTTPException(401, "Sessão expirada")
    user = await db.users.find_one({"user_id": s["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(401, "Utilizador não encontrado")
    return user


@api.post("/auth/session")
async def auth_session(body: SessionIn):
    async with httpx.AsyncClient(timeout=15) as hc:
        r = await hc.get("https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                         headers={"X-Session-ID": body.session_id})
    if r.status_code != 200:
        raise HTTPException(401, "Sessão Google inválida")
    data = r.json()
    email = data["email"]
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"name": data.get("name"), "picture": data.get("picture")}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({"user_id": user_id, "email": email, "name": data.get("name"),
                                   "picture": data.get("picture"), "created_at": datetime.now(timezone.utc)})
    now = datetime.now(timezone.utc)
    await db.user_sessions.update_one({"session_token": data["session_token"]},  # idempotent: same session_id may be exchanged twice
                                      {"$set": {"user_id": user_id, "expires_at": now + timedelta(days=7), "created_at": now}},
                                      upsert=True)
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "created_at": 0})
    return {"session_token": data["session_token"], "user": user}


@api.get("/auth/me")
async def auth_me(request: Request):
    u = await get_user(request)
    u.pop("created_at", None)
    return u


@api.post("/auth/logout")
async def auth_logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        await db.user_sessions.delete_one({"session_token": auth[7:]})
    return {"ok": True}

# ---------------------------------------------------------------- markets
async def quote(symbol: str) -> Optional[dict]:
    try:
        df = await get_df(symbol, "1h")
    except HTTPException:
        return None
    last = float(df["close"].iloc[-1])
    ref_idx = df.index[-1] - pd.Timedelta(hours=24)
    prev_df = df[df.index <= ref_idx]
    prev = float(prev_df["close"].iloc[-1]) if len(prev_df) else float(df["close"].iloc[0])
    spark = [round(float(x), 6) for x in df["close"].iloc[-24:].tolist()]
    return {**ASSET_INFO[symbol], "display": display(symbol), "price": last,
            "change_pct": (last - prev) / prev * 100 if prev else 0.0,
            "decimals": price_decimals(last), "spark": spark}


@api.get("/markets")
async def markets(category: str = "crypto"):
    if category not in ASSETS:
        raise HTTPException(400, "Categoria inválida")
    res = await asyncio.gather(*[quote(s) for s, _ in ASSETS[category]])
    return [r for r in res if r]


@api.get("/candles")
async def candles(symbol: str, tf: str = "1h", limit: int = 120):
    full = await get_df(symbol, tf)
    smc = smc_analyze(full)
    df = full.iloc[-limit:]
    ind = {
        "ema20": ema(full["close"], 20).iloc[-limit:], "ema50": ema(full["close"], 50).iloc[-limit:],
        "vwap": vwap(full).iloc[-limit:], "rsi": rsi(full["close"], 14).iloc[-limit:],
    }
    offset = smc["_n"] - len(df)
    out = [{"t": int(ix.timestamp()), "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close)}
           for ix, r in df.iterrows()]

    def shift(items):
        res = []
        for it in items:
            it = dict(it)
            for k in ("idx", "break_idx"):
                if k in it:
                    it[k] = it[k] - offset
            res.append(it)
        return res
    last = float(df["close"].iloc[-1])
    return {
        **ASSET_INFO[symbol], "display": display(symbol), "tf": tf, "price": last, "decimals": price_decimals(last),
        "candles": out,
        "order_blocks": shift(smc["order_blocks"]),
        "fvgs": shift(smc["fvgs"]),
        "structure": [s for s in shift(smc["structure"]) if s["break_idx"] >= 0],
        "trend": smc["trend"],
        "indicators": {k: [None if pd.isna(x) else round(float(x), 8) for x in v.tolist()] for k, v in ind.items()},
        "sr_levels": sr_levels(full.iloc[-300:]),
        "fib": fib_levels(df),
    }


@api.get("/patterns")
async def patterns(category: str = "crypto", tf: str = "1h"):
    if category not in ASSETS:
        raise HTTPException(400, "Categoria inválida")

    async def one(sym):
        try:
            df = await get_df(sym, tf)
        except HTTPException:
            return None
        found = []
        for back in (2, 3, 4):  # last 3 closed candles
            i = len(df) - back
            for p in detect_patterns(df, i):
                found.append({**p, "bars_ago": back - 1, "time": df.index[i].isoformat()})
        last = float(df["close"].iloc[-1])
        return {"symbol": sym, "display": display(sym), "name": ASSET_INFO[sym]["name"], "price": last,
                "decimals": price_decimals(last), "patterns": found,
                "trend": "alta" if last > float(ema(df["close"], 50).iloc[-1]) else "baixa"}
    res = [r for r in await asyncio.gather(*[one(s) for s, _ in ASSETS[category]]) if r]
    res.sort(key=lambda x: -len(x["patterns"]))
    return res

# ---------------------------------------------------------------- plugins
PARAM_RANGES = {"swing": (1, 20), "length": (2, 200), "oversold": (1, 50), "overbought": (50, 99),
                "fast": (2, 200), "slow": (3, 400), "signal": (2, 100), "mult": (0.5, 5),
                "ema": (5, 100), "trend": (20, 300), "atr_len": (5, 50), "st_mult": (1, 6), "stoch": (5, 50), "lvl": (5, 40),
                "threshold": (10, 50), "tenkan": (5, 30), "kijun": (10, 60), "step": (0.005, 0.1), "max_step": (0.05, 0.5),
                "wick": (1, 5), "tol": (0.05, 1), "window": (2, 50)}


class PluginsIn(BaseModel):
    plugins: Dict[str, Dict[str, Any]]


async def user_plugins(user_id: str) -> dict:
    doc = await db.plugins.find_one({"user_id": user_id}, {"_id": 0})
    merged = json.loads(json.dumps(PLUGIN_DEFAULTS))
    if doc:
        for k, v in doc.get("plugins", {}).items():
            if k in merged:
                merged[k].update(v)
    return merged


@api.get("/plugins")
async def get_plugins(request: Request):
    u = await get_user(request)
    return {"plugins": await user_plugins(u["user_id"]), "meta": PLUGIN_META}


@api.put("/plugins")
async def put_plugins(body: PluginsIn, request: Request):
    u = await get_user(request)
    clean = {}
    for k, v in body.plugins.items():
        if k not in PLUGIN_DEFAULTS:
            continue
        clean[k] = {"enabled": bool(v.get("enabled", False))}
        for p, dv in PLUGIN_DEFAULTS[k].items():
            if p == "enabled" or p not in v:
                continue
            try:
                val = type(dv)(v[p])
            except (TypeError, ValueError):
                raise HTTPException(400, f"Parâmetro inválido: {k}.{p}")
            lo, hi = PARAM_RANGES.get(p, (1, 500))
            if not (lo <= val <= hi):
                raise HTTPException(400, f"{PLUGIN_META[k]['params'][p]} deve estar entre {lo} e {hi}")
            clean[k][p] = val
        if k == "ema_cross" and clean[k].get("fast", 9) >= clean[k].get("slow", 21):
            raise HTTPException(400, "A EMA rápida tem de ser menor que a lenta")
        if k == "rsi" and clean[k].get("oversold", 30) >= clean[k].get("overbought", 70):
            raise HTTPException(400, "Sobrevenda tem de ser menor que sobrecompra")
    await db.plugins.update_one({"user_id": u["user_id"]}, {"$set": {"plugins": clean, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return {"plugins": await user_plugins(u["user_id"])}

# ---------------------------------------------------------------- signals
def build_signal(symbol: str, df: pd.DataFrame, plugins: dict, lookback: int = 3, htf: Optional[pd.DataFrame] = None, tf: str = "1h") -> dict:
    a = atr(df).iloc[-1]
    last = float(df["close"].iloc[-1])
    votes, triggered = 0, []
    for name, cfg in plugins.items():
        if not cfg.get("enabled"):
            continue
        sig = compute_signals(name, df, cfg)
        sig = trend_filtered(df, sig)
        sig = mtf_filtered(df, sig, htf)
        recent = sig[-lookback:]
        nz = recent[recent != 0]
        if len(nz):
            v = int(nz[-1])
            votes += v
            triggered.append({"plugin": name, "label": PLUGIN_META[name]["label"], "dir": v})
    enabled = sum(1 for c in plugins.values() if c.get("enabled"))
    direction = "BUY" if votes > 0 else "SELL" if votes < 0 else "NEUTRAL"
    trend = "alta" if last > float(ema(df["close"], 200).iloc[-1]) else "baixa"
    htf_dir = int(htf_trend(df, htf)[-1]) if htf is not None and not htf.empty else None
    sl_m, rr = 1.5, 2.0
    sl = last - sl_m * a if direction == "BUY" else last + sl_m * a
    tp = last + rr * sl_m * a if direction == "BUY" else last - rr * sl_m * a
    return {
        **ASSET_INFO[symbol], "display": display(symbol), "direction": direction, "price": last,
        "entry": last, "stop_loss": float(sl), "take_profit": float(tp), "decimals": price_decimals(last),
        "confidence": round(abs(votes) / enabled * 100) if enabled else 0,
        "triggered": triggered, "trend": trend, "rsi": round(float(rsi(df["close"]).iloc[-1]), 1),
        "htf": HTF_MAP.get(tf), "htf_trend": htf_dir,
    }


@api.get("/signals")
async def signals(request: Request, category: str = "crypto", tf: str = "1h"):
    u = await get_user(request)
    plugins = await user_plugins(u["user_id"])
    if category not in ASSETS:
        raise HTTPException(400, "Categoria inválida")

    async def one(sym):
        try:
            df = await get_df(sym, tf)
            htf = await get_htf(sym, tf)
            return build_signal(sym, df, plugins, htf=htf, tf=tf)
        except HTTPException:
            return None
    res = [r for r in await asyncio.gather(*[one(s) for s, _ in ASSETS[category]]) if r]
    res.sort(key=lambda x: (x["direction"] == "NEUTRAL", -x["confidence"]))
    return res

# ---------------------------------------------------------------- backtest
class BacktestIn(BaseModel):
    symbol: str
    tf: str = "1h"
    strategy: str = "smc"
    sl_atr: float = 1.5
    rr: float = 2.0
    risk_pct: float = 1.0
    capital: float = 10000
    trend_filter: bool = True
    breakeven: bool = True
    mtf: bool = False
    conf_votes: int = Field(2, ge=1, le=10)
    conf_score: float = Field(55, ge=40, le=90)
    c12_min: int = Field(10, ge=6, le=12)
    c20_min: int = Field(16, ge=10, le=20)
    partial_pct: float = Field(0, ge=0, le=90)
    partial_r: float = Field(1.0, ge=0.5, le=5)


@api.post("/backtest")
async def backtest(body: BacktestIn, request: Request):
    u = await get_user(request)
    plugins = await user_plugins(u["user_id"])
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, "Estratégia inválida")
    if not (0.1 <= body.risk_pct <= 10 and 0.3 <= body.sl_atr <= 10 and 0.5 <= body.rr <= 10 and body.capital > 0):
        raise HTTPException(400, "Parâmetros fora dos limites")
    df = await get_df(body.symbol, body.tf, long=True)
    if len(df) < 250:
        raise HTTPException(400, "Histórico insuficiente para backtest")
    fee = FEES[ASSET_INFO[body.symbol]["category"]]
    htf = await get_htf(body.symbol, body.tf) if body.mtf else None
    plugins["_conf"] = {"min_votes": body.conf_votes, "min_score": body.conf_score}
    plugins["_c12"] = {"min": body.c12_min}
    plugins["_c20"] = {"min": body.c20_min}
    res = await asyncio.to_thread(run_backtest, df, body.strategy, plugins, body.sl_atr, body.rr, body.risk_pct, body.capital,
                                  fee, body.trend_filter, body.breakeven, body.mtf and htf is not None, htf,
                                  body.partial_pct, body.partial_r)
    res.update({"symbol": body.symbol, "display": display(body.symbol), "tf": body.tf, "strategy": body.strategy,
                "mtf": body.mtf and htf is not None, "htf": HTF_MAP.get(body.tf),
                "from": df.index[0].isoformat(), "to": df.index[-1].isoformat(), "bars": len(df)})
    await db.backtests.insert_one({"backtest_id": uuid.uuid4().hex, "user_id": u["user_id"],
                                   "symbol": body.symbol, "tf": body.tf, "strategy": body.strategy,
                                   "metrics": res["metrics"], "created_at": datetime.now(timezone.utc)})
    return res

class OptimizeIn(BaseModel):
    symbol: str
    tf: str = "1h"


@api.post("/optimize")
async def optimize_ep(body: OptimizeIn, request: Request):
    u = await get_user(request)
    plugins = await user_plugins(u["user_id"])
    df = await get_df(body.symbol, body.tf, long=True)
    if len(df) < 600:
        raise HTTPException(400, "Histórico insuficiente para otimizar")
    fee = FEES[ASSET_INFO[body.symbol]["category"]]
    htf = await get_htf(body.symbol, body.tf)
    res = await asyncio.to_thread(optimize, df, plugins, fee, 1.0, 10000.0, 0.7, htf)
    res.update({"symbol": body.symbol, "display": display(body.symbol), "tf": body.tf, "htf": HTF_MAP.get(body.tf), "bars": len(df)})
    return res


OPT_TFS = ["1m", "2m", "3m", "5m", "15m", "1h", "4h", "1d"]
_opt_jobs: Dict[str, dict] = {}


class OptimizeAllIn(BaseModel):
    symbol: str


async def _optimize_all(job_id: str, symbol: str, plugins: dict):
    job = _opt_jobs[job_id]
    fee = FEES[ASSET_INFO[symbol]["category"]]
    for tf in OPT_TFS:
        job["current"] = tf
        entry = {"tf": tf, "htf": HTF_MAP.get(tf), "best": None, "tested": 0, "error": None}
        try:
            df = await get_df(symbol, tf, long=True)
            if len(df) < 600:
                entry["error"] = "Histórico insuficiente"
            else:
                htf = await get_htf(symbol, tf)
                r = await asyncio.to_thread(optimize, df, plugins, fee, 1.0, 10000.0, 0.7, htf)
                entry.update({"best": r["best"], "tested": r["tested"], "bars": len(df)})
        except HTTPException as e:
            entry["error"] = e.detail
        except Exception as e:  # keep the job alive for the other timeframes
            logger.exception("optimize-all %s %s", symbol, tf)
            entry["error"] = str(e)
        job["results"].append(entry)
    job["status"] = "done"
    job["current"] = None


@api.post("/optimize/all")
async def optimize_all_start(body: OptimizeAllIn, request: Request):
    u = await get_user(request)
    if body.symbol not in ASSET_INFO:
        raise HTTPException(404, "Ativo desconhecido")
    plugins = await user_plugins(u["user_id"])
    now = time.time()
    for jid in [j for j, v in _opt_jobs.items() if v["status"] == "done" and now - v["started"] > 3600]:
        _opt_jobs.pop(jid, None)
    if any(v["user_id"] == u["user_id"] and v["status"] == "running" for v in _opt_jobs.values()):
        raise HTTPException(429, "Já tens uma otimização em curso")
    job_id = uuid.uuid4().hex[:12]
    _opt_jobs[job_id] = {"job_id": job_id, "user_id": u["user_id"], "symbol": body.symbol, "display": display(body.symbol), "started": now,
                         "status": "running", "current": OPT_TFS[0], "total": len(OPT_TFS), "results": []}
    asyncio.create_task(_optimize_all(job_id, body.symbol, plugins))
    return {"job_id": job_id}


@api.get("/optimize/all/{job_id}")
async def optimize_all_status(job_id: str, request: Request):
    u = await get_user(request)
    job = _opt_jobs.get(job_id)
    if not job or job["user_id"] != u["user_id"]:
        raise HTTPException(404, "Otimização não encontrada")
    return {k: v for k, v in job.items() if k != "user_id"}

# ---------------------------------------------------------------- AI analysis
class AnalyzeIn(BaseModel):
    symbol: str
    tf: str = "1h"


@api.post("/ai/analyze")
async def ai_analyze(body: AnalyzeIn, request: Request):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
    u = await get_user(request)
    plugins = await user_plugins(u["user_id"])
    df = await get_df(body.symbol, body.tf)
    smc = smc_analyze(df)
    sig = build_signal(body.symbol, df, plugins)
    d = price_decimals(float(df["close"].iloc[-1]))
    recent = df.iloc[-40:]
    candles_txt = "\n".join(f"{ix:%Y-%m-%d %H:%M} O{r.open:.{d}f} H{r.high:.{d}f} L{r.low:.{d}f} C{r.close:.{d}f}" for ix, r in recent.iterrows())
    obs = [f"{o['dir']} OB {o['bottom']:.{d}f}-{o['top']:.{d}f}" for o in smc["order_blocks"]]
    fv = [f"{f['dir']} FVG {f['bottom']:.{d}f}-{f['top']:.{d}f}" for f in smc["fvgs"]]
    st = [f"{s['type']} {s['dir']} @ {s['price']:.{d}f}" for s in smc["structure"][-4:]]
    prompt = (
        f"Ativo: {display(body.symbol)} ({ASSET_INFO[body.symbol]['name']}), timeframe {body.tf}.\n"
        f"Preço atual: {sig['price']:.{d}f}. Tendência EMA200: {sig['trend']}. RSI14: {sig['rsi']}. ATR14: {float(atr(df).iloc[-1]):.{d}f}\n"
        f"Estrutura SMC recente: {', '.join(st) or 'nenhuma'}\n"
        f"Order Blocks ativos: {', '.join(obs) or 'nenhum'}\nFVGs abertos: {', '.join(fv) or 'nenhum'}\n"
        f"Sinal dos plugins: {sig['direction']} (confiança {sig['confidence']}%), "
        f"disparados: {', '.join(t['label'] for t in sig['triggered']) or 'nenhum'}\n"
        f"Últimas 40 velas:\n{candles_txt}"
    )
    system = (
        "És um analista de trading profissional especializado em Smart Money Concepts (estrutura de mercado, BOS/CHoCH, "
        "order blocks, fair value gaps, liquidez). Responde SEMPRE em português de Portugal, de forma concisa e estruturada "
        "em markdown simples com estas secções: **Viés**, **Zonas-chave**, **Plano de trade** (Entrada, Stop Loss, Take Profit, "
        "rácio R:R), **Invalidação**, **Gestão de risco**. Usa os níveis de preço fornecidos. Nunca prometas lucro; "
        "termina com uma linha curta a lembrar que não é aconselhamento financeiro."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"ai_{uuid.uuid4().hex}", system_message=system).with_model("openai", "gpt-5.4")

    async def gen():
        full = []
        try:
            async for ev in chat.stream_message(UserMessage(text=prompt)):
                if isinstance(ev, TextDelta):
                    full.append(ev.content)
                    yield f"data: {json.dumps({'t': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
            await db.analyses.insert_one({"analysis_id": uuid.uuid4().hex, "user_id": u["user_id"], "symbol": body.symbol,
                                          "tf": body.tf, "text": "".join(full), "created_at": datetime.now(timezone.utc)})
        except Exception as e:  # stream boundary: report to client
            logger.exception("AI error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------------------------------------------------------- paper trading
START_BALANCE = 10000.0


class OrderIn(BaseModel):
    symbol: str
    side: str  # BUY | SELL
    qty: float = Field(gt=0)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


async def get_account(user_id: str) -> dict:
    acc = await db.accounts.find_one({"user_id": user_id}, {"_id": 0})
    if not acc:
        acc = {"user_id": user_id, "balance": START_BALANCE, "start_balance": START_BALANCE, "created_at": datetime.now(timezone.utc)}
        await db.accounts.insert_one(dict(acc))
    return acc


def pnl_of(p: dict, price: float) -> float:
    d = 1 if p["side"] == "BUY" else -1
    return (price - p["entry"]) * p["qty"] * d


LEVERAGE = 500  # margin = notional / 500


async def _margin_qty(uid: str, acc: dict, qty: float, price: float) -> float:
    """Caps the size so the margin of all open positions never exceeds the equity (leverage 1:500)."""
    used = 0.0
    async for p in db.positions.find({"user_id": uid, "status": "open"}, {"_id": 0, "entry": 1, "qty": 1}):
        used += p["entry"] * p["qty"] / LEVERAGE
    free = acc["balance"] - used
    if free <= 0:
        return 0.0
    return max(0.0, min(qty, free * LEVERAGE / price))


async def _go_live(uid: str, bot: dict, pos: dict) -> bool:
    """Real-account execution. Returns False when the entry must be skipped.
    Live mode only sends crypto BUY entries (Binance Spot cannot short); everything else stays on paper."""
    if bot.get("live_mode") == "metatrader":
        return await _go_mt(uid, bot, pos)
    if bot.get("live_mode") != "binance":
        return True
    pair = binance_exec.to_pair(pos["symbol"])
    tag = display(pos["symbol"])
    if not pair or pos["side"] != "BUY":
        return True  # forex/stocks/shorts keep running on the simulated account
    if not binance_exec.configured():
        await bot_log(uid, "skip", f"{tag}: conta Binance não configurada — entrada real cancelada", pos["symbol"])
        return False
    quote = min(pos["qty"] * pos["entry"], float(bot.get("live_max_usd", 50)))
    try:
        r = await binance_exec.market_buy(pair, quote, f"st{pos['position_id']}")
    except (binance_exec.BinanceError, httpx.HTTPError) as e:
        await bot_log(uid, "skip", f"{tag}: Binance recusou a compra ({e})", pos["symbol"])
        return False
    if r["qty"] <= 0:
        await bot_log(uid, "skip", f"{tag}: ordem Binance sem execução ({r['status']})", pos["symbol"])
        return False
    d_stop = pos["entry"] - pos["stop_loss"]
    d_tp = pos["take_profit"] - pos["entry"]
    pos.update({"qty": r["qty"], "entry": r["price"], "stop_loss": r["price"] - d_stop, "take_profit": r["price"] + d_tp,
                "live": {"exchange": "binance", "env": binance_exec.env(), "pair": pair, "buy_order": r["order_id"]}})
    await bot_log(uid, "open", f"REAL ({binance_exec.env()}) Binance: comprado {r['qty']:g} {pair} @ {r['price']:.4f} ({quote:.2f} USDT)", pos["symbol"])
    return True


async def _mt_acc(uid: str) -> Optional[dict]:
    return await db.live_accounts.find_one({"user_id": uid, "kind": "mt"}, {"_id": 0})


async def _go_mt(uid: str, bot: dict, pos: dict) -> bool:
    """Send the entry to the MetaTrader account (with SL/TP on the broker, so it shows in the MT app)."""
    tag = display(pos["symbol"])
    mt_sym = metaapi_exec.to_mt_symbol(pos["symbol"], bot.get("mt_suffix", ""))
    if not mt_sym:
        return True  # stocks etc. stay on the simulated account
    acc = await _mt_acc(uid)
    if not metaapi_exec.configured() or not acc:
        await bot_log(uid, "skip", f"{tag}: conta MetaTrader não ligada — entrada cancelada", pos["symbol"])
        return False
    vol = metaapi_exec.lots(pos["symbol"], pos["qty"], float(bot.get("mt_max_lots", 0.1)))
    dec = price_decimals(pos["entry"])
    body = {"actionType": "ORDER_TYPE_BUY" if pos["side"] == "BUY" else "ORDER_TYPE_SELL", "symbol": mt_sym, "volume": vol,
            "stopLoss": round(pos["stop_loss"], dec), "takeProfit": round(pos["take_profit"], dec), "comment": "SmartTrade",
            "clientId": f"ST_{pos['position_id']}"[:26]}
    try:
        r = await metaapi_exec.trade(acc["account_id"], acc["region"], body)
    except (metaapi_exec.MetaApiError, httpx.HTTPError) as e:
        await bot_log(uid, "skip", f"{tag}: MetaTrader recusou a ordem ({e})", pos["symbol"])
        return False
    pos["live"] = {"exchange": "mt", "symbol": mt_sym, "volume": vol, "mt_position": r.get("positionId") or r.get("orderId")}
    await bot_log(uid, "open", f"MetaTrader: {pos['side']} {vol} lote(s) {mt_sym} (posição {pos['live']['mt_position']})", pos["symbol"])
    return True


async def _mt_trade(p: dict, body: dict, what: str) -> bool:
    acc = await _mt_acc(p["user_id"])
    if not acc or not metaapi_exec.configured():
        return False
    try:
        await metaapi_exec.trade(acc["account_id"], acc["region"], {**body, "positionId": str(p["live"]["mt_position"])})
        return True
    except (metaapi_exec.MetaApiError, httpx.HTTPError) as e:
        await bot_log(p["user_id"], "skip", f"{display(p['symbol'])}: MetaTrader {what} falhou ({e})", p["symbol"])
        return False


async def _live_sell(p: dict, qty: float, label: str) -> Optional[float]:
    """Sell `qty` on Binance for a live position. Returns the fill price, or None if it failed (logged)."""
    lv = p.get("live")
    if not lv:
        return None
    if lv.get("exchange") == "mt":
        if label == "c":  # full close (may already be closed by MT's own SL/TP — error is only logged)
            await _mt_trade(p, {"actionType": "POSITION_CLOSE_ID"}, "fecho")
        else:  # partial close then stop to break-even
            vol = max(0.01, round(lv["volume"] * qty / max(p["qty"], 1e-12), 2))
            if await _mt_trade(p, {"actionType": "POSITION_PARTIAL", "volume": vol}, "parcial"):
                await _mt_trade(p, {"actionType": "POSITION_MODIFY", "stopLoss": round(p["entry"], price_decimals(p["entry"])),
                                    "takeProfit": round(p["take_profit"], price_decimals(p["entry"]))}, "break-even")
        return None
    try:
        r = await binance_exec.market_sell(lv["pair"], qty, f"sx{p['position_id']}{label}"[:36])
        return r["price"] or None
    except (binance_exec.BinanceError, httpx.HTTPError) as e:
        await bot_log(p["user_id"], "skip", f"{display(p['symbol'])}: venda Binance falhou ({e}) — verifica a conta", p["symbol"])
        return None


async def close_position(p: dict, price: float, reason: str):
    if p.get("live"):
        fill = await _live_sell(p, p["qty"], "c")
        price = fill or price
    rest = pnl_of(p, price)
    pnl = rest + float(p.get("realized") or 0)  # include an already-banked partial take profit
    await db.positions.update_one({"position_id": p["position_id"]}, {"$set": {
        "status": "closed", "exit": price, "pnl": pnl, "reason": reason, "closed_at": datetime.now(timezone.utc).isoformat()}})
    await db.accounts.update_one({"user_id": p["user_id"]}, {"$inc": {"balance": rest}})
    return pnl


@api.get("/portfolio")
async def portfolio(request: Request):
    u = await get_user(request)
    await get_account(u["user_id"])
    open_pos = await db.positions.find({"user_id": u["user_id"], "status": "open"}, {"_id": 0}).to_list(200)
    prices = {}
    for s in {p["symbol"] for p in open_pos}:
        q = await quote(s)
        if q:
            prices[s] = q["price"]
    # auto-close on SL/TP
    for p in open_pos:
        px = prices.get(p["symbol"])
        if px is None:
            continue
        long = p["side"] == "BUY"
        if p.get("stop_loss") and ((long and px <= p["stop_loss"]) or (not long and px >= p["stop_loss"])):
            await close_position(p, px, "stop_loss"); p["status"] = "closed"
        elif p.get("take_profit") and ((long and px >= p["take_profit"]) or (not long and px <= p["take_profit"])):
            await close_position(p, px, "take_profit"); p["status"] = "closed"
    acc = await get_account(u["user_id"])
    positions, unreal = [], 0.0
    for p in open_pos:
        if p["status"] != "open":
            continue
        px = prices.get(p["symbol"], p["entry"])
        pl = pnl_of(p, px)
        unreal += pl
        positions.append({**p, "price": px, "pnl": pl, "pnl_pct": pl / (p["entry"] * p["qty"]) * 100,
                          "display": display(p["symbol"]), "decimals": price_decimals(px)})
    history = await db.positions.find({"user_id": u["user_id"], "status": "closed"}, {"_id": 0}).sort("closed_at", -1).to_list(100)
    for h in history:
        h["display"] = display(h["symbol"])
        h["decimals"] = price_decimals(h["entry"])
    realized = acc["balance"] - acc["start_balance"]
    wins = sum(1 for h in history if h["pnl"] > 0)
    hfx_open = await db.hfx_trades.find({"user_id": u["user_id"], "status": "open"}, {"_id": 0, "amount": 1}).to_list(500)
    locked = sum(t["amount"] for t in hfx_open)
    return {"balance": acc["balance"], "hfx_locked": locked, "equity": acc["balance"] + unreal + locked, "unrealized": unreal, "realized": realized,
            "start_balance": acc["start_balance"], "win_rate": (wins / len(history) * 100) if history else 0,
            "positions": positions, "history": history}


@api.post("/orders")
async def place_order(body: OrderIn, request: Request):
    u = await get_user(request)
    if body.side not in ("BUY", "SELL"):
        raise HTTPException(400, "Lado inválido")
    if body.symbol not in ASSET_INFO:
        raise HTTPException(404, "Ativo desconhecido")
    acc = await get_account(u["user_id"])
    q = await quote(body.symbol)
    if not q:
        raise HTTPException(502, "Preço indisponível")
    px = q["price"]
    notional = px * body.qty
    open_pos = await db.positions.find({"user_id": u["user_id"], "status": "open"}, {"_id": 0, "entry": 1, "qty": 1}).to_list(500)
    used = sum(p["entry"] * p["qty"] for p in open_pos)
    if notional + used > acc["balance"] * 10:
        raise HTTPException(400, "Tamanho excede a alavancagem máxima (10x) da conta simulada")
    long = body.side == "BUY"
    if body.stop_loss is not None and ((long and body.stop_loss >= px) or (not long and body.stop_loss <= px)):
        raise HTTPException(400, "Stop loss do lado errado do preço")
    if body.take_profit is not None and ((long and body.take_profit <= px) or (not long and body.take_profit >= px)):
        raise HTTPException(400, "Take profit do lado errado do preço")
    pos = {"position_id": uuid.uuid4().hex[:16], "user_id": u["user_id"], "symbol": body.symbol, "side": body.side,
           "qty": body.qty, "entry": px, "stop_loss": body.stop_loss, "take_profit": body.take_profit,
           "status": "open", "opened_at": datetime.now(timezone.utc).isoformat()}
    await db.positions.insert_one(dict(pos))
    return pos


@api.post("/positions/{position_id}/close")
async def close_pos(position_id: str, request: Request):
    u = await get_user(request)
    p = await db.positions.find_one({"position_id": position_id, "user_id": u["user_id"], "status": "open"}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Posição não encontrada")
    q = await quote(p["symbol"])
    if not q:
        raise HTTPException(502, "Preço indisponível")
    pnl = await close_position(p, q["price"], "manual")
    return {"ok": True, "pnl": pnl}


@api.post("/portfolio/reset")
async def reset_portfolio(request: Request):
    u = await get_user(request)
    await db.positions.delete_many({"user_id": u["user_id"]})
    await db.bot_logs.delete_many({"user_id": u["user_id"]})
    await db.hfx_trades.delete_many({"user_id": u["user_id"]})
    await db.accounts.update_one({"user_id": u["user_id"]}, {"$set": {"balance": START_BALANCE, "start_balance": START_BALANCE}}, upsert=True)
    return {"ok": True}


# ---------------------------------------------------------------- auto-trading bot (paper)
BOT_DEFAULT = {"enabled": False, "symbols": ["BTC-USD", "ETH-USD", "EURUSD=X"], "tf": "1h", "strategy": "smc", "trend_filter": True, "mtf": True, "setups": [],
               "risk_pct": 1.0, "sl_atr": 1.5, "rr": 2.0, "max_positions": 30, "ai_filter": False,
               "conf_votes": 2, "conf_score": 55.0, "c12_enabled": False, "c12_min": 10, "c12_max_positions": 30, "c12_tf": "1h",
               "c20_enabled": False, "c20_min": 16, "c20_max_positions": 30, "c20_tf": "1h", "c20_rr": 5.0, "c20_ptp_r": 2.0,
               "ptp_enabled": True, "ptp_pct": 50.0, "ptp_r": 1.0, "c20_pairs": [], "c12_pairs": [], "live_mode": "paper", "live_max_usd": 50.0,
               "mt_max_lots": 0.1, "mt_suffix": ""}


class BotSetup(BaseModel):
    symbol: str
    tf: str
    strategy: str
    sl_atr: float = Field(1.5, ge=0.5, le=5)
    rr: float = Field(2.0, ge=0.5, le=6)
    trend_filter: bool = True
    mtf: bool = False


class BotIn(BaseModel):
    enabled: bool
    symbols: List[str]
    tf: str = "1h"
    strategy: str = "combo"
    risk_pct: float = Field(1.0, ge=0.1, le=5)
    sl_atr: float = Field(1.5, ge=0.5, le=5)
    rr: float = Field(2.0, ge=0.5, le=6)
    max_positions: int = Field(30, ge=1, le=30)
    trend_filter: bool = True
    mtf: bool = True
    ai_filter: bool = False
    conf_votes: int = Field(2, ge=1, le=10)
    conf_score: float = Field(55, ge=40, le=90)
    c12_enabled: bool = False
    c12_min: int = Field(10, ge=6, le=12)
    c12_max_positions: int = Field(30, ge=1, le=30)
    c12_tf: str = "1h"
    c20_enabled: bool = False
    c20_min: int = Field(16, ge=10, le=20)
    c20_max_positions: int = Field(30, ge=1, le=30)
    c20_tf: str = "1h"
    c20_rr: float = Field(5.0, ge=5, le=10)
    c20_ptp_r: float = Field(2.0, ge=0.5, le=5)
    c20_pairs: List[Dict[str, Any]] = []
    c12_pairs: List[Dict[str, Any]] = []
    live_mode: str = Field("paper", pattern="^(paper|binance|metatrader)$")
    live_max_usd: float = Field(50, ge=5, le=100000)
    mt_max_lots: float = Field(0.1, ge=0.01, le=50)
    mt_suffix: str = Field("", max_length=8)
    ptp_enabled: bool = True
    ptp_pct: float = Field(50, ge=10, le=90)
    ptp_r: float = Field(1.0, ge=0.5, le=5)
    setups: List[BotSetup] = []


async def get_bot(user_id: str) -> dict:
    doc = await db.bots.find_one({"user_id": user_id}, {"_id": 0})
    return {**BOT_DEFAULT, **(doc or {}), "user_id": user_id}


async def bot_log(user_id: str, kind: str, msg: str, symbol: Optional[str] = None):
    await db.bot_logs.insert_one({"log_id": uuid.uuid4().hex[:16], "user_id": user_id, "kind": kind, "msg": msg,
                                  "symbol": symbol, "created_at": datetime.now(timezone.utc).isoformat()})


async def check_exits(user_id: str):
    open_pos = await db.positions.find({"user_id": user_id, "status": "open"}, {"_id": 0}).to_list(200)
    for p in open_pos:
        q = await quote(p["symbol"])
        if not q:
            continue
        px, long = q["price"], p["side"] == "BUY"
        reason = None
        if p.get("stop_loss") and ((long and px <= p["stop_loss"]) or (not long and px >= p["stop_loss"])):
            reason = "stop_loss"
        elif p.get("take_profit") and ((long and px >= p["take_profit"]) or (not long and px <= p["take_profit"])):
            reason = "take_profit"
        if not reason and p.get("ptp_pct") and not p.get("ptp_done") and p.get("stop_dist"):
            d = 1 if long else -1
            lvl = p["entry"] + d * p["stop_dist"] * p["ptp_r"]
            if (long and px >= lvl) or (not long and px <= lvl):
                q = p["qty"] * p["ptp_pct"] / 100
                if p.get("live"):
                    fill = await _live_sell(p, q, "p")
                    lvl = fill or lvl
                part = (lvl - p["entry"]) * q * d
                await db.positions.update_one({"position_id": p["position_id"]}, {
                    "$set": {"ptp_done": True, "stop_loss": p["entry"], "be": True},
                    "$inc": {"qty": -q, "realized": part}})
                await db.accounts.update_one({"user_id": user_id}, {"$inc": {"balance": part}})
                await bot_log(user_id, "ptp", f"{display(p['symbol'])}: parcial {p['ptp_pct']:.0f}% fechada a +{p['ptp_r']:g}R ({part:+.2f} $), stop em break-even", p["symbol"])
                continue
        if not reason and p.get("stop_dist") and not p.get("be"):
            one_r = p["entry"] + (1 if long else -1) * p["stop_dist"]
            if (long and px >= one_r) or (not long and px <= one_r):
                await db.positions.update_one({"position_id": p["position_id"]}, {"$set": {"stop_loss": p["entry"], "be": True}})
                await bot_log(user_id, "be", f"{display(p['symbol'])}: stop movido para break-even (+1R atingido)", p["symbol"])
        if reason:
            # simulated resting stop/limit order: fill at the order level, not at the (later) polled price
            fill = p["stop_loss"] if reason == "stop_loss" else p["take_profit"]
            pnl = await close_position(p, fill, reason)
            if p.get("source") == "bot":
                await bot_log(user_id, "close", f"{display(p['symbol'])} fechado por {'stop' if reason == 'stop_loss' else 'alvo'}: {pnl:+.2f} $", p["symbol"])


_bot_locks: Dict[str, asyncio.Lock] = {}

BOT_DIAG = {
    "setup": "{k}: perde dinheiro em conta real do robô (PF {pf:.2f}). Correção: quarentena desta configuração até reotimizar.",
    "hour": "As entradas às {k}h UTC perdem mais. Correção: o robô deixa de entrar a esta hora.",
    "against_htf": "Entradas contra a tendência do timeframe superior perdem mais. Correção: confirmação do TF superior em todos os setups.",
    "stops": "{k}% das operações saem no stop — stop demasiado curto ou entradas cedo demais. Correção: stop 0,5x ATR mais largo.",
}


async def bot_loss_analysis(uid: str) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    trades = await db.positions.find({"user_id": uid, "source": "bot", "status": "closed", "closed_at": {"$gte": since}},
                                     {"_id": 0}).sort("closed_at", -1).to_list(300)
    groups: Dict[tuple, list] = {}
    for t in trades:
        ctx = t.get("ctx") or {}
        key = t.get("setup") or f"{t['symbol']}|?"
        groups.setdefault(("setup", key), []).append(t["pnl"])
        if "hour" in ctx:
            groups.setdefault(("hour", ctx["hour"]), []).append(t["pnl"])
        if ctx.get("htf_aligned") is False:
            groups.setdefault(("against_htf", ""), []).append(t["pnl"])
    problems = []
    for (kind, k), pnls in groups.items():
        if len(pnls) < 6:
            continue
        gp = sum(x for x in pnls if x > 0)
        gl = -sum(x for x in pnls if x <= 0)
        pf = gp / gl if gl > 0 else 99.0
        if pf < 1:
            sym, tf = (str(k).split("|") + ["?"])[:2]
            label = f"{display(sym)} {tf.upper()}" if kind == "setup" else str(k)
            problems.append({"kind": kind, "key": k, "label": label, "n": len(pnls), "pnl": sum(pnls), "pf": pf,
                             "winrate": sum(1 for x in pnls if x > 0) / len(pnls) * 100,
                             "text": BOT_DIAG[kind].format(k=label, pf=pf)})
    if len(trades) >= 8:
        sl = sum(1 for t in trades if t.get("reason") == "stop_loss") / len(trades) * 100
        if sl > 65:
            problems.append({"kind": "stops", "key": round(sl), "label": f"{sl:.0f}%", "n": len(trades), "pnl": 0, "pf": 0,
                             "winrate": 0, "text": BOT_DIAG["stops"].format(k=f"{sl:.0f}")})
    problems.sort(key=lambda x: x["pnl"])
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return {"trades": len(trades), "winrate": wins / len(trades) * 100 if trades else 0.0, "pnl": sum(t["pnl"] for t in trades),
            "losses": len(trades) - wins, "problems": problems,
            "recent_losses": [{"display": display(t["symbol"]), "tf": t.get("tf"), "side": t["side"], "pnl": t["pnl"],
                               "reason": t.get("reason"), "ctx": t.get("ctx"), "closed_at": t.get("closed_at")}
                              for t in trades if t["pnl"] <= 0][:15]}


async def bot_auto_fix(uid: str, force: bool = False) -> Optional[dict]:
    bot = await get_bot(uid)
    if not force and (not bot.get("auto_fix", True) or time.time() - bot.get("fix_ts", 0) < 600):
        return None
    an = await bot_loss_analysis(uid)
    fx = {"paused": [], "hours": [], "force_mtf": False, "widen_stop": False}
    for p in an["problems"]:
        if p["kind"] == "setup":
            fx["paused"].append(p["key"])
        elif p["kind"] == "hour":
            fx["hours"].append(int(p["key"]))
        elif p["kind"] == "against_htf":
            fx["force_mtf"] = True
        elif p["kind"] == "stops":
            fx["widen_stop"] = True
    old = bot.get("fixes") or {}
    await db.bots.update_one({"user_id": uid}, {"$set": {"fixes": fx, "fix_ts": time.time()}}, upsert=True)
    if fx != old and an["problems"]:
        await bot_log(uid, "fix", f"Análise de perdas: {len(an['problems'])} problema(s) corrigido(s) — " +
                      "; ".join(p["text"].split(" Correção")[0] for p in an["problems"][:3]))
    return {"analysis": an, "fixes": fx}


async def run_bot_cycle(bot: dict) -> int:
    lock = _bot_locks.setdefault(bot["user_id"], asyncio.Lock())
    async with lock:
        return await _run_bot_cycle(bot)


STREAMS = {
    # independent entry streams of the main bot: own TF, min confirmations, R:R and position cap
    "c12": {"name": "12C", "matrix": confirm12_matrix, "labels": C12_LABELS, "n": 12},
    "c20": {"name": "20C", "matrix": confirm20_matrix, "labels": C20_LABELS, "n": 20},
}


async def _run_stream(uid: str, bot: dict, kind: str) -> int:
    """Separate entry stream ('12 Confirmações' / 'Sniper 20'). Tagged {kind}=True, independent of the main strategy."""
    st = STREAMS[kind]
    opened = 0
    tf0, need0 = bot.get(f"{kind}_tf") or "1h", int(bot.get(f"{kind}_min", 10))
    rr0 = float(bot.get(f"{kind}_rr") or bot["rr"])
    pairs = {p["symbol"]: p for p in (bot.get(f"{kind}_pairs") or [])}
    fixes = bot.get("fixes") or {}
    if datetime.now(timezone.utc).hour in fixes.get("hours", []):
        return 0
    for sym in bot["symbols"]:
        if opened >= 2:  # avoid opening a basket of correlated trades on the same candle
            break
        ov = pairs.get(sym)
        if ov and not ov.get("enabled", True):
            continue  # optimiser found no profitable TF/R:R for this pair
        tf, need, rr = (ov["tf"], int(ov["min"]), float(ov["rr"])) if ov else (tf0, need0, rr0)
        if tf not in TIMEFRAMES:
            continue
        htf_tf = HTF_MAP.get(tf)
        if sym not in ASSET_INFO:
            continue
        try:
            df = await get_df(sym, tf)
        except HTTPException:
            continue
        if len(df) < 260:
            continue
        row = (await asyncio.to_thread(st["matrix"], df))[-2]
        up, dn = int((row > 0).sum()), int((row < 0).sum())
        s = 1 if up >= need else -1 if dn >= need else 0
        if s == 0:
            continue
        key = f"{kind}|{sym}|{tf}"
        skey = key.replace(".", "_")
        bar_ts = df.index[-2].isoformat()
        if bot.get("last_bar", {}).get(skey) == bar_ts:
            continue
        await db.bots.update_one({"user_id": uid}, {"$set": {f"last_bar.{skey}": bar_ts}}, upsert=True)
        side = "BUY" if s == 1 else "SELL"
        tag = f"{st['name']} {display(sym)} {tf.upper()}"
        if htf_tf:
            try:
                hdf = await get_df(sym, htf_tf)
                if int(htf_trend(hdf, hdf)[-1]) != s:
                    await bot_log(uid, "skip", f"{tag} {side} ignorado: contra a tendência {htf_tf.upper()}", sym)
                    continue
            except HTTPException:
                pass
        price = float(df["close"].iloc[-1])
        existing = await db.positions.find_one({"user_id": uid, "status": "open", "setup": key}, {"_id": 0})
        if existing:
            if existing["side"] == side:
                continue
            pnl = await close_position(existing, price, "signal")
            await bot_log(uid, "close", f"{tag} fechado por confirmações contrárias: {pnl:+.2f} $", sym)
        if await db.positions.count_documents({"user_id": uid, "status": "open", kind: True}) >= bot.get(f"{kind}_max_positions", 30):
            await bot_log(uid, "skip", f"{tag} {side} ignorado: limite de posições {st['name']}", sym)
            continue
        a = float(atr(df).iloc[-1])
        if a <= 0:
            continue
        stop = bot["sl_atr"] * a
        if stop < 8 * FEES[ASSET_INFO[sym]["category"]] * price:
            continue
        acc = await get_account(uid)
        qty = await _margin_qty(uid, acc, (acc["balance"] * bot["risk_pct"] / 100) / stop, price)
        if qty <= 0:
            await bot_log(uid, "skip", f"{tag} ignorado: margem livre insuficiente (alavancagem 1:{LEVERAGE})", sym)
            continue
        d = 1 if side == "BUY" else -1
        n_ok = up if s == 1 else dn
        pos = {"position_id": uuid.uuid4().hex[:16], "user_id": uid, "symbol": sym, "side": side, "qty": float(qty),
               "entry": price, "stop_loss": price - d * stop, "take_profit": price + d * stop * rr,
               "status": "open", "source": "bot", "setup": key, "tf": tf, "stop_dist": float(stop), kind: True,
               "ctx": {"hour": datetime.now(timezone.utc).hour, "confirmations": n_ok},
               "opened_at": datetime.now(timezone.utc).isoformat(), **_ptp_fields(bot, kind)}
        if not await _go_live(uid, bot, pos):
            continue
        await db.positions.insert_one(dict(pos))
        opened += 1
        dec = price_decimals(price)
        await bot_log(uid, "open", f"{'COMPRA' if s == 1 else 'VENDA'} {tag} · {n_ok}/{st['n']} confirmações · R:R 1:{rr:g} @ {price:.{dec}f} · SL {pos['stop_loss']:.{dec}f} · TP {pos['take_profit']:.{dec}f}", sym)
    return opened


def _ptp_fields(bot: dict, kind: str = "") -> dict:
    if not bot.get("ptp_enabled"):
        return {}
    r = float(bot.get("c20_ptp_r", 2.0)) if kind == "c20" else float(bot.get("ptp_r", 1.0))
    return {"ptp_pct": float(bot.get("ptp_pct", 50)), "ptp_r": r}


@api.get("/confirm12")
async def confirm12_ep(request: Request, symbol: str, tf: str = "1h", min: int = 10, set: str = "c12"):
    await get_user(request)
    if symbol not in ASSET_INFO or tf not in TIMEFRAMES or set not in STREAMS:
        raise HTTPException(400, "Ativo, timeframe ou conjunto inválido")
    df = await get_df(symbol, tf)
    if len(df) < 260:
        raise HTTPException(400, "Histórico insuficiente")
    st = STREAMS[set]
    row = (await asyncio.to_thread(st["matrix"], df))[-2]
    up, dn = int((row > 0).sum()), int((row < 0).sum())
    sig = "BUY" if up >= min else "SELL" if dn >= min else None
    return {"symbol": symbol, "display": display(symbol), "tf": tf, "min": min, "n": st["n"], "up": up, "down": dn, "signal": sig,
            "checks": [{"label": lbl, "state": int(v)} for lbl, v in zip(st["labels"], row)]}


class SimItem(BaseModel):
    kind: str = "setup"  # setup | c12 | c20
    symbol: str
    tf: str
    strategy: str = "smc"
    sl_atr: float = Field(1.5, ge=0.5, le=5)
    rr: float = Field(2.0, ge=0.5, le=10)
    trend_filter: bool = True
    mtf: bool = False
    min: int = Field(10, ge=6, le=20)


class SimIn(BaseModel):
    items: List[SimItem]
    capital: float = Field(10000, ge=10, le=10_000_000)
    risk_pct: float = Field(1.0, ge=0.1, le=10)
    days: int = Field(30, ge=7, le=365)
    partial_pct: float = Field(0, ge=0, le=90)
    ai: bool = False


_sim_jobs: Dict[str, dict] = {}
SIM_AI_CAP = 150  # max AI evaluations per simulation (cost/time); strategies themselves are unlimited


def _r_stats(trades: list, capital: float, risk_pct: float, days: int = 30) -> dict:
    """Daily compounding: every trade risks risk_pct of the equity at the START of its closing day, so trades that
    run at the same time do not compound on top of each other (per-trade compounding inflates the result)."""
    n = len(trades)
    w = sum(1 for t in trades if t["r"] > 0)
    r = sum(t["r"] for t in trades)
    by_day: Dict[str, float] = {}
    for t in trades:
        d = pd.Timestamp(t["closed"]).strftime("%Y-%m-%d")
        by_day[d] = by_day.get(d, 0.0) + t["r"]
    eq, peak, dd = capital, capital, 0.0
    daily = []
    for d in sorted(by_day):
        ret = max(-1.0, risk_pct / 100 * by_day[d])
        daily.append(ret * 100)
        eq = eq * (1 + ret)
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100 if peak else 0.0)
    simple = r * capital * risk_pct / 100
    cal_days = max(1, days)
    geo = ((eq / capital) ** (1 / cal_days) - 1) * 100 if capital and eq > 0 else -100.0
    return {"trades": n, "wins": w, "winrate": w / n * 100 if n else 0.0, "r": round(r, 2), "pnl": round(eq - capital, 2),
            "pct": round((eq - capital) / capital * 100, 2), "final": round(eq, 2), "max_dd": round(dd, 2),
            "pnl_simple": round(simple, 2), "avg_daily_pct": round(geo, 3),
            "avg_trading_day_pct": round(sum(daily) / len(daily), 3) if daily else 0.0, "trading_days": len(daily),
            "best_day_pct": round(max(daily), 2) if daily else 0.0, "worst_day_pct": round(min(daily), 2) if daily else 0.0}


def _sim_context(df: pd.DataFrame, i: int, t: dict, label: str) -> str:
    c = df["close"].iloc[: i + 1]
    dec = price_decimals(float(c.iloc[-1]))
    closes = ", ".join(f"{x:.{dec}f}" for x in c.iloc[-20:])
    return (f"{'COMPRA' if t['dir'] == 'BUY' else 'VENDA'} em {label}, preço {float(c.iloc[-1]):.{dec}f}.\n"
            f"EMA200: {'acima' if c.iloc[-1] > ema(c, 200).iloc[-1] else 'abaixo'} · RSI14 {float(rsi(c, 14).iloc[-1]):.1f} · "
            f"ATR14 {float(atr(df.iloc[: i + 1]).iloc[-1]):.{dec}f}.\nÚltimos 20 fechos: {closes}")


async def _simulate_job(job_id: str, body: SimIn, plugins: dict):
    job = _sim_jobs[job_id]
    since = (datetime.now(timezone.utc) - timedelta(days=body.days)).isoformat()
    pending_ai = []
    try:
        for it in body.items:
            label = f"{display(it.symbol)} {it.tf.upper()}"
            name = {"c12": "12 Confirmações", "c20": "Sniper 20"}.get(it.kind) or it.strategy
            job["current"] = label
            row = {"kind": it.kind, "symbol": it.symbol, "tf": it.tf, "label": label, "strategy": name, "rr": it.rr}
            try:
                df = await get_df(it.symbol, it.tf, long=True)
                htf = await get_htf(it.symbol, it.tf)
                strat = {"c12": "confirm12", "c20": "confirm20"}.get(it.kind, it.strategy)
                pl = {**plugins, "_c12": {"min": it.min}, "_c20": {"min": it.min}}
                fee = FEES[ASSET_INFO[it.symbol]["category"]]
                stream = it.kind in ("c12", "c20")
                res = await asyncio.to_thread(run_backtest, df, strat, pl, it.sl_atr, it.rr, body.risk_pct, body.capital, fee,
                                              False if stream else it.trend_filter, True, (stream or it.mtf) and htf is not None, htf,
                                              body.partial_pct, 2.0 if it.kind == "c20" else 1.0, True)
                span = (pd.Timestamp(df.index[-1]) - pd.Timestamp(df.index[0])).total_seconds() / 86400
                row["days_covered"] = max(1, min(body.days, int(round(span))))
                cut = pd.Timestamp(since)
                trades = [t for t in res["trades"] if pd.Timestamp(t["opened"]).tz_convert("UTC") >= cut] \
                    if res["trades"] and pd.Timestamp(res["trades"][0]["opened"]).tzinfo else \
                    [t for t in res["trades"] if pd.Timestamp(t["opened"]) >= cut.tz_localize(None)]
            except HTTPException as e:
                row["error"] = e.detail
                job["rows"].append(row)
                job["step"] += 1
                continue
            row["no_ai"] = _r_stats(trades, body.capital, body.risk_pct, row["days_covered"])
            row["_trades"] = trades
            if body.ai:
                idx = {ts.isoformat(): k for k, ts in enumerate(df.index)}
                for t in trades:
                    if t["opened"] in idx:
                        pending_ai.append((row, t, df, idx[t["opened"]], label))
            job["rows"].append(row)
            job["step"] += 1
        if body.ai and pending_ai:
            pending_ai.sort(key=lambda x: x[1]["opened"], reverse=True)
            todo = pending_ai[:SIM_AI_CAP]
            job["ai_total"], job["ai_done"] = len(todo), 0
            job["ai_capped"] = len(pending_ai) > SIM_AI_CAP
            job["current"] = "Filtro IA"
            sem = asyncio.Semaphore(8)

            async def judge(x):
                row, t, df, i, label = x
                async with sem:
                    v = await ai.ai_filter(_sim_context(df, i, t, label), timeout=20)
                t["ai"] = v["approve"]
                job["ai_done"] += 1
            await asyncio.gather(*(judge(x) for x in todo))
        tot_no, tot_ai_eval, tot_ai_ok = [], [], []
        cov = max([r["days_covered"] for r in job["rows"] if "days_covered" in r] or [body.days])
        job["days_covered"] = cov
        for row in job["rows"]:
            tr = row.pop("_trades", [])
            tot_no += tr
            if body.ai and "days_covered" in row:
                ev = [t for t in tr if "ai" in t]
                ok = [t for t in ev if t["ai"]]
                row["ai_eval"] = _r_stats(ev, body.capital, body.risk_pct, row["days_covered"])
                row["with_ai"] = _r_stats(ok, body.capital, body.risk_pct, row["days_covered"])
                tot_ai_eval += ev
                tot_ai_ok += ok
        job["total"] = {"no_ai": _r_stats(tot_no, body.capital, body.risk_pct, cov)}
        if body.ai:
            job["total"]["ai_eval"] = _r_stats(tot_ai_eval, body.capital, body.risk_pct, cov)
            job["total"]["with_ai"] = _r_stats(tot_ai_ok, body.capital, body.risk_pct, cov)
    except Exception:
        logger.exception("simulation failed")
        job["error"] = "Falha na simulação"
    finally:
        job["status"], job["current"] = "done", None


@api.post("/simulate")
async def simulate_ep(body: SimIn, request: Request):
    u = await get_user(request)
    if not body.items:
        raise HTTPException(400, "Escolhe pelo menos uma estratégia")
    for it in body.items:
        if it.symbol not in ASSET_INFO or it.tf not in TIMEFRAMES or (it.kind == "setup" and it.strategy not in STRATEGIES) \
                or it.kind not in ("setup", "c12", "c20"):
            raise HTTPException(400, f"Item inválido: {it.symbol} {it.tf}")
    if any(v["user_id"] == u["user_id"] and v["status"] == "running" for v in _sim_jobs.values()):
        raise HTTPException(429, "Já tens uma simulação em curso")
    for jid in [j for j, v in _sim_jobs.items() if v["status"] == "done" and time.time() - v["started"] > 3600]:
        _sim_jobs.pop(jid, None)
    job_id = uuid.uuid4().hex[:12]
    _sim_jobs[job_id] = {"job_id": job_id, "user_id": u["user_id"], "status": "running", "started": time.time(), "current": None,
                         "step": 0, "steps": len(body.items), "rows": [], "ai": body.ai, "days": body.days,
                         "capital": body.capital, "ai_total": 0, "ai_done": 0, "ai_capped": False}
    asyncio.create_task(_simulate_job(job_id, body, await user_plugins(u["user_id"])))
    return {"job_id": job_id}


@api.get("/simulate/{job_id}")
async def simulate_status(job_id: str, request: Request):
    u = await get_user(request)
    job = _sim_jobs.get(job_id)
    if not job or job["user_id"] != u["user_id"]:
        raise HTTPException(404, "Simulação não encontrada")
    out = {k: v for k, v in job.items() if k != "user_id"}
    out["rows"] = [{k: v for k, v in r.items() if k != "_trades"} for r in job["rows"]]
    return out


C20_OPT_TFS = ["5m", "15m", "1h", "4h", "1d"]
C20_OPT_RR = [5.0, 10.0]
C20_OPT_MIN = [14, 16, 18]
C12_OPT_RR = [1.5, 2.0, 3.0]
C12_OPT_MIN = [9, 10, 11]
_c20_jobs: Dict[str, dict] = {}


def _c20_grid(df: pd.DataFrame, htf, fee: float, bot: dict, kind: str = "c20") -> Optional[dict]:
    """Best (min confirmations, R:R) for one pair/TF, selected on the first 70% and validated on the last 30%."""
    mat = confirm20_matrix(df) if kind == "c20" else confirm12_matrix(df)
    mins, rrs = (C20_OPT_MIN, C20_OPT_RR) if kind == "c20" else (C12_OPT_MIN, C12_OPT_RR)
    ptp_r = float(bot.get("c20_ptp_r", 2.0)) if kind == "c20" else float(bot.get("ptp_r", 1.0))
    split = int(len(df) * 0.7)
    ptp = float(bot.get("ptp_pct", 50)) if bot.get("ptp_enabled") else 0.0
    best = None
    for mn in mins:
        sig = apply_filters(df, confirm_signals(mat, mn), "confirm20", False, htf is not None, htf)
        for rr in rrs:
            tr = simulate(df.iloc[:split], sig[:split], bot["sl_atr"], rr, 1.0, 10000.0, fee, True, ptp, ptp_r)
            te = simulate(df.iloc[split:], sig[split:], bot["sl_atr"], rr, 1.0, 10000.0, fee, True, ptp, ptp_r)
            m_tr, m_te = tr["metrics"], te["metrics"]
            if m_tr["total_trades"] < 3:
                continue
            cand = {"min": mn, "rr": rr, "train": m_tr["return_pct"], "test": m_te["return_pct"],
                    "test_trades": m_te["total_trades"], "test_winrate": m_te["win_rate"]}
            if best is None or cand["train"] > best["train"]:
                best = cand
    return best


async def _c20_optimize(job_id: str):
    job = _c20_jobs[job_id]
    uid = job["user_id"]
    kind = job["kind"]
    bot = await get_bot(uid)
    try:
        for sym in job["symbols"]:
            fee = FEES[ASSET_INFO[sym]["category"]]
            best = None
            for tf in C20_OPT_TFS:
                job["current"] = f"{display(sym)} {tf.upper()}"
                job["step"] += 1
                try:
                    df = await get_df(sym, tf, long=True)
                    if len(df) < 600:
                        continue
                    htf = await get_htf(sym, tf)
                    b = await asyncio.to_thread(_c20_grid, df, htf, fee, bot, kind)
                except HTTPException:
                    continue
                except Exception:
                    logger.exception("c20 optimize %s %s", sym, tf)
                    continue
                if b and (best is None or b["test"] > best["test"]):
                    best = {**b, "tf": tf}
            pair = {"symbol": sym, "display": display(sym), "enabled": bool(best and best["test"] > 0), **(best or {"tf": bot.get(f"{kind}_tf", "1h"), "rr": bot.get(f"{kind}_rr") or bot["rr"], "min": bot.get(f"{kind}_min", 16), "test": None})}
            job["results"].append(pair)
            # save immediately so nothing is lost if the app/server sleeps
            await db.bots.update_one({"user_id": uid}, {"$pull": {f"{kind}_pairs": {"symbol": sym}}})
            await db.bots.update_one({"user_id": uid}, {"$push": {f"{kind}_pairs": {k: pair[k] for k in ("symbol", "tf", "rr", "min", "enabled", "test")}}})
    finally:
        job["status"], job["current"] = "done", None
        on = sum(1 for p in job["results"] if p["enabled"])
        await bot_log(uid, "fix", f"{'Sniper 20' if kind == 'c20' else '12 Confirmações'} otimizado: {on}/{len(job['results'])} pares ativos com o melhor TF e R:R")


@api.post("/bot/c20-optimize")
async def c20_optimize(request: Request, kind: str = "c20"):
    u = await get_user(request)
    if kind not in ("c12", "c20"):
        raise HTTPException(400, "Tipo inválido")
    bot = await get_bot(u["user_id"])
    syms = [s for s in bot["symbols"] if s in ASSET_INFO]
    if not syms:
        raise HTTPException(400, "Adiciona ativos ao robô primeiro")
    if any(v["user_id"] == u["user_id"] and v["status"] == "running" and v.get("kind") == kind for v in _c20_jobs.values()):
        raise HTTPException(429, f"Já tens uma otimização {'Sniper 20' if kind == 'c20' else '12 Confirmações'} em curso")
    job_id = uuid.uuid4().hex[:12]
    _c20_jobs[job_id] = {"job_id": job_id, "user_id": u["user_id"], "kind": kind, "status": "running", "current": None, "step": 0,
                         "total": len(syms) * len(C20_OPT_TFS), "symbols": syms, "results": []}
    asyncio.create_task(_c20_optimize(job_id))
    return {"job_id": job_id}


@api.get("/bot/c20-optimize/{job_id}")
async def c20_optimize_status(job_id: str, request: Request):
    u = await get_user(request)
    job = _c20_jobs.get(job_id)
    if not job or job["user_id"] != u["user_id"]:
        raise HTTPException(404, "Otimização não encontrada")
    return {k: v for k, v in job.items() if k not in ("user_id", "symbols")}


_negopt_jobs: Dict[str, dict] = {}


class NegOptIn(BaseModel):
    items: List[SimItem]  # the negative rows of a simulation


async def _negopt(job_id: str, items: List[SimItem]):
    job = _negopt_jobs[job_id]
    uid = job["user_id"]
    plugins = await user_plugins(uid)
    bot = await get_bot(uid)
    try:
        for it in items:
            label = f"{display(it.symbol)} {it.tf.upper()}"
            job["current"] = label
            fee = FEES[ASSET_INFO[it.symbol]["category"]]
            prop = {"kind": it.kind, "symbol": it.symbol, "tf": it.tf, "old_strategy": it.strategy, "label": label, "best": None}
            try:
                if it.kind == "setup":
                    df = await get_df(it.symbol, it.tf, long=True)
                    htf = await get_htf(it.symbol, it.tf)
                    b = (await asyncio.to_thread(optimize, df, plugins, fee, 1.0, 10000.0, 0.7, htf))["best"]
                    if b and b["test"]["return_pct"] > MIN_BOT_RETURN:
                        prop["best"] = {"strategy": b["strategy"], "sl_atr": b["sl_atr"], "rr": b["rr"], "trend_filter": b["trend_filter"],
                                        "mtf": b["mtf"], "tf": it.tf, "test": b["test"]["return_pct"], "winrate": b["test"]["win_rate"]}
                elif it.kind == "c20":
                    best = None
                    for tf in C20_OPT_TFS:
                        df = await get_df(it.symbol, tf, long=True)
                        if len(df) < 600:
                            continue
                        b = await asyncio.to_thread(_c20_grid, df, await get_htf(it.symbol, tf), fee, bot)
                        if b and (best is None or b["test"] > best["test"]):
                            best = {**b, "tf": tf}
                    if best and best["test"] > 0:
                        prop["best"] = {"tf": best["tf"], "rr": best["rr"], "min": best["min"], "test": best["test"], "winrate": best["test_winrate"]}
            except HTTPException:
                pass
            except Exception:
                logger.exception("negopt %s", label)
            job["results"].append(prop)
            job["step"] += 1
    finally:
        job["status"], job["current"] = "done", None


@api.post("/simulate/optimize-negatives")
async def negopt_start(body: NegOptIn, request: Request):
    u = await get_user(request)
    items = [i for i in body.items if i.kind in ("setup", "c20") and i.symbol in ASSET_INFO and i.tf in TIMEFRAMES]
    if not items:
        raise HTTPException(400, "Sem setups negativos otimizáveis")
    job_id = uuid.uuid4().hex[:12]
    _negopt_jobs[job_id] = {"job_id": job_id, "user_id": u["user_id"], "status": "running", "current": None, "step": 0,
                            "total": len(items), "results": [], "applied": False}
    asyncio.create_task(_negopt(job_id, items))
    return {"job_id": job_id}


@api.get("/simulate/optimize-negatives/{job_id}")
async def negopt_status(job_id: str, request: Request):
    u = await get_user(request)
    job = _negopt_jobs.get(job_id)
    if not job or job["user_id"] != u["user_id"]:
        raise HTTPException(404, "Otimização não encontrada")
    return {k: v for k, v in job.items() if k != "user_id"}


@api.post("/simulate/optimize-negatives/{job_id}/apply")
async def negopt_apply(job_id: str, request: Request):
    """Negative setups are replaced by their optimised version (or removed if none qualified); Sniper 20 pairs updated."""
    u = await get_user(request)
    uid = u["user_id"]
    job = _negopt_jobs.get(job_id)
    if not job or job["user_id"] != uid or job["status"] != "done":
        raise HTTPException(400, "Otimização ainda não terminou")
    bot = await get_bot(uid)
    setups = list(bot.get("setups") or [])
    pairs = {p["symbol"]: p for p in (bot.get("c20_pairs") or [])}
    replaced = removed = 0
    for r in job["results"]:
        if r["kind"] == "setup":
            setups = [s for s in setups if not (s["symbol"] == r["symbol"] and s["tf"] == r["tf"] and s["strategy"] == r["old_strategy"])]
            if r["best"]:
                b = r["best"]
                setups = [s for s in setups if not (s["symbol"] == r["symbol"] and s["tf"] == r["tf"])]
                setups.append({"symbol": r["symbol"], "tf": r["tf"], "strategy": b["strategy"], "sl_atr": b["sl_atr"], "rr": b["rr"],
                               "trend_filter": b["trend_filter"], "mtf": b["mtf"]})
                replaced += 1
            else:
                removed += 1
        elif r["kind"] == "c20":
            b = r["best"]
            pairs[r["symbol"]] = ({"symbol": r["symbol"], "tf": b["tf"], "rr": b["rr"], "min": b["min"], "enabled": True, "test": b["test"]}
                                  if b else {**pairs.get(r["symbol"], {"symbol": r["symbol"], "tf": bot["c20_tf"], "rr": bot["c20_rr"], "min": bot["c20_min"], "test": None}), "enabled": False})
            replaced += 1 if b else 0
            removed += 0 if b else 1
    await db.bots.update_one({"user_id": uid}, {"$set": {"setups": setups, "c20_pairs": list(pairs.values())}}, upsert=True)
    job["applied"] = True
    await bot_log(uid, "fix", f"Negativos da simulação: {replaced} otimizado(s), {removed} retirado(s)/desligado(s)")
    return {"replaced": replaced, "removed": removed}


_bot_opt_jobs: Dict[str, dict] = {}
MIN_BOT_RETURN = 6.0  # only setups with > 6% profit in the out-of-sample test period may go to the bot


async def _save_job(job: dict) -> None:
    await db.bot_opt_jobs.update_one({"job_id": job["job_id"]}, {"$set": dict(job)}, upsert=True)


async def _bot_optimize_all(job_id: str, resume: bool = False):
    """Walk-forward optimise every (asset, timeframe). Progress lives in MongoDB, so a server restart/sleep
    resumes where it stopped. Each setup with > 6% test profit is added to the bot immediately."""
    job = _bot_opt_jobs[job_id]
    uid = job["user_id"]
    plugins = await user_plugins(uid)
    if not resume:  # start from scratch: old setups are removed
        await db.bots.update_one({"user_id": uid}, {"$set": {"setups": []}}, upsert=True)
        await bot_log(uid, "fix", "Otimizar tudo: setups antigos removidos, a otimizar de novo")
    else:
        await bot_log(uid, "fix", f"Otimizar tudo retomado ({job['step']}/{job['total']})")
    try:
        for sym in job["symbols"]:
            fee = FEES[ASSET_INFO[sym]["category"]]
            for tf in OPT_TFS:
                k = f"{sym}|{tf}"
                if k in job["done_keys"]:
                    continue
                job["current"] = f"{display(sym)} {tf.upper()}"
                await _save_job(job)
                try:
                    df = await get_df(sym, tf, long=True)
                    b = None
                    if len(df) >= 600:
                        htf = await get_htf(sym, tf)
                        b = (await asyncio.to_thread(optimize, df, plugins, fee, 1.0, 10000.0, 0.7, htf))["best"]
                except HTTPException:
                    b = None
                except Exception:  # keep going with the other timeframes
                    logger.exception("bot optimize-all %s %s", sym, tf)
                    b = None
                if b and b["test"]["return_pct"] > MIN_BOT_RETURN:
                    job["results"].append({"symbol": sym, "display": display(sym), "tf": tf, "best": b})
                    await db.bots.update_one({"user_id": uid}, {"$pull": {"setups": {"symbol": sym, "tf": tf}}})
                    await db.bots.update_one({"user_id": uid}, {"$push": {"setups": {
                        "symbol": sym, "tf": tf, "strategy": b["strategy"], "sl_atr": b["sl_atr"], "rr": b["rr"],
                        "trend_filter": b["trend_filter"], "mtf": b["mtf"]}}})
                    job["applied"] += 1
                    await bot_log(uid, "fix", f"Setup adicionado: {display(sym)} {tf.upper()} {b['strategy']} (teste {b['test']['return_pct']:+.1f}%)", sym)
                job["done_keys"].append(k)
                job["step"] = len(job["done_keys"])
                await _save_job(job)
        job["results"].sort(key=lambda x: -(x["best"]["test"]["return_pct"]))
        job["status"] = "done"
    except asyncio.CancelledError:  # server shutting down: keep status "running" so it resumes on next start
        raise
    except Exception:
        logger.exception("bot optimize-all job failed")
        job["status"] = "done"
    finally:
        if job["status"] == "done":
            job["current"] = None
        await _save_job(job)


async def resume_opt_jobs() -> None:
    async for job in db.bot_opt_jobs.find({"status": "running"}, {"_id": 0}):
        _bot_opt_jobs[job["job_id"]] = job
        asyncio.create_task(_bot_optimize_all(job["job_id"], resume=True))


async def _get_job(job_id: str, uid: str) -> dict:
    job = _bot_opt_jobs.get(job_id) or await db.bot_opt_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job or job["user_id"] != uid:
        raise HTTPException(404, "Otimização não encontrada")
    return job


class OptApplyIn(BaseModel):
    keys: List[str]  # "SYMBOL|tf"
    replace: bool = False


@api.post("/bot/optimize-all/{job_id}/apply")
async def bot_optimize_all_apply(job_id: str, body: OptApplyIn, request: Request):
    u = await get_user(request)
    uid = u["user_id"]
    job = await _get_job(job_id, uid)
    chosen = [x for x in job["results"] if f"{x['symbol']}|{x['tf']}" in set(body.keys)
              and x["best"]["test"]["return_pct"] > MIN_BOT_RETURN]
    if not chosen and not body.replace:
        raise HTTPException(400, "Escolhe pelo menos um setup")
    new = [{"symbol": x["symbol"], "tf": x["tf"], "strategy": x["best"]["strategy"], "sl_atr": x["best"]["sl_atr"],
            "rr": x["best"]["rr"], "trend_filter": x["best"]["trend_filter"], "mtf": x["best"]["mtf"]} for x in chosen]
    bot = await get_bot(uid)
    keys = {(x["symbol"], x["tf"]) for x in new}
    keep = [] if body.replace else [x for x in (bot.get("setups") or []) if (x["symbol"], x["tf"]) not in keys]
    setups = keep + new
    await db.bots.update_one({"user_id": uid}, {"$set": {"setups": setups}}, upsert=True)
    await bot_log(uid, "fix", f"Otimizar tudo: {len(setups)} setup(s) ativos no robô")
    return {"applied": len(new), "total": len(setups)}


@api.post("/bot/optimize-all")
async def bot_optimize_all(request: Request):
    u = await get_user(request)
    uid = u["user_id"]
    bot = await get_bot(uid)
    syms = [s for s in bot["symbols"] if s in ASSET_INFO]
    if not syms:
        raise HTTPException(400, "Adiciona ativos ao robô primeiro")
    if await db.bot_opt_jobs.find_one({"user_id": uid, "status": "running"}):
        raise HTTPException(429, "Já tens uma otimização em curso")
    job_id = uuid.uuid4().hex[:12]
    _bot_opt_jobs[job_id] = {"job_id": job_id, "user_id": uid, "status": "running", "started": time.time(), "current": None,
                             "step": 0, "total": len(syms) * len(OPT_TFS), "results": [], "applied": 0,
                             "symbols": syms, "done_keys": []}
    await _save_job(_bot_opt_jobs[job_id])
    asyncio.create_task(_bot_optimize_all(job_id))
    return {"job_id": job_id}


@api.get("/bot/optimize-all/current")
async def bot_optimize_all_current(request: Request):
    u = await get_user(request)
    job = await db.bot_opt_jobs.find_one({"user_id": u["user_id"]}, {"_id": 0, "job_id": 1}, sort=[("started", -1)])
    return {"job_id": job["job_id"] if job else None}


@api.get("/bot/optimize-all/{job_id}")
async def bot_optimize_all_status(job_id: str, request: Request):
    u = await get_user(request)
    job = await _get_job(job_id, u["user_id"])
    return {k: v for k, v in job.items() if k not in ("user_id", "done_keys", "symbols")}


async def _run_bot_cycle(bot: dict) -> int:
    """One pass: evaluate each symbol's last CLOSED bar and open/close bot positions. Returns trades opened."""
    uid = bot["user_id"]
    bot = await get_bot(uid)  # fresh state (last_bar) under the lock
    await check_exits(uid)
    plugins = await user_plugins(uid)
    plugins["_conf"] = {"min_votes": bot.get("conf_votes", 2), "min_score": bot.get("conf_score", 55.0)}
    plugins["_c12"] = {"min": bot.get("c12_min", 10)}
    acc = await get_account(uid)
    opened = 0
    setups = bot.get("setups") or []
    with_setup = {x["symbol"] for x in setups}
    jobs = [{"symbol": s, "tf": bot["tf"], "strategy": bot["strategy"], "sl_atr": bot["sl_atr"], "rr": bot["rr"],
             "trend_filter": bot.get("trend_filter", True), "mtf": bot.get("mtf", True)}
            for s in bot["symbols"] if s not in with_setup] + setups
    fixes = bot.get("fixes") or {}
    for cfg in jobs:
        sym = cfg["symbol"]
        if sym not in ASSET_INFO:
            continue
        key = f"{sym}|{cfg['tf']}"
        if key in fixes.get("paused", []) or datetime.now(timezone.utc).hour in fixes.get("hours", []):
            continue
        if fixes.get("force_mtf"):
            cfg = {**cfg, "mtf": True}
        if fixes.get("widen_stop"):
            cfg = {**cfg, "sl_atr": min(5.0, cfg["sl_atr"] + 0.5)}
        tag = f"{display(sym)} {cfg['tf'].upper()}"
        try:
            df = await get_df(sym, cfg["tf"])
        except HTTPException:
            continue
        if len(df) < 210:
            continue
        htf = await get_htf(sym, cfg["tf"]) if cfg.get("mtf") else None
        sig = strategy_signals(df, cfg["strategy"], plugins)
        sig = apply_filters(df, sig, cfg["strategy"], cfg.get("trend_filter", True), bool(cfg.get("mtf")) and htf is not None, htf)
        s = int(sig[-2])  # last closed bar, avoids repainting
        bar_ts = df.index[-2].isoformat()
        if s == 0:
            continue
        skey = key.replace('.', '_')
        state_key = f"last_bar.{skey}"
        if bot.get("last_bar", {}).get(skey) == bar_ts:
            continue
        await db.bots.update_one({"user_id": uid}, {"$set": {state_key: bar_ts}}, upsert=True)
        side = "BUY" if s == 1 else "SELL"
        existing = await db.positions.find_one({"user_id": uid, "status": "open", "source": "bot",
                                                "$or": [{"setup": key}, {"symbol": sym, "setup": {"$exists": False}}]}, {"_id": 0})
        price = float(df["close"].iloc[-1])
        if existing:
            if existing["side"] == side:
                continue
            pnl = await close_position(existing, price, "signal")
            await bot_log(uid, "close", f"{tag} fechado por sinal contrário: {pnl:+.2f} $", sym)
        n_open = await db.positions.count_documents({"user_id": uid, "status": "open", "source": "bot", "c12": {"$ne": True}, "c20": {"$ne": True}})
        if n_open >= bot["max_positions"]:
            await bot_log(uid, "skip", f"Sinal {side} em {tag} ignorado: limite de {bot['max_positions']} posições", sym)
            continue
        a = float(atr(df).iloc[-1])
        if a <= 0:
            continue
        acc = await get_account(uid)
        stop = cfg["sl_atr"] * a
        if stop < 8 * FEES[ASSET_INFO[sym]["category"]] * price:
            await bot_log(uid, "skip", f"Sinal {side} em {tag} ignorado: stop demasiado curto face aos custos", sym)
            continue
        qty = await _margin_qty(uid, acc, (acc["balance"] * bot["risk_pct"] / 100) / stop, price)
        if qty <= 0:
            await bot_log(uid, "skip", f"Sinal {side} em {tag} ignorado: margem livre insuficiente (alavancagem 1:{LEVERAGE})", sym)
            continue
        d = 1 if side == "BUY" else -1
        htf_ok = (int(htf_trend(df, htf)[-1]) == d) if htf is not None else None
        ai_note, ai_ok = "", None
        if bot.get("ai_filter"):
            dec = price_decimals(price)
            closes = ", ".join(f"{x:.{dec}f}" for x in df["close"].iloc[-20:])
            v = await ai.ai_filter(
                f"{'COMPRA' if side == 'BUY' else 'VENDA'} em {tag} ({ASSET_INFO[sym]['category']}), estratégia {cfg['strategy']}, "
                f"preço {price:.{dec}f}, SL {cfg['sl_atr']}x ATR, R:R {cfg['rr']}.\n"
                f"EMA200: {'acima' if price > float(ema(df['close'], 200).iloc[-1]) else 'abaixo'} · RSI14 {float(rsi(df['close'], 14).iloc[-1]):.1f} · "
                f"ATR14 {a:.{dec}f} · TF superior {'alinhado' if htf_ok else 'CONTRA' if htf_ok is False else 'sem dados'}.\n"
                f"Últimos 20 fechos: {closes}")
            if not v["approve"]:
                await ai.record_rejection(db, uid, "bot", sym, side, v)
                await bot_log(uid, "ai", f"IA rejeitou {side} {tag}: {v['reason']} ({v['confidence']}%)", sym)
                continue
            ai_note = f" · IA ✓ {v['confidence']}%"
            ai_ok = {"confidence": v["confidence"], "reason": v["reason"]}
        pos = {"position_id": uuid.uuid4().hex[:16], "user_id": uid, "symbol": sym, "side": side, "qty": float(qty),
               "entry": price, "stop_loss": price - d * stop, "take_profit": price + d * stop * cfg["rr"],
               "status": "open", "source": "bot", "setup": key, "tf": cfg["tf"], "stop_dist": float(stop),
               "ctx": {"hour": datetime.now(timezone.utc).hour,
                       "htf_aligned": htf_ok}, "opened_at": datetime.now(timezone.utc).isoformat()}
        if ai_ok:
            pos["ai"] = ai_ok
        pos.update(_ptp_fields(bot))
        if not await _go_live(uid, bot, pos):
            continue
        await db.positions.insert_one(dict(pos))
        opened += 1
        dec = price_decimals(price)
        await bot_log(uid, "open", f"{'COMPRA' if side == 'BUY' else 'VENDA'} {tag}{(' · tendência ' + HTF_MAP[cfg['tf']].upper() + ' confirmada') if cfg.get('mtf') and htf is not None else ''} @ {price:.{dec}f} · SL {pos['stop_loss']:.{dec}f} · TP {pos['take_profit']:.{dec}f}{ai_note}", sym)
    for kind in STREAMS:
        if bot.get(f"{kind}_enabled"):
            opened += await _run_stream(uid, bot, kind)
    await db.bots.update_one({"user_id": uid}, {"$set": {"last_run": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    await bot_auto_fix(uid)
    return opened


async def bot_loop():
    while True:
        try:
            bots = await db.bots.find({"enabled": True}, {"_id": 0}).to_list(500)
            for b in bots:
                try:
                    await run_bot_cycle({**BOT_DEFAULT, **b})
                except Exception:
                    logger.exception("bot cycle failed for %s", b.get("user_id"))
            bot_users = {b["user_id"] for b in bots}
            for uid in await db.positions.distinct("user_id", {"status": "open"}):
                if uid not in bot_users:
                    await check_exits(uid)
        except Exception:
            logger.exception("bot loop error")
        await asyncio.sleep(60)


@api.get("/bot")
async def bot_get(request: Request):
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    bot.pop("last_bar", None)
    bot.pop("fix_ts", None)
    logs = await db.bot_logs.find({"user_id": u["user_id"], "scope": {"$ne": "hfx"}}, {"_id": 0}).sort("created_at", -1).to_list(50)
    closed = await db.positions.find({"user_id": u["user_id"], "status": "closed", "source": "bot"}, {"_id": 0, "pnl": 1}).to_list(1000)
    n_open = await db.positions.count_documents({"user_id": u["user_id"], "status": "open", "source": "bot"})
    stats = {"trades": len(closed), "pnl": sum(p["pnl"] for p in closed), "wins": sum(1 for p in closed if p["pnl"] > 0), "open": n_open}
    assets = [{"symbol": s, "display": display(s), "category": i["category"]} for s, i in ASSET_INFO.items()]
    return {"bot": bot, "logs": logs, "stats": stats, "assets": assets}


@api.put("/bot")
async def bot_put(body: BotIn, request: Request):
    u = await get_user(request)
    if body.tf not in TIMEFRAMES:
        raise HTTPException(400, "Timeframe inválido")
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, "Estratégia inválida")
    syms = [s for s in body.symbols if s in ASSET_INFO]
    seen = set()
    for st in body.setups:
        if st.symbol not in ASSET_INFO or st.tf not in TIMEFRAMES or st.strategy not in STRATEGIES:
            raise HTTPException(400, f"Setup inválido para {st.symbol} {st.tf}")
        if (st.symbol, st.tf) in seen:
            raise HTTPException(400, f"Setup duplicado: {st.symbol} {st.tf}")
        seen.add((st.symbol, st.tf))
    if body.enabled and not syms:
        raise HTTPException(400, "Escolhe pelo menos um ativo")
    prev = await get_bot(u["user_id"])
    data = body.model_dump()
    data["symbols"] = syms
    data["setups"] = [st.model_dump() for st in body.setups if st.symbol in syms]
    data.pop("overrides", None)
    await db.bots.update_one({"user_id": u["user_id"]}, {"$set": {**data, "updated_at": datetime.now(timezone.utc).isoformat()}, "$unset": {"overrides": ""}}, upsert=True)
    if body.enabled != prev["enabled"]:
        await bot_log(u["user_id"], "status", "Robô ativado" if body.enabled else "Robô parado")
    return {"ok": True}


@api.get("/bot/analysis")
async def bot_analysis(request: Request):
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    return {**await bot_loss_analysis(u["user_id"]), "fixes": bot.get("fixes") or {}, "auto_fix": bot.get("auto_fix", True)}


@api.post("/bot/analysis/apply")
async def bot_analysis_apply(request: Request):
    u = await get_user(request)
    return await bot_auto_fix(u["user_id"], force=True)


@api.post("/bot/analysis/reset")
async def bot_analysis_reset(request: Request):
    u = await get_user(request)
    await db.bots.update_one({"user_id": u["user_id"]}, {"$set": {"fixes": {}, "fix_ts": time.time()}}, upsert=True)
    await bot_log(u["user_id"], "fix", "Correções automáticas removidas")
    return {"ok": True}


class AutoFixIn(BaseModel):
    scope: str
    enabled: bool


@api.put("/analysis/auto-fix")
async def set_auto_fix(body: AutoFixIn, request: Request):
    u = await get_user(request)
    coll = {"bot": db.bots, "hfx": db.hfx_bots}.get(body.scope)
    if coll is None:
        raise HTTPException(400, "Âmbito inválido")
    await coll.update_one({"user_id": u["user_id"]}, {"$set": {"auto_fix": body.enabled}}, upsert=True)
    return {"ok": True}


class LossReviewIn(BaseModel):
    scope: str


@api.post("/ai/loss-review")
async def ai_loss_review(body: LossReviewIn, request: Request):
    from emergentintegrations.llm.chat import UserMessage, TextDelta, StreamDone
    u = await get_user(request)
    uid = u["user_id"]
    if body.scope == "hfx":
        bot = {**hfx.HFX_BOT_DEFAULT, **(await db.hfx_bots.find_one({"user_id": uid}, {"_id": 0, "last_bar": 0, "fix_ts": 0}) or {})}
        trades = await db.hfx_trades.find({"user_id": uid, "origin": "bot", "status": {"$in": ["won", "lost"]},
                                           "opened_ts": {"$gte": time.time() - 86400}}, {"_id": 0}).sort("expires_ts", -1).to_list(200)
        if len(trades) < 3:  # fall back to all HFX trades so manual-only users still get a review
            trades = await db.hfx_trades.find({"user_id": uid, "status": {"$in": ["won", "lost"]}}, {"_id": 0}).sort("expires_ts", -1).to_list(200)
        an = hfx.loss_analysis(trades, 1 / (1 + hfx.PAYOUT[bot["source"]]) * 100)
        an["recent_losses"] = [{"par": hfx.pair_display(t["pair"], t["source"]), "dir": t["direction"], "exp": t["expiry"],
                                "regra": t.get("rule_label") or "manual", "ctx": t.get("ctx")} for t in trades if t["status"] == "lost"][:12]
        cfg = {k: bot.get(k) for k in ("source", "pairs", "expiry", "amount", "min_winrate", "strategy", "min_votes", "max_per_hour", "auto_fix", "ai_filter")}
    elif body.scope == "bot":
        bot = await get_bot(uid)
        an = await bot_loss_analysis(uid)
        cfg = {k: bot.get(k) for k in ("symbols", "tf", "strategy", "risk_pct", "sl_atr", "rr", "max_positions", "trend_filter", "mtf", "auto_fix", "ai_filter", "setups")}
    else:
        raise HTTPException(400, "Âmbito inválido")
    if an["trades"] < 3:
        raise HTTPException(400, "Poucas operações fechadas para a IA analisar (mínimo 3)")
    chat = ai.review_chat()
    prompt = ai.review_prompt(body.scope, an, bot.get("fixes") or {}, cfg)

    async def gen():
        full = []
        try:
            async for ev in chat.stream_message(UserMessage(text=prompt)):
                if isinstance(ev, TextDelta):
                    full.append(ev.content)
                    yield f"data: {json.dumps({'t': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
            await db.ai_reviews.update_one({"user_id": uid, "scope": body.scope}, {"$set": {
                "text": "".join(full), "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        except Exception as e:  # stream boundary: report to client
            logger.exception("AI review error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.get("/ai/loss-review")
async def ai_loss_review_last(scope: str, request: Request):
    u = await get_user(request)
    doc = await db.ai_reviews.find_one({"user_id": u["user_id"], "scope": scope}, {"_id": 0, "text": 1, "created_at": 1})
    return doc or {"text": "", "created_at": None}


def _day_range(date: Optional[str]) -> tuple:
    try:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date else \
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(400, "Data inválida (AAAA-MM-DD)")
    return d.strftime("%Y-%m-%d"), d, d + timedelta(days=1)


def _group_stats(rows: List[tuple]) -> dict:
    """rows = (label, won, pnl, hour)"""
    groups: Dict[str, list] = {}
    hours: Dict[int, float] = {}
    for label, won, pnl, hour in rows:
        groups.setdefault(label, []).append((won, pnl))
        if hour is not None:
            hours[hour] = hours.get(hour, 0.0) + pnl
    n = len(rows)
    wins = sum(1 for r in rows if r[1])
    g = [{"label": k, "trades": len(v), "winrate": sum(1 for w, _ in v if w) / len(v) * 100, "pnl": sum(p for _, p in v)}
         for k, v in groups.items()]
    g.sort(key=lambda x: x["pnl"])
    return {"trades": n, "wins": wins, "winrate": wins / n * 100 if n else 0.0, "pnl": sum(r[2] for r in rows),
            "groups": g, "bad_hours": ", ".join(f"{h}h ({p:+.2f} $)" for h, p in sorted(hours.items()) if p < 0)}


async def daily_stats(uid: str, start: datetime, end: datetime) -> dict:
    s_iso, e_iso = start.isoformat(), end.isoformat()
    ht = await db.hfx_trades.find({"user_id": uid, "origin": "bot", "status": {"$in": ["won", "lost", "tie"]},
                                   "opened_ts": {"$gte": start.timestamp(), "$lt": end.timestamp()}}, {"_id": 0}).to_list(5000)
    hfx_s = _group_stats([(f"{hfx.pair_display(t['pair'], t['source'])} · {t.get('rule_label') or '?'} · {t['expiry']}m",
                           t["status"] == "won", t.get("profit", 0.0), (t.get("ctx") or {}).get("hour")) for t in ht])
    hb = {**hfx.HFX_BOT_DEFAULT, **(await db.hfx_bots.find_one({"user_id": uid}, {"_id": 0}) or {})}
    pos = await db.positions.find({"user_id": uid, "source": "bot", "status": "closed",
                                   "closed_at": {"$gte": s_iso, "$lt": e_iso}}, {"_id": 0}).to_list(5000)
    bot_s = _group_stats([(f"{display(p['symbol'])} {str(p.get('tf') or '').upper()}", p["pnl"] > 0, p["pnl"],
                           (p.get("ctx") or {}).get("hour")) for p in pos])
    mb = await get_bot(uid)

    async def count(kind: str, hfx_scope: bool, prefix: str = "") -> int:
        q = {"user_id": uid, "kind": kind, "created_at": {"$gte": s_iso, "$lt": e_iso},
             "scope": "hfx" if hfx_scope else {"$ne": "hfx"}}
        if prefix:
            q["msg"] = {"$regex": prefix}
        return await db.bot_logs.count_documents(q)
    hfx_s.update({"ai_rejected": await count("ai", True), "fix_skipped": await count("skip", True, "correção automática"),
                  "breakeven": 1 / (1 + hfx.PAYOUT[hb["source"]]) * 100, "fixes": hb.get("fixes") or {},
                  "config": {k: hb.get(k) for k in ("source", "pairs", "expiry", "amount", "min_winrate", "strategy", "min_votes", "max_per_hour", "ai_filter")}})
    bot_s.update({"ai_rejected": await count("ai", False), "fix_skipped": 0, "fixes": mb.get("fixes") or {},
                  "config": {**{k: mb.get(k) for k in ("symbols", "tf", "strategy", "risk_pct", "sl_atr", "rr", "max_positions", "trend_filter", "mtf", "ai_filter", "conf_votes", "conf_score")},
                             "plugins_ativos": [k for k, v in (await user_plugins(uid)).items() if v.get("enabled")]}})
    return {"hfx": hfx_s, "bot": bot_s, "total_pnl": hfx_s["pnl"] + bot_s["pnl"], "total_trades": hfx_s["trades"] + bot_s["trades"]}


def _public_stats(st: dict) -> dict:
    return {k: ({kk: vv for kk, vv in v.items() if kk not in ("config", "fixes")} if isinstance(v, dict) else v) for k, v in st.items()}


@api.get("/ai/daily-stats")
async def ai_daily_stats(request: Request, date: Optional[str] = None):
    u = await get_user(request)
    day, start, end = _day_range(date)
    return {"date": day, **_public_stats(await daily_stats(u["user_id"], start, end))}


class DailyIn(BaseModel):
    date: Optional[str] = None


@api.post("/ai/daily-summary")
async def ai_daily_summary(body: DailyIn, request: Request):
    from emergentintegrations.llm.chat import UserMessage, TextDelta, StreamDone
    u = await get_user(request)
    uid = u["user_id"]
    day, start, end = _day_range(body.date)
    st = await daily_stats(uid, start, end)
    if st["total_trades"] == 0:
        raise HTTPException(400, "Os robôs não fecharam operações neste dia")
    chat = ai.daily_chat()
    prompt = ai.daily_prompt(day, st)

    async def gen():
        full = []
        try:
            async for ev in chat.stream_message(UserMessage(text=prompt)):
                if isinstance(ev, TextDelta):
                    full.append(ev.content)
                    yield f"data: {json.dumps({'t': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
            yield f"data: {json.dumps({'status': 'adjustments'})}\n\n"
            raw = await ai.ai_adjustments("".join(full) + "\n\nDados:\n" + prompt, _adj_allowed_text())
            hb, mb, plugins = await _configs(uid)
            adjs, seen = [], set()
            for a in raw:
                c = sanitize_adj(a, hb, mb, plugins)
                if c and (c["scope"], c["field"]) not in seen:
                    seen.add((c["scope"], c["field"]))
                    adjs.append({**c, "applied": False})
            await db.daily_summaries.update_one({"user_id": uid, "date": day}, {"$set": {
                "text": "".join(full), "stats": _public_stats(st), "adjustments": adjs,
                "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        except Exception as e:  # stream boundary: report to client
            logger.exception("AI daily error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


ADJ_SPEC = {
    "hfx": {"expiry": ("choice", [1, 3]), "amount": ("num", 1, 1000), "min_winrate": ("num", 50, 90),
            "max_per_hour": ("int", 1, 60), "min_votes": ("int", 1, 7), "strategy": ("choice", ["auto", "plugins"]),
            "ai_filter": ("bool",), "remove_pairs": ("list",)},
    "bot": {"risk_pct": ("num", 0.1, 5), "sl_atr": ("num", 0.5, 5), "rr": ("num", 0.5, 6), "max_positions": ("int", 1, 10),
            "trend_filter": ("bool",), "mtf": ("bool",), "ai_filter": ("bool",), "strategy": ("choice", STRATEGIES),
            "tf": ("choice", list(TIMEFRAMES)), "conf_votes": ("int", 1, 10), "conf_score": ("num", 40, 90),
            "remove_symbols": ("list",), "plugin_on": ("plugin",), "plugin_off": ("plugin",)},
}


def _adj_allowed_text() -> str:
    lines = ["Campos permitidos:"]
    for scope, spec in ADJ_SPEC.items():
        for f, t in spec.items():
            rng = (f"um de {t[1]}" if t[0] == "choice" else f"entre {t[1]} e {t[2]}" if t[0] in ("num", "int") else
                   "true/false" if t[0] == "bool" else "lista de símbolos atuais a remover" if t[0] == "list" else
                   f"nome do plugin, um de {list(PLUGIN_DEFAULTS)}")
            lines.append(f"- {scope}.{f}: {rng}")
    return "\n".join(lines)


def _fmt_val(v) -> str:
    if isinstance(v, bool):
        return "ligado" if v else "desligado"
    if isinstance(v, list):
        return ", ".join(hfx.PAIR_NAME.get(x) or display(x) for x in v) or "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def sanitize_adj(a: dict, hb: dict, mb: dict, plugins: dict) -> Optional[dict]:
    """Validate one AI adjustment against the allowed spec and the CURRENT config; returns it with from/to labels."""
    scope, field, v = a.get("scope"), a.get("field"), a.get("value")
    if isinstance(field, str) and field.startswith(f"{scope}."):  # LLM echoes "hfx.min_winrate" from the allowed list
        field = field[len(scope) + 1:]
    spec = ADJ_SPEC.get(scope, {}).get(field)
    if not spec:
        return None
    cur = hb if scope == "hfx" else mb
    kind = spec[0]
    try:
        if kind in ("num", "int"):
            v = int(round(float(v))) if kind == "int" else round(float(v), 2)
            if not spec[1] <= v <= spec[2]:
                return None
            frm = cur.get(field)
        elif kind == "choice":
            v = type(spec[1][0])(v)
            if v not in spec[1]:
                return None
            frm = cur.get(field)
        elif kind == "bool":
            if not isinstance(v, bool):
                return None
            frm = cur.get(field)
        elif kind == "list":
            key = "pairs" if scope == "hfx" else "symbols"
            v = [x for x in (v if isinstance(v, list) else [v]) if x in cur.get(key, [])]
            if not v or len(v) >= len(cur.get(key, [])):
                return None
            frm = cur.get(key, [])
            label = ai.LABELS[field]
            return {"scope": scope, "field": field, "value": v, "label": label, "from": _fmt_val(frm),
                    "to": _fmt_val([x for x in frm if x not in v]), "reason": str(a.get("reason", ""))[:120]}
        else:  # plugin on/off
            if v not in PLUGIN_DEFAULTS:
                return None
            on = field == "plugin_on"
            if bool(plugins[v].get("enabled")) == on:
                return None
            return {"scope": scope, "field": field, "value": v, "label": f"Plugin {PLUGIN_META[v]['label']}",
                    "from": _fmt_val(not on), "to": _fmt_val(on), "reason": str(a.get("reason", ""))[:120]}
    except (TypeError, ValueError):
        return None
    if frm == v:
        return None
    return {"scope": scope, "field": field, "value": v, "label": ai.LABELS.get(field, field), "from": _fmt_val(frm),
            "to": _fmt_val(v), "reason": str(a.get("reason", ""))[:120]}


async def _configs(uid: str) -> tuple:
    hb = {**hfx.HFX_BOT_DEFAULT, **(await db.hfx_bots.find_one({"user_id": uid}, {"_id": 0}) or {})}
    return hb, await get_bot(uid), await user_plugins(uid)


class ApplyAdjIn(BaseModel):
    date: str
    ids: List[int]


@api.post("/ai/daily-summary/apply")
async def ai_daily_apply(body: ApplyAdjIn, request: Request):
    u = await get_user(request)
    uid = u["user_id"]
    doc = await db.daily_summaries.find_one({"user_id": uid, "date": body.date}, {"_id": 0})
    if not doc or not doc.get("adjustments"):
        raise HTTPException(404, "Sem ajustes para este dia")
    adjs = doc["adjustments"]
    hb, mb, plugins = await _configs(uid)
    applied, skipped = [], 0
    for i in sorted(set(body.ids)):
        if i < 0 or i >= len(adjs) or adjs[i].get("applied"):
            continue
        a = sanitize_adj(adjs[i], hb, mb, plugins)
        if not a:
            skipped += 1
            continue
        coll = db.hfx_bots if a["scope"] == "hfx" else db.bots
        if a["field"] in ("remove_pairs", "remove_symbols"):
            key = "pairs" if a["scope"] == "hfx" else "symbols"
            cur = hb if a["scope"] == "hfx" else mb
            cur[key] = [x for x in cur[key] if x not in a["value"]]
            await coll.update_one({"user_id": uid}, {"$set": {key: cur[key]}}, upsert=True)
        elif a["field"] in ("plugin_on", "plugin_off"):
            on = a["field"] == "plugin_on"
            plugins[a["value"]]["enabled"] = on
            await db.plugins.update_one({"user_id": uid}, {"$set": {f"plugins.{a['value']}.enabled": on}}, upsert=True)
        else:
            (hb if a["scope"] == "hfx" else mb)[a["field"]] = a["value"]
            await coll.update_one({"user_id": uid}, {"$set": {a["field"]: a["value"]}}, upsert=True)
        adjs[i]["applied"] = True
        applied.append(a)
        msg = f"Ajuste IA aplicado: {a['label']} {a['from']} → {a['to']}"
        if a["scope"] == "hfx":
            await db.bot_logs.insert_one({"log_id": uuid.uuid4().hex[:16], "user_id": uid, "kind": "fix", "msg": msg,
                                          "scope": "hfx", "created_at": datetime.now(timezone.utc).isoformat()})
        else:
            await bot_log(uid, "fix", msg)
    await db.daily_summaries.update_one({"user_id": uid, "date": body.date}, {"$set": {"adjustments": adjs}})
    return {"applied": len(applied), "skipped": skipped, "adjustments": adjs}


@api.get("/confluence")
async def confluence_ep(request: Request, symbol: str, tf: str = "1h", votes: int = 2, score: float = 55):
    u = await get_user(request)
    if symbol not in ASSET_INFO or tf not in TIMEFRAMES:
        raise HTTPException(400, "Ativo ou timeframe inválido")
    plugins = await user_plugins(u["user_id"])
    df = await get_df(symbol, tf)
    d = await asyncio.to_thread(confluence_detail, df, plugins, {"min_votes": votes, "min_score": score})
    sig = int(d["signals"][-2]) if len(df) > 1 else 0
    return {"symbol": symbol, "display": display(symbol), "tf": tf, "signal": "BUY" if sig > 0 else "SELL" if sig < 0 else None,
            "trend": d["trend"], "votes_up": d["votes_up"], "votes_dn": d["votes_dn"], "score_up": d["score_up"], "score_dn": d["score_dn"],
            "plugins": [{"plugin": k, "label": PLUGIN_META[k]["label"], **v} for k, v in d["plugins"].items()],
            "min_votes": votes, "min_score": score}


def _ai_bucket(c: int) -> str:
    return "85%+" if c >= 85 else "70–84%" if c >= 70 else "<70%"


@api.get("/ai/filter-stats")
async def ai_filter_stats(request: Request, scope: str = "hfx", days: int = 7):
    u = await get_user(request)
    uid = u["user_id"]
    if scope not in ("hfx", "bot"):
        raise HTTPException(400, "Âmbito inválido")
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    if scope == "hfx":
        rows = await db.hfx_trades.find({"user_id": uid, "origin": "bot", "opened_ts": {"$gte": since.timestamp()}},
                                        {"_id": 0, "status": 1, "profit": 1, "ai": 1}).to_list(10000)
        closed = [(r.get("ai"), r["status"] == "won", r.get("profit", 0.0)) for r in rows if r["status"] in ("won", "lost", "tie")]
        open_n = sum(1 for r in rows if r.get("ai") and r["status"] == "open")
    else:
        rows = await db.positions.find({"user_id": uid, "source": "bot", "opened_at": {"$gte": since.isoformat()}},
                                       {"_id": 0, "status": 1, "pnl": 1, "ai": 1}).to_list(10000)
        closed = [(r.get("ai"), (r.get("pnl") or 0) > 0, r.get("pnl") or 0.0) for r in rows if r["status"] == "closed"]
        open_n = sum(1 for r in rows if r.get("ai") and r["status"] == "open")
    rej = await db.ai_decisions.find({"user_id": uid, "scope": scope, "created_at": {"$gte": since.isoformat()}},
                                     {"_id": 0}).sort("created_at", -1).to_list(5000)

    def perf(items: list) -> dict:
        n = len(items)
        w = sum(1 for _, won, _ in items if won)
        return {"trades": n, "wins": w, "winrate": w / n * 100 if n else 0.0, "pnl": round(sum(p for _, _, p in items), 2)}
    approved = [c for c in closed if c[0]]
    approved_n = sum(1 for r in rows if r.get("ai"))
    buckets = {}
    for c in approved:
        buckets.setdefault(_ai_bucket(int(c[0].get("confidence", 0))), []).append(c)
    reasons: Dict[str, int] = {}
    for r in rej:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    total = approved_n + len(rej)
    return {"scope": scope, "days": days, "evaluated": total, "approved": approved_n, "rejected": len(rej),
            "approval_rate": approved_n / total * 100 if total else 0.0, "open": open_n,
            "approved_perf": perf(approved), "no_ai_perf": perf([c for c in closed if not c[0]]),
            "by_confidence": [{"bucket": b, **perf(buckets[b])} for b in ("85%+", "70–84%", "<70%") if b in buckets],
            "top_reasons": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:5]],
            "recent_rejections": [{k: r.get(k) for k in ("symbol", "side", "confidence", "reason", "created_at")} for r in rej[:10]]}


@api.get("/ai/daily-summaries")
async def ai_daily_summaries(request: Request):
    u = await get_user(request)
    return await db.daily_summaries.find({"user_id": u["user_id"]}, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(60)


@api.get("/bot/daily-results")
async def bot_daily_results(request: Request, scope: str = "all", days: int = 30):
    u = await get_user(request)
    uid = u["user_id"]
    if scope not in ("all", "bot", "hfx", "portfolio"):
        raise HTTPException(400, "Âmbito inválido")
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows: List[tuple] = []  # (date, pnl, won, source)
    pq = {} if scope == "portfolio" else {"source": "bot"}
    hq = {} if scope == "portfolio" else {"origin": "bot"}
    if scope in ("all", "bot", "portfolio"):
        async for p in db.positions.find({"user_id": uid, **pq, "status": "closed", "closed_at": {"$gte": since.isoformat()}},
                                         {"_id": 0, "closed_at": 1, "pnl": 1}):
            rows.append((p["closed_at"][:10], float(p.get("pnl") or 0), (p.get("pnl") or 0) > 0, "bot"))
    if scope in ("all", "hfx", "portfolio"):
        async for t in db.hfx_trades.find({"user_id": uid, **hq, "status": {"$in": ["won", "lost", "tie"]},
                                           "expires_ts": {"$gte": since.timestamp()}}, {"_id": 0, "expires_ts": 1, "profit": 1, "status": 1}):
            d = datetime.fromtimestamp(t["expires_ts"], timezone.utc).strftime("%Y-%m-%d")
            rows.append((d, float(t.get("profit") or 0), t["status"] == "won", "hfx"))
    acc = await get_account(uid)
    by: Dict[str, dict] = {}
    for d, pnl, won, src in rows:
        x = by.setdefault(d, {"date": d, "trades": 0, "wins": 0, "pnl": 0.0, "bot": 0.0, "hfx": 0.0})
        x["trades"] += 1
        x["wins"] += won
        x["pnl"] += pnl
        x[src] += pnl
    total_pnl = sum(x["pnl"] for x in by.values())
    # walk back from the current balance to get each day's starting equity → daily %
    eq = float(acc["balance"]) - total_pnl
    out = []
    for d in sorted(by):
        x = by[d]
        x["pct"] = round(x["pnl"] / eq * 100, 3) if eq > 0 else 0.0
        x["winrate"] = x["wins"] / x["trades"] * 100 if x["trades"] else 0.0
        eq += x["pnl"]
        x.update({k: round(x[k], 2) for k in ("pnl", "bot", "hfx")})
        out.append(x)
    n = len(rows)
    wins = sum(1 for r in rows if r[2])
    pos_days = sum(1 for x in out if x["pnl"] > 0)
    start = float(acc["balance"]) - total_pnl
    return {"scope": scope, "days": days, "daily": out[::-1], "total": {
        "pnl": round(total_pnl, 2), "pct": round(total_pnl / start * 100, 2) if start > 0 else 0.0, "trades": n, "wins": wins,
        "winrate": wins / n * 100 if n else 0.0, "trading_days": len(out), "green_days": pos_days, "red_days": len(out) - pos_days,
        "avg_day_pnl": round(total_pnl / len(out), 2) if out else 0.0,
        "avg_day_pct": round(sum(x["pct"] for x in out) / len(out), 3) if out else 0.0,
        "best_day": max(out, key=lambda x: x["pnl"]) if out else None, "worst_day": min(out, key=lambda x: x["pnl"]) if out else None}}


class MtConnectIn(BaseModel):
    login: str = Field(pattern=r"^\d{3,12}$")
    password: str = Field(min_length=1, max_length=64)
    server: str = Field(min_length=2, max_length=80)
    platform: str = Field("mt4", pattern="^(mt4|mt5)$")


@api.post("/live/mt/connect")
async def mt_connect(body: MtConnectIn, request: Request):
    u = await get_user(request)
    if not metaapi_exec.configured():
        raise HTTPException(400, "Falta o token MetaApi")
    try:
        acc_id = await metaapi_exec.provision(body.login, body.password, body.server, body.platform)
    except (metaapi_exec.MetaApiError, httpx.HTTPError) as e:
        raise HTTPException(400, f"MetaApi: {e}")
    await db.live_accounts.update_one({"user_id": u["user_id"], "kind": "mt"}, {"$set": {
        "account_id": acc_id, "region": "new-york", "login": body.login, "server": body.server, "platform": body.platform,
        "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)  # password is NOT stored
    return {"account_id": acc_id}


@api.delete("/live/mt")
async def mt_disconnect(request: Request):
    u = await get_user(request)
    await db.live_accounts.delete_one({"user_id": u["user_id"], "kind": "mt"})
    await db.bots.update_one({"user_id": u["user_id"], "live_mode": "metatrader"}, {"$set": {"live_mode": "paper"}})
    return {"ok": True}


@api.get("/live/mt/status")
async def mt_status(request: Request):
    u = await get_user(request)
    acc = await _mt_acc(u["user_id"])
    out = {"configured": metaapi_exec.configured(), "account": None, "error": None}
    if acc and out["configured"]:
        out["account"] = {k: acc.get(k) for k in ("login", "server", "platform")}
        try:
            st = await metaapi_exec.account_state(acc["account_id"])
            out["account"].update(st)
            if st["connection"] == "CONNECTED":
                inf = await metaapi_exec.info(acc["account_id"], acc["region"])
                out["account"].update({k: inf.get(k) for k in ("balance", "equity", "currency", "leverage", "type", "broker")})
                out["account"]["positions"] = len(await metaapi_exec.positions(acc["account_id"], acc["region"]))
        except (metaapi_exec.MetaApiError, httpx.HTTPError) as e:
            out["error"] = str(e)
    return out


@api.get("/ea/all")
async def ea_all_preview(request: Request):
    """List of setups that the generated 'Todas as Estratégias' EA will trade."""
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    cfgs = ea_gen.build_configs(bot, HTF_MAP, FEES, ASSET_INFO)
    return {"count": len(cfgs), "setups": [{k: c[k] for k in ("kind", "symbol", "mt_symbol", "tf", "label", "rr", "sl_atr", "min", "mtf", "htf")} for c in cfgs]}


@api.post("/ea/all/link")
async def ea_all_link(request: Request):
    """Short-lived download link (the browser/phone download cannot send the auth header)."""
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    if not ea_gen.build_configs(bot, HTF_MAP, FEES, ASSET_INFO):
        raise HTTPException(400, "O robô ainda não tem setups. Otimiza primeiro (Otimizar tudo / 12C / Sniper 20).")
    await db.ea_links.delete_many({"expires": {"$lt": time.time()}})
    token = uuid.uuid4().hex
    await db.ea_links.insert_one({"token": token, "user_id": u["user_id"], "expires": time.time() + 900})
    return {"path": f"/ea/all/{token}/{'SmartTradeNow' if request.query_params.get('script') else 'SmartTradeAll'}.mq5"}


@api.get("/ea/all/{token}/{name}.mq5")
async def ea_all_download(token: str, name: str):
    from fastapi.responses import Response
    if name not in ("SmartTradeAll", "SmartTradeNow"):
        raise HTTPException(404, "Ficheiro desconhecido")
    link = await db.ea_links.find_one({"token": token}, {"_id": 0})
    if not link or link["expires"] < time.time():
        raise HTTPException(404, "Link expirado — gera um novo na app")
    bot = await get_bot(link["user_id"])
    user = await db.users.find_one({"user_id": link["user_id"]}, {"_id": 0, "email": 1}) or {}
    plugins = await user_plugins(link["user_id"])
    fn = ea_gen.render_script if name == "SmartTradeNow" else ea_gen.render
    src = fn(bot, plugins, ea_gen.build_configs(bot, HTF_MAP, FEES, ASSET_INFO), user.get("email", link["user_id"]))
    return Response(src.encode("utf-8"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.mq5"'})


@api.get("/ea/SmartTrade12C.mq5")
async def ea_download():
    """MQL5 source of the '12 Confirmações' Expert Advisor (compile in MetaEditor to get the .ex5)."""
    from fastapi.responses import FileResponse
    return FileResponse(ROOT_DIR / "static" / "SmartTrade12C.mq5", media_type="text/plain",
                        filename="SmartTrade12C.mq5")


@api.get("/live/status")
async def live_status(request: Request):
    await get_user(request)
    out = {"configured": binance_exec.configured(), "env": binance_exec.env(), "balances": [], "error": None}
    if out["configured"]:
        try:
            out["balances"] = (await binance_exec.balances())[:12]
        except (binance_exec.BinanceError, httpx.HTTPError) as e:
            out["error"] = str(e)
    return out


@api.post("/bot/run")
async def bot_run_now(request: Request):
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    if not bot["enabled"]:
        raise HTTPException(400, "Ativa o robô primeiro")
    opened = await run_bot_cycle(bot)
    return {"opened": opened}


app.include_router(api)
hfx_router = hfx.build_router(db, get_user, get_account)
app.include_router(hfx_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.positions.create_index([("user_id", 1), ("status", 1)])
    await db.plugins.create_index("user_id", unique=True)
    await db.bots.create_index("user_id", unique=True)
    await db.bot_logs.create_index([("user_id", 1), ("created_at", -1)])
    asyncio.create_task(bot_loop())
    asyncio.create_task(hfx_router.loop())
    await db.bot_opt_jobs.create_index("job_id", unique=True)
    await resume_opt_jobs()
    await db.hfx_trades.create_index([("status", 1), ("expires_ts", 1)])
    await db.hfx_trades.create_index([("user_id", 1), ("status", 1)])
    await db.hfx_bots.create_index("user_id", unique=True)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
