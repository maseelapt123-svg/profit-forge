"""Binance Spot execution (testnet by default). Keys stay server-side; only crypto BUY entries are sent (spot cannot short)."""
import hashlib
import hmac
import math
import os
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

_filters: dict = {}


def configured() -> bool:
    return bool(os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET"))


def base_url() -> str:
    return os.environ.get("BINANCE_BASE_URL") or "https://testnet.binance.vision"


def env() -> str:
    return "testnet" if "testnet" in base_url() else "live"


def to_pair(symbol: str) -> Optional[str]:
    """yfinance 'BTC-USD' → Binance 'BTCUSDT'."""
    if symbol.endswith("-USD"):
        return symbol[:-4].replace("-", "") + "USDT"
    return None


class BinanceError(Exception):
    pass


async def _req(method: str, path: str, params: Optional[dict] = None, signed: bool = True):
    params = {k: str(v) for k, v in (params or {}).items() if v is not None}
    headers = {}
    if signed:
        params["timestamp"] = str(int(time.time() * 1000))
        params["recvWindow"] = "5000"
        q = urlencode(params)
        params["signature"] = hmac.new(os.environ["BINANCE_API_SECRET"].encode(), q.encode(), hashlib.sha256).hexdigest()
        headers["X-MBX-APIKEY"] = os.environ["BINANCE_API_KEY"]
    async with httpx.AsyncClient(base_url=base_url(), timeout=15) as c:
        r = await c.request(method, path, params=params, headers=headers)
    if r.is_error:
        try:
            msg = r.json().get("msg", r.text)
        except ValueError:
            msg = r.text
        raise BinanceError(str(msg)[:200])
    return r.json()


async def _symbol_filters(pair: str) -> dict:
    if pair not in _filters:
        info = await _req("GET", "/api/v3/exchangeInfo", {"symbol": pair}, signed=False)
        f = {x["filterType"]: x for x in info["symbols"][0]["filters"]}
        lot = f.get("MARKET_LOT_SIZE") or f.get("LOT_SIZE") or {}
        step = float(lot.get("stepSize") or f.get("LOT_SIZE", {}).get("stepSize") or 0.000001)
        if step <= 0:
            step = float(f.get("LOT_SIZE", {}).get("stepSize", 0.000001))
        notional = float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5))
        _filters[pair] = {"step": step, "min_notional": notional}
    return _filters[pair]


def _floor(qty: float, step: float) -> str:
    n = math.floor(qty / step + 1e-9) * step
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return f"{n:.{dec}f}"


async def balances() -> list:
    d = await _req("GET", "/api/v3/account", {"omitZeroBalances": "true"})
    return [b for b in d.get("balances", []) if float(b["free"]) + float(b["locked"]) > 0]


def _fill(res: dict) -> tuple:
    qty = float(res.get("executedQty") or 0)
    quote = float(res.get("cummulativeQuoteQty") or 0)
    return qty, (quote / qty if qty else 0.0)


async def market_buy(pair: str, quote_usdt: float, client_id: str) -> dict:
    f = await _symbol_filters(pair)
    if quote_usdt < f["min_notional"]:
        raise BinanceError(f"valor {quote_usdt:.2f} USDT abaixo do mínimo da Binance ({f['min_notional']:.2f})")
    res = await _req("POST", "/api/v3/order", {"symbol": pair, "side": "BUY", "type": "MARKET",
                                               "quoteOrderQty": f"{quote_usdt:.2f}", "newClientOrderId": client_id,
                                               "newOrderRespType": "FULL"})
    qty, px = _fill(res)
    return {"order_id": res.get("orderId"), "qty": qty, "price": px, "status": res.get("status")}


async def market_sell(pair: str, qty: float, client_id: str) -> dict:
    f = await _symbol_filters(pair)
    q = _floor(qty, f["step"])
    if float(q) <= 0:
        raise BinanceError("quantidade abaixo do passo mínimo")
    res = await _req("POST", "/api/v3/order", {"symbol": pair, "side": "SELL", "type": "MARKET", "quantity": q,
                                               "newClientOrderId": client_id, "newOrderRespType": "FULL"})
    sq, px = _fill(res)
    return {"order_id": res.get("orderId"), "qty": sq, "price": px, "status": res.get("status")}
