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

from strategies import PLUGIN_DEFAULTS, PLUGIN_META, FEES, compute_signals, smc_analyze, atr, run_backtest, optimize, strategy_signals, trend_filtered, apply_filters, mtf_filtered, htf_trend, ema, rsi  # noqa: E402

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


HTF_MAP = {"1m": "15m", "5m": "1h", "15m": "4h", "1h": "4h", "4h": "1d", "1d": None}


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
    await db.user_sessions.insert_one({"session_token": data["session_token"], "user_id": user_id,
                                       "expires_at": now + timedelta(days=7), "created_at": now})
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
    df = await get_df(symbol, tf)
    smc = smc_analyze(df)
    df = df.iloc[-limit:]
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
    }

# ---------------------------------------------------------------- plugins
PARAM_RANGES = {"swing": (1, 20), "length": (2, 200), "oversold": (1, 50), "overbought": (50, 99),
                "fast": (2, 200), "slow": (3, 400), "signal": (2, 100), "mult": (0.5, 5)}


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


@api.post("/backtest")
async def backtest(body: BacktestIn, request: Request):
    u = await get_user(request)
    plugins = await user_plugins(u["user_id"])
    if body.strategy != "combo" and body.strategy not in PLUGIN_DEFAULTS:
        raise HTTPException(400, "Estratégia inválida")
    if not (0.1 <= body.risk_pct <= 10 and 0.3 <= body.sl_atr <= 10 and 0.5 <= body.rr <= 10 and body.capital > 0):
        raise HTTPException(400, "Parâmetros fora dos limites")
    df = await get_df(body.symbol, body.tf, long=True)
    if len(df) < 250:
        raise HTTPException(400, "Histórico insuficiente para backtest")
    fee = FEES[ASSET_INFO[body.symbol]["category"]]
    htf = await get_htf(body.symbol, body.tf) if body.mtf else None
    res = await asyncio.to_thread(run_backtest, df, body.strategy, plugins, body.sl_atr, body.rr, body.risk_pct, body.capital,
                                  fee, body.trend_filter, body.breakeven, body.mtf and htf is not None, htf)
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


OPT_TFS = ["1m", "5m", "15m", "1h", "4h", "1d"]
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


async def close_position(p: dict, price: float, reason: str):
    pnl = pnl_of(p, price)
    await db.positions.update_one({"position_id": p["position_id"]}, {"$set": {
        "status": "closed", "exit": price, "pnl": pnl, "reason": reason, "closed_at": datetime.now(timezone.utc).isoformat()}})
    await db.accounts.update_one({"user_id": p["user_id"]}, {"$inc": {"balance": pnl}})
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
    return {"balance": acc["balance"], "equity": acc["balance"] + unreal, "unrealized": unreal, "realized": realized,
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
    await db.accounts.update_one({"user_id": u["user_id"]}, {"$set": {"balance": START_BALANCE, "start_balance": START_BALANCE}}, upsert=True)
    return {"ok": True}


# ---------------------------------------------------------------- auto-trading bot (paper)
BOT_DEFAULT = {"enabled": False, "symbols": ["BTC-USD", "ETH-USD", "EURUSD=X"], "tf": "1h", "strategy": "smc", "trend_filter": True, "mtf": True, "setups": [],
               "risk_pct": 1.0, "sl_atr": 1.5, "rr": 2.0, "max_positions": 3}


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
    max_positions: int = Field(3, ge=1, le=10)
    trend_filter: bool = True
    mtf: bool = True
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
        if not reason and p.get("stop_dist") and not p.get("be"):
            one_r = p["entry"] + (1 if long else -1) * p["stop_dist"]
            if (long and px >= one_r) or (not long and px <= one_r):
                await db.positions.update_one({"position_id": p["position_id"]}, {"$set": {"stop_loss": p["entry"], "be": True}})
                await bot_log(user_id, "be", f"{display(p['symbol'])}: stop movido para break-even (+1R atingido)", p["symbol"])
        if reason:
            pnl = await close_position(p, px, reason)
            if p.get("source") == "bot":
                await bot_log(user_id, "close", f"{display(p['symbol'])} fechado por {'stop' if reason == 'stop_loss' else 'alvo'}: {pnl:+.2f} $", p["symbol"])


_bot_locks: Dict[str, asyncio.Lock] = {}


async def run_bot_cycle(bot: dict) -> int:
    lock = _bot_locks.setdefault(bot["user_id"], asyncio.Lock())
    async with lock:
        return await _run_bot_cycle(bot)


async def _run_bot_cycle(bot: dict) -> int:
    """One pass: evaluate each symbol's last CLOSED bar and open/close bot positions. Returns trades opened."""
    uid = bot["user_id"]
    bot = await get_bot(uid)  # fresh state (last_bar) under the lock
    await check_exits(uid)
    plugins = await user_plugins(uid)
    acc = await get_account(uid)
    opened = 0
    setups = bot.get("setups") or []
    with_setup = {x["symbol"] for x in setups}
    jobs = [{"symbol": s, "tf": bot["tf"], "strategy": bot["strategy"], "sl_atr": bot["sl_atr"], "rr": bot["rr"],
             "trend_filter": bot.get("trend_filter", True), "mtf": bot.get("mtf", True)}
            for s in bot["symbols"] if s not in with_setup] + setups
    for cfg in jobs:
        sym = cfg["symbol"]
        if sym not in ASSET_INFO:
            continue
        key = f"{sym}|{cfg['tf']}"
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
        n_open = await db.positions.count_documents({"user_id": uid, "status": "open", "source": "bot"})
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
        qty = (acc["balance"] * bot["risk_pct"] / 100) / stop
        qty = min(qty, acc["balance"] * 10 / price)
        d = 1 if side == "BUY" else -1
        pos = {"position_id": uuid.uuid4().hex[:16], "user_id": uid, "symbol": sym, "side": side, "qty": float(qty),
               "entry": price, "stop_loss": price - d * stop, "take_profit": price + d * stop * cfg["rr"],
               "status": "open", "source": "bot", "setup": key, "tf": cfg["tf"], "stop_dist": float(stop), "opened_at": datetime.now(timezone.utc).isoformat()}
        await db.positions.insert_one(dict(pos))
        opened += 1
        dec = price_decimals(price)
        await bot_log(uid, "open", f"{'COMPRA' if side == 'BUY' else 'VENDA'} {tag}{(' · tendência ' + HTF_MAP[cfg['tf']].upper() + ' confirmada') if cfg.get('mtf') and htf is not None else ''} @ {price:.{dec}f} · SL {pos['stop_loss']:.{dec}f} · TP {pos['take_profit']:.{dec}f}", sym)
    await db.bots.update_one({"user_id": uid}, {"$set": {"last_run": datetime.now(timezone.utc).isoformat()}}, upsert=True)
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
    logs = await db.bot_logs.find({"user_id": u["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
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
    if body.strategy != "combo" and body.strategy not in PLUGIN_DEFAULTS:
        raise HTTPException(400, "Estratégia inválida")
    syms = [s for s in body.symbols if s in ASSET_INFO]
    seen = set()
    for st in body.setups:
        if st.symbol not in ASSET_INFO or st.tf not in TIMEFRAMES or (st.strategy != "combo" and st.strategy not in PLUGIN_DEFAULTS):
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


@api.post("/bot/run")
async def bot_run_now(request: Request):
    u = await get_user(request)
    bot = await get_bot(u["user_id"])
    if not bot["enabled"]:
        raise HTTPException(400, "Ativa o robô primeiro")
    opened = await run_bot_cycle(bot)
    return {"opened": opened}


app.include_router(api)
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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
