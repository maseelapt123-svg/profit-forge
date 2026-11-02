"""Generates SmartTradeAll.mq5: one MT5 Expert Advisor holding every optimised setup of the user's bot
(strategy setups + 12 Confirmações + Sniper 20 per pair, with their TF, R:R, stops, filters and confirmations)."""
import json
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TPL = Path(__file__).parent / "static" / "SmartTradeAll.mq5.tpl"
MT_TF = {"1m": "PERIOD_M1", "2m": "PERIOD_M2", "3m": "PERIOD_M3", "5m": "PERIOD_M5", "15m": "PERIOD_M15",
         "1h": "PERIOD_H1", "4h": "PERIOD_H4", "1d": "PERIOD_D1"}
STRAT_NAMES = {"c12": "12C", "c20": "20C"}


def mt_symbol(symbol: str) -> Optional[str]:
    from metaapi_exec import to_mt_symbol
    return to_mt_symbol(symbol)


def build_configs(bot: dict, htf_map: dict, fees: dict, asset_info: dict) -> list:
    """Same job list the app's bot runs (see _run_bot_cycle / _run_stream), with the bot's auto-fixes applied."""
    fixes = bot.get("fixes") or {}
    paused = set(fixes.get("paused", []))
    setups = bot.get("setups") or []
    with_setup = {x["symbol"] for x in setups}
    jobs = [{"symbol": s, "tf": bot["tf"], "strategy": bot["strategy"], "sl_atr": bot["sl_atr"], "rr": bot["rr"],
             "trend_filter": bot.get("trend_filter", True), "mtf": bot.get("mtf", True)}
            for s in bot["symbols"] if s not in with_setup] + setups
    ptp_r = float(bot.get("ptp_r", 1.0))
    out = []
    for j in jobs:
        if j["symbol"] not in asset_info or f"{j['symbol']}|{j['tf']}" in paused:
            continue
        out.append({"kind": 0, "symbol": j["symbol"], "tf": j["tf"], "strategy": j["strategy"], "min": 0,
                    "sl_atr": min(5.0, j["sl_atr"] + 0.5) if fixes.get("widen_stop") else float(j["sl_atr"]),
                    "rr": float(j["rr"]), "trend": bool(j.get("trend_filter", True)),
                    "mtf": bool(j.get("mtf")) or bool(fixes.get("force_mtf")), "ptp_r": ptp_r})
    for k, kind in (("c12", 1), ("c20", 2)):
        pairs = {p["symbol"]: p for p in (bot.get(f"{k}_pairs") or [])}
        if not bot.get(f"{k}_enabled") and not pairs:
            continue
        tf0, need0 = bot.get(f"{k}_tf") or "1h", int(bot.get(f"{k}_min", 10))
        rr0 = float(bot.get(f"{k}_rr") or bot["rr"])
        for sym in bot["symbols"]:
            ov = pairs.get(sym)
            if sym not in asset_info or (ov and not ov.get("enabled", True)):
                continue
            tf, need, rr = (ov["tf"], int(ov["min"]), float(ov["rr"])) if ov else (tf0, need0, rr0)
            out.append({"kind": kind, "symbol": sym, "tf": tf, "strategy": k, "min": need, "sl_atr": float(bot["sl_atr"]),
                        "rr": rr, "trend": False, "mtf": True,
                        "ptp_r": float(bot.get("c20_ptp_r", 2.0)) if k == "c20" else ptp_r})
    for c in out:
        c["mt_symbol"] = mt_symbol(c["symbol"])
        c["htf"] = htf_map.get(c["tf"])
        c["fee"] = fees[asset_info[c["symbol"]]["category"]]
        c["label"] = f"{STRAT_NAMES.get(c['strategy'], c['strategy'])} {c['tf'].upper()}" + (f" {c['min']}/{12 if c['kind'] == 1 else 20}" if c["kind"] else "")
    out = [c for c in out if c["mt_symbol"] and c["tf"] in MT_TF]
    used = set()
    for c in out:  # stable id per setup so re-downloads keep managing the same open trades
        m = zlib.crc32(f"{c['symbol']}|{c['tf']}|{c['kind']}|{c['strategy']}".encode()) % 900000
        while m in used:
            m = (m + 1) % 900000
        used.add(m)
        c["magic"] = m
    return out


def _arr(typ: str, name: str, vals: list) -> str:
    return f"{typ} {name}[] = {{{', '.join(vals)}}};"


def _s(x: str) -> str:
    return json.dumps(x)


def _f(x: float) -> str:
    return repr(float(x))


def render(bot: dict, plugins: dict, configs: list, user: str, script: bool = False) -> str:
    cfg = [f"#define NCFG {len(configs)}",
           _arr("string", "CSym", [_s(c["mt_symbol"]) for c in configs]),
           _arr("string", "CLabel", [_s(c["label"]) for c in configs]),
           _arr("ENUM_TIMEFRAMES", "CTf", [MT_TF[c["tf"]] for c in configs]),
           _arr("ENUM_TIMEFRAMES", "CHtf", [MT_TF.get(c["htf"] or "", "PERIOD_CURRENT") for c in configs]),
           _arr("long", "CMagic", [str(c["magic"]) for c in configs]),
           _arr("int", "CKind", [str(c["kind"]) for c in configs]),
           _arr("string", "CStrat", [_s(c["strategy"]) for c in configs]),
           _arr("int", "CMin", [str(c["min"]) for c in configs]),
           _arr("double", "CSl", [_f(c["sl_atr"]) for c in configs]),
           _arr("double", "CRr", [_f(c["rr"]) for c in configs]),
           _arr("double", "CPtpR", [_f(c["ptp_r"]) for c in configs]),
           _arr("double", "CFee", [_f(c["fee"]) for c in configs]),
           _arr("bool", "CTrend", ["true" if c["trend"] else "false" for c in configs]),
           _arr("bool", "CMtf", ["true" if c["mtf"] else "false" for c in configs])]
    names = [k for k in plugins if not k.startswith("_")]
    keys, vals = [], []
    for k in names:
        for p, v in plugins[k].items():
            keys.append(f"{k}.{p}")
            vals.append(_f(1.0 if v is True else 0.0 if v is False else v))
    conf = {"min_votes": bot.get("conf_votes", 2), "min_score": bot.get("conf_score", 55.0), "horizon": 10, "memory": 3, "lookback": 300}
    for p, v in conf.items():
        keys.append(f"_conf.{p}")
        vals.append(_f(v))
    keys += ["_c12.min", "_c20.min"]
    vals += [_f(bot.get("c12_min", 10)), _f(16)]
    hours = [str(int(h)) for h in ((bot.get("fixes") or {}).get("hours") or [])] or ["-1"]
    cfg += [_arr("string", "Plugins", [_s(n) for n in names]), _arr("string", "PKey", [_s(k) for k in keys]),
            _arr("double", "PVal", vals), _arr("int", "BlockHours", hours)]
    table = "\n".join(f"//   {i:>2}. {c['mt_symbol']:<8} {c['label']:<22} R:R 1:{c['rr']:g} · SL {c['sl_atr']:g}xATR"
                      f"{' · TF sup. ' + c['htf'].upper() if c['mtf'] and c['htf'] else ''}" for i, c in enumerate(configs, 1))
    rep = {
        "__USER__": user, "__DATE__": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "__RISK__": _f(bot.get("risk_pct", 1.0)),
        "__C12ON__": "true" if any(c["kind"] == 1 for c in configs) else "false",
        "__C20ON__": "true" if any(c["kind"] == 2 for c in configs) else "false",
        "__MAXS__": str(int(bot.get("max_positions", 30))), "__MAX12__": str(int(bot.get("c12_max_positions", 30))),
        "__MAX20__": str(int(bot.get("c20_max_positions", 30))),
        "__PTPON__": "true" if bot.get("ptp_enabled", True) else "false", "__PTPPCT__": _f(bot.get("ptp_pct", 50)),
        "__BEON__": "true" if bot.get("breakeven_enabled", True) else "false",
        "__MAXLOTS__": _f(bot.get("mt_max_lots", 0.1)), "__SUFFIX__": (bot.get("mt_suffix") or "").replace('"', ""),
        "__CONFIG__": "// ---- setups otimizados na app:\n" + table + "\n" + "\n".join(cfg),
        "//__RUNTIME__\n": "//__RUNTIME__\n" if script else "",
    }
    src = TPL.read_text(encoding="utf-8")
    for k, v in rep.items():
        src = src.replace(k, v)
    return src


SCRIPT_MAIN = r'''void OnStart() {
   ArrayResize(LastBar, NCFG); for(int i = 0; i < NCFG; i++) LastBar[i] = 0;
   SrvOffset = (long)(MathRound((double)(TimeTradeServer() - TimeGMT()) / 1800.0) * 1800);
   SigBars = MathMax(1, SignalBars); StreamCap = MathMax(1, MaxNewPerKind);
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) { Alert("Ativa o botão 'Algo Trading' e 'Permitir Algo Trading' nas propriedades do script."); return; }
   for(int i = 0; i < NCFG; i++) if(!SymbolSelect(Sym(i), true)) PrintFormat("Símbolo %s não existe nesta corretora — ajusta o sufixo (SymbolSuffix).", Sym(i));
   string plan = ""; int o12 = 0, o20 = 0, n = 0;
   for(int i = 0; i < NCFG; i++) if(SymbolInfoInteger(Sym(i), SYMBOL_SELECT) && Evaluate(i, o12, o20, true, plan)) n++;
   if(n == 0) { Alert(StringFormat("SmartTrade: nenhum dos %d setups tem sinal válido nas últimas %d velas. Nada aberto.", NCFG, SigBars)); return; }
   string acc = AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL ? "CONTA REAL" : "conta demo";
   if(AskConfirmation && MessageBox(StringFormat("Abrir %d ordens na %s (risco %.2f%% cada)?\n\n%s", n, acc, RiskPercent, plan), "SmartTrade — abrir ordens com sinal", MB_YESNO | MB_ICONQUESTION) != IDYES) { Print("SmartTrade: cancelado."); return; }
   for(int i = 0; i < NCFG; i++) LastBar[i] = 0;
   o12 = 0; o20 = 0; int done = 0;
   for(int i = 0; i < NCFG; i++) if(SymbolInfoInteger(Sym(i), SYMBOL_SELECT) && Evaluate(i, o12, o20, false, plan)) done++;
   Alert(StringFormat("SmartTrade: %d de %d ordens abertas (detalhes no separador Experts). Para gerir stops/TP parcial deixa o SmartTradeAll ligado.", done, n));
}
'''


def render_script(bot: dict, plugins: dict, configs: list, user: str) -> str:
    """One-shot MT5 script: opens now every setup that has a valid signal (same rules/magic IDs as the EA)."""
    src = render(bot, plugins, configs, user, script=True)
    src = src.split("//__RUNTIME__")[0] + SCRIPT_MAIN
    src = src.replace('#property version   "2.00"', '#property version   "2.00"\n#property script_show_inputs')
    src = src.replace("//| SmartTradeAll.mq5 — Expert Advisor \"Todas as Estratégias\" (SmartTrade AI)",
                      "//| SmartTradeNow.mq5 — SCRIPT \"Abrir ordens com sinal agora\" (SmartTrade AI)\n"
                      "//| Corre UMA vez: analisa todos os setups, mostra a lista e, após confirmares, abre as ordens.")
    src = src.replace('input long   MagicBase', 'input int    SignalBars        = 3;          // Aceitar sinais das últimas N velas fechadas\n'
                      'input int    MaxNewPerKind     = 5;          // Máx. novas ordens 12C / 20C de uma vez\n'
                      'input bool   AskConfirmation   = true;       // Pedir confirmação antes de abrir\n'
                      'input long   MagicBase')
    return src
