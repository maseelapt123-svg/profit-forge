"""MetaApi cloud bridge: the bot's trades go to an MT4/MT5 (demo) account, visible in the MetaTrader app.
Token stays server-side; broker passwords are sent once to MetaApi and never stored."""
import os
import uuid
from typing import Optional

import httpx

PROV = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
HOSTS = {"new-york": "https://mt-client-api-v1.new-york.agiliumtrade.ai",
         "london": "https://mt-client-api-v1.london.agiliumtrade.ai"}


class MetaApiError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("METAAPI_TOKEN"))


async def _call(method: str, url: str, json: Optional[dict] = None, headers: Optional[dict] = None):
    h = {"Accept": "application/json", "auth-token": os.environ["METAAPI_TOKEN"], **(headers or {})}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, url, json=json, headers=h)
    if r.status_code >= 400:
        try:
            j = r.json()
            msg = j.get("message", r.text) + (f" {j['details']}" if j.get("details") else "")
        except ValueError:
            msg = r.text
        raise MetaApiError(str(msg)[:200])
    return None if r.status_code == 204 or not r.content else r.json()


async def provision(login: str, password: str, server: str, platform: str, region: str = "new-york") -> str:
    res = await _call("POST", f"{PROV}/users/current/accounts", headers={"transaction-id": uuid.uuid4().hex}, json={
        "login": login, "password": password, "name": f"SmartTrade {login}", "server": server, "platform": platform,
        "region": region, "magic": 10001, "type": "cloud-g2"})
    return res["id"]


async def account_state(acc_id: str) -> dict:
    a = await _call("GET", f"{PROV}/users/current/accounts/{acc_id}")
    return {"state": a.get("state"), "connection": a.get("connectionStatus"), "region": a.get("region", "new-york")}


async def list_accounts() -> list:
    r = await _call("GET", f"{PROV}/users/current/accounts") or []
    return [{"id": a["_id"], "name": a.get("name"), "login": a.get("login"), "server": a.get("server"),
             "platform": a.get("platform") or f"mt{a.get('version', 5)}", "region": a.get("region", "new-york"),
             "state": a.get("state"), "connection": a.get("connectionStatus")} for a in r]


async def deploy(acc_id: str) -> None:
    await _call("POST", f"{PROV}/users/current/accounts/{acc_id}/deploy")


async def symbols(acc_id: str, region: str) -> list:
    return await _call("GET", f"{_host(region)}/users/current/accounts/{acc_id}/symbols") or []


async def price(acc_id: str, region: str, symbol: str) -> dict:
    return await _call("GET", f"{_host(region)}/users/current/accounts/{acc_id}/symbols/{symbol}/current-price")


async def spec(acc_id: str, region: str, symbol: str) -> dict:
    return await _call("GET", f"{_host(region)}/users/current/accounts/{acc_id}/symbols/{symbol}/specification")


def _host(region: str) -> str:
    return HOSTS.get(region, HOSTS["new-york"])


async def info(acc_id: str, region: str) -> dict:
    return await _call("GET", f"{_host(region)}/users/current/accounts/{acc_id}/account-information")


async def positions(acc_id: str, region: str) -> list:
    return await _call("GET", f"{_host(region)}/users/current/accounts/{acc_id}/positions") or []


async def trade(acc_id: str, region: str, body: dict) -> dict:
    r = await _call("POST", f"{_host(region)}/users/current/accounts/{acc_id}/trade", json=body)
    if r and r.get("stringCode") not in (None, "TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "ERR_NO_ERROR"):
        raise MetaApiError(f"{r.get('stringCode')}: {r.get('message', '')}")
    return r or {}


def to_mt_symbol(symbol: str, suffix: str = "") -> Optional[str]:
    """yfinance symbol -> typical MetaTrader symbol (brokers may add a suffix like '.m'); existence is checked by the caller."""
    special = {"GC=F": "XAUUSD", "SI=F": "XAGUSD", "CL=F": "USOUSD", "BZ=F": "UKOUSD",
               "^NDX": "NAS100", "^GSPC": "SP500", "^DJI": "DJ30", "^GDAXI": "GER40", "^FTSE": "UK100", "^FCHI": "FRA40", "^HSI": "HK50",
               "DOGE-USD": "DOGUSD", "AVAX-USD": "AVAUSD", "ALGO-USD": "ALGUSD", "AMZN": "AMAZON", "NVDA": "NVIDIA"}
    if symbol in special:
        return special[symbol] + suffix
    if symbol.endswith("=X"):
        return symbol[:-2] + suffix
    if symbol.endswith("-USD"):
        return symbol.replace("-", "") + suffix
    return symbol + suffix if symbol.isalpha() else None


def lots(symbol: str, qty: float, max_lots: float) -> float:
    """Units → lots (forex 100k, gold 100 oz, silver 5000 oz, crypto 1 coin), min 0.01, capped."""
    size = 100000 if symbol.endswith("=X") else 100 if symbol == "GC=F" else 5000 if symbol == "SI=F" else 1
    return max(0.01, min(max_lots, round(qty / size, 2)))
