"""Indicators, Smart Money Concepts detection, strategy plugins and backtest engine."""
import numpy as np
import pandas as pd
from typing import Optional

PLUGIN_DEFAULTS = {
    "smc": {"enabled": True, "swing": 3},
    "rsi": {"enabled": True, "length": 14, "oversold": 30.0, "overbought": 70.0},
    "ema_cross": {"enabled": True, "fast": 9, "slow": 21},
    "macd": {"enabled": False, "fast": 12, "slow": 26, "signal": 9},
    "bollinger": {"enabled": False, "length": 20, "mult": 2.0},
}

PLUGIN_META = {
    "smc": {"label": "Smart Money (SMC)", "desc": "Reteste de order blocks na direção do BOS/CHoCH",
            "params": {"swing": "Força do swing (velas)"}},
    "rsi": {"label": "RSI Reversão", "desc": "Saída das zonas de sobrecompra/sobrevenda",
            "params": {"length": "Período", "oversold": "Sobrevenda", "overbought": "Sobrecompra"}},
    "ema_cross": {"label": "Cruzamento EMA", "desc": "EMA rápida cruza a EMA lenta",
                  "params": {"fast": "EMA rápida", "slow": "EMA lenta"}},
    "macd": {"label": "MACD", "desc": "Linha MACD cruza a linha de sinal",
             "params": {"fast": "Rápida", "slow": "Lenta", "signal": "Sinal"}},
    "bollinger": {"label": "Bandas de Bollinger", "desc": "Regresso para dentro das bandas",
                  "params": {"length": "Período", "mult": "Desvios"}},
}


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def smc_analyze(df: pd.DataFrame, k: int = 3) -> dict:
    """Sequential (no look-ahead) SMC detection: swings, BOS/CHoCH, order blocks, FVGs and retest signals."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(c)
    signals = np.zeros(n)
    trend = 0
    sh = sl = None  # (idx, price)
    sh_broken = sl_broken = True
    obs, fvgs, structure = [], [], []
    for i in range(n):
        j = i - k
        if j >= k:
            if h[j] == h[j - k:j + k + 1].max():
                sh, sh_broken = (j, h[j]), False
            if l[j] == l[j - k:j + k + 1].min():
                sl, sl_broken = (j, l[j]), False
        if i >= 2:
            if l[i] > h[i - 2]:
                fvgs.append({"dir": "bull", "top": float(l[i]), "bottom": float(h[i - 2]), "idx": i - 1, "filled": False})
            elif h[i] < l[i - 2]:
                fvgs.append({"dir": "bear", "top": float(l[i - 2]), "bottom": float(h[i]), "idx": i - 1, "filled": False})
        if sh and not sh_broken and c[i] > sh[1]:
            structure.append({"type": "BOS" if trend == 1 else "CHoCH", "dir": "bull", "price": float(sh[1]), "idx": sh[0], "break_idx": i})
            trend, sh_broken = 1, True
            for m in range(i - 1, max(sh[0] - 10, 0) - 1, -1):
                if c[m] < o[m]:
                    obs.append({"dir": "bull", "top": float(h[m]), "bottom": float(l[m]), "idx": m, "created": i, "active": True})
                    break
        if sl and not sl_broken and c[i] < sl[1]:
            structure.append({"type": "BOS" if trend == -1 else "CHoCH", "dir": "bear", "price": float(sl[1]), "idx": sl[0], "break_idx": i})
            trend, sl_broken = -1, True
            for m in range(i - 1, max(sl[0] - 10, 0) - 1, -1):
                if c[m] > o[m]:
                    obs.append({"dir": "bear", "top": float(h[m]), "bottom": float(l[m]), "idx": m, "created": i, "active": True})
                    break
        for ob in obs:
            if not ob["active"] or i <= ob["created"]:
                continue
            if ob["dir"] == "bull":
                if c[i] < ob["bottom"]:
                    ob["active"] = False
                elif l[i] <= ob["top"] and trend == 1 and signals[i] == 0:
                    signals[i] = 1
                    ob["active"] = False
            else:
                if c[i] > ob["top"]:
                    ob["active"] = False
                elif h[i] >= ob["bottom"] and trend == -1 and signals[i] == 0:
                    signals[i] = -1
                    ob["active"] = False
        for f in fvgs:
            if f["filled"] or i <= f["idx"] + 1:
                continue
            if (f["dir"] == "bull" and l[i] <= f["bottom"]) or (f["dir"] == "bear" and h[i] >= f["top"]):
                f["filled"] = True
    active_obs = [ob for ob in obs if ob["active"]][-6:]
    open_fvgs = [f for f in fvgs if not f["filled"]][-6:]
    return {"_n": n, "signals": signals, "trend": trend, "order_blocks": active_obs,
            "fvgs": open_fvgs, "structure": structure[-8:]}


def _cross(a: pd.Series, b: pd.Series) -> np.ndarray:
    up = (a > b) & (a.shift() <= b.shift())
    dn = (a < b) & (a.shift() >= b.shift())
    return np.where(up, 1, np.where(dn, -1, 0)).astype(float)


def compute_signals(name: str, df: pd.DataFrame, cfg: dict) -> np.ndarray:
    c = df["close"]
    if name == "smc":
        return smc_analyze(df, int(cfg.get("swing", 3)))["signals"]
    if name == "rsi":
        r = rsi(c, int(cfg["length"]))
        os_, ob_ = float(cfg["oversold"]), float(cfg["overbought"])
        up = (r > os_) & (r.shift() <= os_)
        dn = (r < ob_) & (r.shift() >= ob_)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "ema_cross":
        return _cross(ema(c, int(cfg["fast"])), ema(c, int(cfg["slow"])))
    if name == "macd":
        m = ema(c, int(cfg["fast"])) - ema(c, int(cfg["slow"]))
        return _cross(m, ema(m, int(cfg["signal"])))
    if name == "bollinger":
        n, k = int(cfg["length"]), float(cfg["mult"])
        mid = c.rolling(n).mean()
        sd = c.rolling(n).std()
        lo, hi = mid - k * sd, mid + k * sd
        up = (c > lo) & (c.shift() <= lo.shift())
        dn = (c < hi) & (c.shift() >= hi.shift())
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    raise ValueError(name)


def strategy_signals(df: pd.DataFrame, strategy: str, plugins: dict) -> np.ndarray:
    if strategy != "combo":
        return compute_signals(strategy, df, plugins[strategy])
    trend = np.where(df["close"] > ema(df["close"], 200), 1, -1)
    total = np.zeros(len(df))
    for name, cfg in plugins.items():
        if cfg.get("enabled"):
            total += compute_signals(name, df, cfg)
    sig = np.sign(total)
    return np.where(sig == trend, sig, 0)


FEES = {"crypto": 0.0004, "forex": 0.00003, "stocks": 0.0001}  # per side, realistic spread/commission


def trend_filtered(df: pd.DataFrame, sig: np.ndarray) -> np.ndarray:
    """Only keep signals aligned with the EMA200 trend (trade with the market, not against it)."""
    trend = np.where(df["close"] > ema(df["close"], 200), 1, -1)
    return np.where(sig == trend, sig, 0)


def htf_trend(df: pd.DataFrame, htf: pd.DataFrame) -> np.ndarray:
    """Higher-timeframe trend (+1/-1/0) aligned to df bars using only CLOSED HTF candles (no look-ahead).
    Bullish = HTF close above EMA50 and EMA50 above EMA200 (bearish the inverse); otherwise 0 (no trade)."""
    c = htf["close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    t = pd.Series(np.where((c > e50) & (e50 > e200), 1, np.where((c < e50) & (e50 < e200), -1, 0)), index=htf.index)
    # an HTF bar is only known once it closes -> shift by one bar, then map onto lower-TF timestamps
    t = t.shift(1)
    aligned = t.reindex(t.index.union(df.index)).ffill().reindex(df.index)
    return aligned.fillna(0).to_numpy()


def mtf_filtered(df: pd.DataFrame, sig: np.ndarray, htf: Optional[pd.DataFrame]) -> np.ndarray:
    if htf is None or htf.empty:
        return sig
    t = htf_trend(df, htf)
    return np.where(sig == t, sig, 0)


def apply_filters(df, sig, strategy, trend_filter, mtf, htf):
    if trend_filter and strategy != "combo":
        sig = trend_filtered(df, sig)
    if mtf:
        sig = mtf_filtered(df, sig, htf)
    return sig


def run_backtest(df, strategy, plugins, sl_atr=1.5, rr=2.0, risk_pct=1.0, capital=10000.0, fee=0.0005,
                 trend_filter=True, breakeven=True, mtf=False, htf=None):
    sig = strategy_signals(df, strategy, plugins)
    sig = apply_filters(df, sig, strategy, trend_filter, mtf, htf)
    return simulate(df, sig, sl_atr, rr, risk_pct, capital, fee, breakeven)


def optimize(df, plugins, fee, risk_pct=1.0, capital=10000.0, split=0.7, htf=None):
    """Walk-forward search: choose params on the first 70% (treino), validate on the unseen last 30% (teste)."""
    cut = int(len(df) * split)
    train, test = df.iloc[:cut], df.iloc[cut - 200:]  # warm-up bars for indicators
    variants = [(True, False), (False, False)]
    if htf is not None and not htf.empty:
        variants += [(True, True), (False, True)]
    results = []
    for strat in list(PLUGIN_DEFAULTS.keys()) + ["combo"]:
        raw_tr = strategy_signals(train, strat, plugins)
        raw_te = strategy_signals(test, strat, plugins)
        for tfilt, mtf in variants:
            if strat == "combo" and not tfilt:
                continue
            s_tr = apply_filters(train, raw_tr, strat, tfilt, mtf, htf)
            s_te = apply_filters(test, raw_te, strat, tfilt, mtf, htf).copy()
            s_te[:200] = 0
            if np.count_nonzero(s_tr) < 8:
                continue
            for sl in (1.0, 1.5, 2.0, 3.0):
                for rr in (1.5, 2.0, 3.0):
                    tr = simulate(train, s_tr, sl, rr, risk_pct, capital, fee, True)["metrics"]
                    if tr["total_trades"] < 8:
                        continue
                    te = simulate(test, s_te, sl, rr, risk_pct, capital, fee, True)["metrics"]
                    results.append({"strategy": strat, "trend_filter": tfilt, "mtf": mtf, "sl_atr": sl, "rr": rr, "train": tr, "test": te})
    # score: train profit factor & return, then require out-of-sample confirmation
    results.sort(key=lambda r: (r["train"]["profit_factor"] > 1, r["train"]["return_pct"] / (1 + r["train"]["max_drawdown"])), reverse=True)
    top = results[:40]
    validated = [r for r in top if r["test"]["return_pct"] > 0 and r["test"]["profit_factor"] > 1 and r["train"]["return_pct"] > 0 and r["test"]["total_trades"] >= 5]
    validated.sort(key=lambda r: r["test"]["return_pct"] + r["train"]["return_pct"], reverse=True)
    return {"best": validated[0] if validated else None, "candidates": (validated or top)[:8], "tested": len(results)}


def simulate(df, sig, sl_atr=1.5, rr=2.0, risk_pct=1.0, capital=10000.0, fee=0.0005, breakeven=True):
    a = atr(df).to_numpy()
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    times = df.index
    eq = capital
    curve = [eq]
    trades = []
    pos = None
    skipped = 0
    for i in range(20, len(c)):
        if pos:
            exit_px, reason = None, None
            if pos["dir"] == 1:
                if l[i] <= pos["sl"]:
                    exit_px, reason = min(o[i], pos["sl"]), ("BE" if pos.get("be") else "SL")
                elif h[i] >= pos["tp"]:
                    exit_px, reason = max(o[i], pos["tp"]) if o[i] > pos["tp"] else pos["tp"], "TP"
            else:
                if h[i] >= pos["sl"]:
                    exit_px, reason = max(o[i], pos["sl"]), ("BE" if pos.get("be") else "SL")
                elif l[i] <= pos["tp"]:
                    exit_px, reason = min(o[i], pos["tp"]) if o[i] < pos["tp"] else pos["tp"], "TP"
            if exit_px is None and sig[i] == -pos["dir"]:
                exit_px, reason = c[i], "Sinal"
            # move stop to break-even (+fees) once price travels 1R in favour
            if exit_px is None and breakeven and not pos.get("be"):
                one_r = pos["entry"] + pos["dir"] * pos["stop"]
                if (pos["dir"] == 1 and h[i] >= one_r) or (pos["dir"] == -1 and l[i] <= one_r):
                    pos["sl"] = pos["entry"] * (1 + pos["dir"] * fee * 2)
                    pos["be"] = True
            if exit_px is not None:
                gross = (exit_px - pos["entry"]) * pos["qty"] * pos["dir"]
                fees = (pos["entry"] + exit_px) * pos["qty"] * fee
                pnl = gross - fees
                eq += pnl
                trades.append({"dir": "BUY" if pos["dir"] == 1 else "SELL", "entry": pos["entry"], "exit": float(exit_px),
                               "pnl": float(pnl), "r": float(pnl / pos["risk"]) if pos["risk"] else 0.0,
                               "reason": reason, "opened": times[pos["i"]].isoformat(), "closed": times[i].isoformat()})
                pos = None
        # skip setups whose stop is so tight that costs would eat >12% of the risk
        if pos is None and sig[i] != 0 and a[i] > 0 and eq > 0 and sl_atr * a[i] < 8 * fee * c[i]:
            skipped += 1
        elif pos is None and sig[i] != 0 and a[i] > 0 and eq > 0:
            d = int(sig[i])
            stop = sl_atr * a[i]
            risk = eq * risk_pct / 100
            qty = risk / stop
            pos = {"dir": d, "entry": c[i], "sl": c[i] - d * stop, "tp": c[i] + d * stop * rr, "qty": qty, "risk": risk, "i": i, "stop": stop}
        mark = eq + ((c[i] - pos["entry"]) * pos["qty"] * pos["dir"] if pos else 0)
        curve.append(mark)
    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    max_dd = float(((peak - curve) / peak).max() * 100) if len(curve) else 0.0
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    step = max(1, len(curve) // 120)
    sampled = curve[::step].tolist()
    if sampled[-1] != curve[-1]:
        sampled.append(float(curve[-1]))
    bh = float((c[-1] - c[20]) / c[20] * 100)
    return {
        "metrics": {
            "net_profit": float(eq - capital), "return_pct": float((eq - capital) / capital * 100),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
            "profit_factor": float(gp / gl) if gl > 0 else (float(gp) if gp > 0 else 0.0),
            "max_drawdown": max_dd, "total_trades": len(trades),
            "avg_r": float(np.mean([t["r"] for t in trades])) if trades else 0.0,
            "buy_hold_pct": bh, "final_equity": float(eq),
            "skipped_cost": skipped,
        },
        "equity": [round(float(x), 2) for x in sampled],
        "trades": trades[-50:][::-1],
    }


# ---------------------------------------------------------------- chart tools
def vwap(df: pd.DataFrame, n: int = 50) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"].fillna(0)
    if float(v.tail(n).sum()) <= 0:
        return tp.rolling(n, min_periods=1).mean()
    return (tp * v).rolling(n, min_periods=1).sum() / v.rolling(n, min_periods=1).sum().replace(0, np.nan)


def sr_levels(df: pd.DataFrame, k: int = 5, max_levels: int = 6) -> list:
    """Support/resistance from swing pivots, clustered within 0.5 ATR, ranked by touches."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    tol = float(atr(df).iloc[-1]) * 0.5
    pts = []
    for i in range(k, len(df) - k):
        if h[i] == h[i - k:i + k + 1].max():
            pts.append(h[i])
        if l[i] == l[i - k:i + k + 1].min():
            pts.append(l[i])
    clusters: list = []
    for p in sorted(pts):
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    price = float(df["close"].iloc[-1])
    lv = [{"price": float(np.mean(c)), "touches": len(c), "type": "support" if np.mean(c) < price else "resistance"} for c in clusters]
    lv.sort(key=lambda x: -x["touches"])
    return sorted(lv[:max_levels], key=lambda x: x["price"])


def fib_levels(df: pd.DataFrame) -> dict:
    hi_i, lo_i = int(df["high"].values.argmax()), int(df["low"].values.argmin())
    hi, lo = float(df["high"].iloc[hi_i]), float(df["low"].iloc[lo_i])
    up = lo_i < hi_i  # swing up -> retracements measured from the high down
    levels = []
    for r in (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1):
        p = hi - (hi - lo) * r if up else lo + (hi - lo) * r
        levels.append({"ratio": r, "price": p})
    return {"direction": "up" if up else "down", "levels": levels}


PATTERN_LABELS = {
    "bull_engulfing": "Engolfo de alta", "bear_engulfing": "Engolfo de baixa", "hammer": "Martelo",
    "shooting_star": "Estrela cadente", "doji": "Doji", "bull_pin": "Pin bar de alta", "bear_pin": "Pin bar de baixa",
    "inside_bar": "Inside bar",
}


def detect_patterns(df: pd.DataFrame, i: int) -> list:
    o, h, l, c = (float(df[x].iloc[i]) for x in ("open", "high", "low", "close"))
    po, ph, pl, pc = (float(df[x].iloc[i - 1]) for x in ("open", "high", "low", "close"))
    rng = h - l
    if rng <= 0:
        return []
    body = abs(c - o)
    upper, lower = h - max(o, c), min(o, c) - l
    trend_up = float(df["close"].iloc[i]) > float(ema(df["close"], 50).iloc[i])
    out = []
    if pc < po and c > o and c >= po and o <= pc:
        out.append(("bull_engulfing", 1))
    if pc > po and c < o and c <= po and o >= pc:
        out.append(("bear_engulfing", -1))
    if body / rng < 0.1:
        out.append(("doji", 0))
    elif lower >= 2 * body and upper <= body * 0.6:
        out.append(("hammer" if not trend_up else "bull_pin", 1))
    elif upper >= 2 * body and lower <= body * 0.6:
        out.append(("shooting_star" if trend_up else "bear_pin", -1))
    if h < ph and l > pl:
        out.append(("inside_bar", 0))
    return [{"pattern": p, "label": PATTERN_LABELS[p], "dir": d} for p, d in out]
