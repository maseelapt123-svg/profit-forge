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
    "pullback": {"enabled": False, "ema": 21, "trend": 50},
    "supertrend": {"enabled": False, "atr_len": 10, "st_mult": 3.0},
    "stoch_rsi": {"enabled": False, "length": 14, "stoch": 14, "lvl": 20.0},
    "adx": {"enabled": False, "length": 14, "threshold": 22.0},
    "donchian": {"enabled": False, "length": 20},
    "fvg": {"enabled": False, "swing": 3},
    "sweep": {"enabled": False, "length": 20},
    "choch": {"enabled": False, "swing": 3},
    "ote": {"enabled": False, "swing": 3},
    "breaker": {"enabled": False, "swing": 3},
    "eq_liquidity": {"enabled": False, "swing": 3, "tol": 0.15},
    "sweep_choch": {"enabled": False, "length": 20, "window": 10},
    "killzone": {"enabled": False, "swing": 3},
    "ichimoku": {"enabled": False, "tenkan": 9, "kijun": 26},
    "vwap": {"enabled": False, "length": 20},
    "psar": {"enabled": False, "step": 0.02, "max_step": 0.2},
    "williams_r": {"enabled": False, "length": 14},
    "cci": {"enabled": False, "length": 20},
    "keltner": {"enabled": False, "length": 20, "mult": 2.0},
    "pin_bar": {"enabled": False, "wick": 2.0},
    "engulfing": {"enabled": False},
    "inside_bar": {"enabled": False},
}
C12_DEFAULT = {"min": 10}
CONF_DEFAULT = {"min_votes": 2, "min_score": 55.0, "horizon": 10, "memory": 3, "lookback": 300}
STRATEGIES = list(PLUGIN_DEFAULTS) + ["combo", "confluence", "confirm12", "confirm20"]

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
    "pullback": {"label": "Pullback na Tendência", "desc": "Tendência EMA50>EMA200, recuo até à EMA21 e vela de rejeição a favor",
                 "params": {"ema": "EMA do recuo", "trend": "EMA da tendência"}},
    "supertrend": {"label": "Supertrend", "desc": "Mudança de direção do Supertrend (ATR)",
                   "params": {"atr_len": "ATR", "st_mult": "Multiplicador"}},
    "stoch_rsi": {"label": "Stoch RSI", "desc": "%K cruza %D a sair da zona extrema do Stoch RSI",
                  "params": {"length": "RSI", "stoch": "Estocástico", "lvl": "Zona"}},
    "adx": {"label": "ADX + DI", "desc": "+DI cruza -DI com ADX acima do limite (tendência forte)",
            "params": {"length": "Período", "threshold": "ADX mínimo"}},
    "donchian": {"label": "Rompimento Donchian", "desc": "Fecho acima/abaixo do canal das últimas N velas",
                 "params": {"length": "Velas"}},
    "fvg": {"label": "SMC · Fair Value Gap", "desc": "Reteste de FVG aberto a favor da estrutura e rejeição", "params": {"swing": "Força do swing (velas)"}},
    "sweep": {"label": "SMC · Varrimento de Liquidez", "desc": "Pavio rompe o máximo/mínimo anterior e fecha de volta para dentro",
              "params": {"length": "Velas de referência"}},
    "choch": {"label": "SMC · CHoCH", "desc": "Mudança de caráter: quebra de estrutura contra a tendência anterior", "params": {"swing": "Força do swing (velas)"}},
    "ote": {"label": "SMC · OTE (Fibo 62–79%)", "desc": "Após BOS, recuo à zona ótima 62–79% do impulso e vela de rejeição", "params": {"swing": "Força do swing (velas)"}},
    "breaker": {"label": "SMC · Breaker Block", "desc": "Order block falhado muda de papel e é retestado do outro lado", "params": {"swing": "Força do swing (velas)"}},
    "eq_liquidity": {"label": "SMC · Raid EQH/EQL", "desc": "Topos/fundos iguais (liquidez) varridos e fecho de volta para dentro",
                     "params": {"swing": "Força do swing (velas)", "tol": "Tolerância (x ATR)"}},
    "sweep_choch": {"label": "SMC · Varrimento + CHoCH", "desc": "Captura de liquidez seguida de mudança de caráter na mesma direção",
                    "params": {"length": "Velas de referência", "window": "Janela até ao CHoCH"}},
    "killzone": {"label": "SMC · Killzones", "desc": "Reteste de OB/FVG só nas sessões de Londres (7–10h) e Nova Iorque (12–15h) UTC",
                 "params": {"swing": "Força do swing (velas)"}},
    "ichimoku": {"label": "Ichimoku", "desc": "Cruzamento Tenkan/Kijun com o preço fora da nuvem", "params": {"tenkan": "Tenkan", "kijun": "Kijun"}},
    "vwap": {"label": "VWAP", "desc": "Preço cruza a VWAP móvel", "params": {"length": "Período"}},
    "psar": {"label": "Parabolic SAR", "desc": "Inversão do Parabolic SAR", "params": {"step": "Passo", "max_step": "Passo máx."}},
    "williams_r": {"label": "Williams %R", "desc": "Saída das zonas -80 / -20", "params": {"length": "Período"}},
    "cci": {"label": "CCI", "desc": "CCI sai de ±100 (reversão)", "params": {"length": "Período"}},
    "keltner": {"label": "Canal de Keltner", "desc": "Fecho fora do canal EMA ± ATR (rompimento)", "params": {"length": "Período", "mult": "Multiplicador ATR"}},
    "pin_bar": {"label": "Vela · Pin Bar", "desc": "Pavio longo de rejeição com fecho no extremo oposto", "params": {"wick": "Pavio/corpo mín."}},
    "engulfing": {"label": "Vela · Engolfo", "desc": "Corpo engole totalmente o corpo da vela anterior", "params": {}},
    "inside_bar": {"label": "Vela · Inside Bar", "desc": "Rompimento da vela-mãe após uma inside bar", "params": {}},
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
    trend_arr, choch, fvg_sig = np.zeros(n), np.zeros(n), np.zeros(n)
    breaker, ote = np.zeros(n), np.zeros(n)
    swing_hi, swing_lo = np.full(n, np.nan), np.full(n, np.nan)  # swing price confirmed at bar i
    leg = None  # {"dir", "lo", "hi", "used"} impulse leg after the last BOS, for OTE (62–79% retracement)
    breakers = []
    trend = 0
    sh = sl = None  # (idx, price)
    sh_broken = sl_broken = True
    obs, fvgs, structure = [], [], []
    for i in range(n):
        j = i - k
        if j >= k:
            if h[j] == h[j - k:j + k + 1].max():
                sh, sh_broken = (j, h[j]), False
                swing_hi[i] = h[j]
            if l[j] == l[j - k:j + k + 1].min():
                sl, sl_broken = (j, l[j]), False
                swing_lo[i] = l[j]
        if i >= 2:
            if l[i] > h[i - 2]:
                fvgs.append({"dir": "bull", "top": float(l[i]), "bottom": float(h[i - 2]), "idx": i - 1, "filled": False})
            elif h[i] < l[i - 2]:
                fvgs.append({"dir": "bear", "top": float(l[i - 2]), "bottom": float(h[i]), "idx": i - 1, "filled": False})
        if sh and not sh_broken and c[i] > sh[1]:
            structure.append({"type": "BOS" if trend == 1 else "CHoCH", "dir": "bull", "price": float(sh[1]), "idx": sh[0], "break_idx": i})
            if trend == -1:
                choch[i] = 1
            trend, sh_broken = 1, True
            leg = {"dir": 1, "lo": float(sl[1]) if sl else float(l[max(0, i - 20):i + 1].min()), "hi": float(h[i]), "used": False}
            for m in range(i - 1, max(sh[0] - 10, 0) - 1, -1):
                if c[m] < o[m]:
                    obs.append({"dir": "bull", "top": float(h[m]), "bottom": float(l[m]), "idx": m, "created": i, "active": True})
                    break
        if sl and not sl_broken and c[i] < sl[1]:
            structure.append({"type": "BOS" if trend == -1 else "CHoCH", "dir": "bear", "price": float(sl[1]), "idx": sl[0], "break_idx": i})
            if trend == 1:
                choch[i] = -1
            trend, sl_broken = -1, True
            leg = {"dir": -1, "hi": float(sh[1]) if sh else float(h[max(0, i - 20):i + 1].max()), "lo": float(l[i]), "used": False}
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
                    breakers.append({"dir": "bear", "top": ob["top"], "bottom": ob["bottom"], "created": i})
                elif l[i] <= ob["top"] and trend == 1 and signals[i] == 0:
                    signals[i] = 1
                    ob["active"] = False
            else:
                if c[i] > ob["top"]:
                    ob["active"] = False
                    breakers.append({"dir": "bull", "top": ob["top"], "bottom": ob["bottom"], "created": i})
                elif h[i] >= ob["bottom"] and trend == -1 and signals[i] == 0:
                    signals[i] = -1
                    ob["active"] = False
        for f in fvgs:
            if f["filled"] or i <= f["idx"] + 1:
                continue
            if (f["dir"] == "bull" and l[i] <= f["bottom"]) or (f["dir"] == "bear" and h[i] >= f["top"]):
                f["filled"] = True
            elif not f.get("used") and f["dir"] == "bull" and trend == 1 and l[i] <= f["top"] and c[i] > f["top"]:
                fvg_sig[i], f["used"] = 1, True
            elif not f.get("used") and f["dir"] == "bear" and trend == -1 and h[i] >= f["bottom"] and c[i] < f["bottom"]:
                fvg_sig[i], f["used"] = -1, True
        for b in breakers:  # failed OB flips role: retest from the other side
            if b.get("done") or i <= b["created"]:
                continue
            if b["dir"] == "bull" and trend == 1 and l[i] <= b["top"] and c[i] > b["top"]:
                breaker[i], b["done"] = 1, True
            elif b["dir"] == "bear" and trend == -1 and h[i] >= b["bottom"] and c[i] < b["bottom"]:
                breaker[i], b["done"] = -1, True
            elif (b["dir"] == "bull" and c[i] < b["bottom"]) or (b["dir"] == "bear" and c[i] > b["top"]):
                b["done"] = True
        if leg and not leg["used"]:
            if leg["dir"] == 1:
                if trend != 1 or c[i] < leg["lo"]:
                    leg["used"] = True
                else:
                    leg["hi"] = max(leg["hi"], float(h[i]))
                    rng = leg["hi"] - leg["lo"]
                    z_top, z_bot = leg["hi"] - 0.62 * rng, leg["hi"] - 0.79 * rng
                    if rng > 0 and l[i] <= z_top and c[i] > z_bot and c[i] > o[i]:
                        ote[i], leg["used"] = 1, True
            else:
                if trend != -1 or c[i] > leg["hi"]:
                    leg["used"] = True
                else:
                    leg["lo"] = min(leg["lo"], float(l[i]))
                    rng = leg["hi"] - leg["lo"]
                    z_bot, z_top = leg["lo"] + 0.62 * rng, leg["lo"] + 0.79 * rng
                    if rng > 0 and h[i] >= z_bot and c[i] < z_top and c[i] < o[i]:
                        ote[i], leg["used"] = -1, True
        trend_arr[i] = trend
    active_obs = [ob for ob in obs if ob["active"]][-6:]
    open_fvgs = [f for f in fvgs if not f["filled"]][-6:]
    return {"_n": n, "signals": signals, "trend": trend, "trend_arr": trend_arr, "choch": choch, "fvg_sig": fvg_sig, "breaker": breaker, "ote": ote,
            "swing_hi": swing_hi, "swing_lo": swing_lo, "order_blocks": active_obs,
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
    if name == "pullback":
        e, t, e200 = ema(c, int(cfg["ema"])), ema(c, int(cfg["trend"])), ema(c, 200)
        o, h, l = df["open"], df["high"], df["low"]
        up = (t > e200) & (c > t) & (l <= e) & (c > e) & (c > o)
        dn = (t < e200) & (c < t) & (h >= e) & (c < e) & (c < o)
        raw = np.where(up, 1, np.where(dn, -1, 0))
        prev = np.concatenate([[0], raw[:-1]])
        return np.where(raw != prev, raw, 0).astype(float)
    if name == "supertrend":
        return _flips(supertrend_dir(df, int(cfg["atr_len"]), float(cfg["st_mult"])))
    if name == "stoch_rsi":
        r = rsi(c, int(cfg["length"]))
        n = int(cfg["stoch"])
        lo, hi = r.rolling(n).min(), r.rolling(n).max()
        k = ((r - lo) / (hi - lo).replace(0, np.nan) * 100).fillna(50).rolling(3).mean()
        dd = k.rolling(3).mean()
        lvl = float(cfg["lvl"])
        up = (k > dd) & (k.shift() <= dd.shift()) & (dd < lvl)
        dn = (k < dd) & (k.shift() >= dd.shift()) & (dd > 100 - lvl)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "adx":
        pdi, ndi, adx_ = adx_di(df, int(cfg["length"]))
        strong = (adx_ > float(cfg["threshold"])).to_numpy()
        return np.where(strong, _cross(pdi, ndi), 0).astype(float)
    if name == "donchian":
        n = int(cfg["length"])
        hh, ll = df["high"].rolling(n).max().shift(), df["low"].rolling(n).min().shift()
        up = (c > hh) & (c.shift() <= hh.shift())
        dn = (c < ll) & (c.shift() >= ll.shift())
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "fvg":
        return smc_analyze(df, int(cfg.get("swing", 3)))["fvg_sig"]
    if name == "choch":
        return smc_analyze(df, int(cfg.get("swing", 3)))["choch"]
    if name in ("ote", "breaker"):
        return smc_analyze(df, int(cfg.get("swing", 3)))[name]
    if name == "killzone":
        a = smc_analyze(df, int(cfg.get("swing", 3)))
        sig = np.where(a["signals"] != 0, a["signals"], a["fvg_sig"])
        idx = pd.DatetimeIndex(df.index)
        hrs = (idx.tz_convert("UTC") if idx.tz is not None else idx).hour
        kz = np.isin(hrs, [7, 8, 9, 12, 13, 14])
        return np.where(kz, sig, 0).astype(float)
    if name == "eq_liquidity":
        a = smc_analyze(df, int(cfg.get("swing", 3)))
        tol = (atr(df) * float(cfg["tol"])).to_numpy()
        h, l, o, cc = (df[x].to_numpy(float) for x in ("high", "low", "open", "close"))
        out = np.zeros(len(cc))
        his, los = [], []
        for i in range(len(cc)):
            if not np.isnan(a["swing_hi"][i]):
                his = (his + [a["swing_hi"][i]])[-2:]
            if not np.isnan(a["swing_lo"][i]):
                los = (los + [a["swing_lo"][i]])[-2:]
            if len(his) == 2 and abs(his[0] - his[1]) <= tol[i]:
                lvl = max(his)
                if h[i] > lvl and cc[i] < lvl and cc[i] < o[i]:
                    out[i], his = -1, []
            if len(los) == 2 and abs(los[0] - los[1]) <= tol[i]:
                lvl = min(los)
                if l[i] < lvl and cc[i] > lvl and cc[i] > o[i]:
                    out[i], los = 1, []
        return out
    if name == "sweep_choch":
        sw = compute_signals("sweep", df, {"length": cfg["length"]})
        ch = smc_analyze(df)["choch"]
        w = int(cfg["window"])
        recent = pd.Series(sw).replace(0, np.nan).ffill(limit=w).fillna(0).to_numpy()
        return np.where((ch != 0) & (ch == recent), ch, 0).astype(float)
    if name == "sweep":
        n = int(cfg["length"])
        o, h, l = df["open"], df["high"], df["low"]
        ph, pl = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        up = (l < pl) & (c > pl) & (c > o)
        dn = (h > ph) & (c < ph) & (c < o)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "ichimoku":
        tk, kj, sa, sb = ichimoku_lines(df, int(cfg["tenkan"]), int(cfg["kijun"]))
        x = _cross(tk, kj)
        above, below = c > np.maximum(sa, sb), c < np.minimum(sa, sb)
        return np.where((x > 0) & above, 1, np.where((x < 0) & below, -1, 0)).astype(float)
    if name == "vwap":
        return _cross(c, rolling_vwap(df, int(cfg["length"])))
    if name == "psar":
        return _flips(psar_dir(df, float(cfg["step"]), float(cfg["max_step"])))
    if name == "williams_r":
        n = int(cfg["length"])
        hh, ll = df["high"].rolling(n).max(), df["low"].rolling(n).min()
        wr = ((hh - c) / (hh - ll).replace(0, np.nan) * -100).fillna(-50)
        up = (wr > -80) & (wr.shift() <= -80)
        dn = (wr < -20) & (wr.shift() >= -20)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "cci":
        n = int(cfg["length"])
        tp = (df["high"] + df["low"] + c) / 3
        ma = tp.rolling(n).mean()
        md = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci_ = ((tp - ma) / (0.015 * md.replace(0, np.nan))).fillna(0)
        up = (cci_ > -100) & (cci_.shift() <= -100)
        dn = (cci_ < 100) & (cci_.shift() >= 100)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "keltner":
        mid = ema(c, int(cfg["length"]))
        a = atr(df, 10) * float(cfg["mult"])
        return np.where(_cross(c, mid + a) > 0, 1, np.where(_cross(c, mid - a) < 0, -1, 0)).astype(float)
    if name == "pin_bar":
        o, h, l = df["open"], df["high"], df["low"]
        body = (c - o).abs().replace(0, 1e-12)
        rng = (h - l).replace(0, np.nan)
        lw, uw = np.minimum(o, c) - l, h - np.maximum(o, c)
        k = float(cfg["wick"])
        up = (lw >= k * body) & (lw >= 0.6 * rng) & ((c - l) / rng >= 0.66)
        dn = (uw >= k * body) & (uw >= 0.6 * rng) & ((h - c) / rng >= 0.66)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "engulfing":
        o = df["open"]
        po, pc = o.shift(), c.shift()
        up = (c > o) & (pc < po) & (c >= po) & (o <= pc)
        dn = (c < o) & (pc > po) & (c <= po) & (o >= pc)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    if name == "inside_bar":
        h, l = df["high"], df["low"]
        mh, ml = h.shift(2), l.shift(2)
        inside = (h.shift() < mh) & (l.shift() > ml)
        up = inside & (c > mh)
        dn = inside & (c < ml)
        return np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    raise ValueError(name)


def _flips(d: np.ndarray) -> np.ndarray:
    out = np.zeros(len(d))
    out[1:] = np.where(d[1:] != d[:-1], d[1:], 0)
    return out


def supertrend_dir(df: pd.DataFrame, n: int = 10, m: float = 3.0) -> np.ndarray:
    a = atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    cc = df["close"].to_numpy(float)
    ub, lb = hl2 + m * a, hl2 - m * a
    d = np.ones(len(cc))
    fu, fl = ub.copy(), lb.copy()
    for i in range(1, len(cc)):
        fu[i] = ub[i] if ub[i] < fu[i - 1] or cc[i - 1] > fu[i - 1] else fu[i - 1]
        fl[i] = lb[i] if lb[i] > fl[i - 1] or cc[i - 1] < fl[i - 1] else fl[i - 1]
        d[i] = 1 if cc[i] > fu[i - 1] else -1 if cc[i] < fl[i - 1] else d[i - 1]
    return d


def adx_di(df: pd.DataFrame, n: int = 14):
    h, l = df["high"], df["low"]
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=df.index)
    ndm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=df.index)
    tr = atr(df, n).replace(0, np.nan)
    pdi = (pdm.ewm(alpha=1 / n, adjust=False).mean() / tr * 100).fillna(0)
    ndi = (ndm.ewm(alpha=1 / n, adjust=False).mean() / tr * 100).fillna(0)
    dx = ((pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan) * 100).fillna(0)
    return pdi, ndi, dx.ewm(alpha=1 / n, adjust=False).mean()


def ichimoku_lines(df: pd.DataFrame, t: int = 9, k: int = 26):
    h, l = df["high"], df["low"]
    tk = (h.rolling(t).max() + l.rolling(t).min()) / 2
    kj = (h.rolling(k).max() + l.rolling(k).min()) / 2
    sa = ((tk + kj) / 2).shift(k)
    sb = ((h.rolling(2 * k).max() + l.rolling(2 * k).min()) / 2).shift(k)
    return tk, kj, sa, sb


def rolling_vwap(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"].fillna(0) if "volume" in df else pd.Series(0.0, index=df.index)
    vs = v.rolling(n).sum()
    vw = (tp * v).rolling(n).sum() / vs.replace(0, np.nan)
    return vw.fillna(tp.rolling(n).mean())  # forex has no volume → typical-price mean


def psar_dir(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> np.ndarray:
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    n = len(h)
    d = np.ones(n)
    if n < 2:
        return d
    up, sar, ep, af = True, l[0], h[0], step
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, max_step)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, max_step)
        d[i] = 1 if up else -1
    return d


C12_LABELS = [
    "Preço vs EMA200", "EMA21 vs EMA50", "Inclinação da EMA50", "Histograma MACD", "RSI na zona de momentum",
    "ADX > 20 com DI a favor", "Supertrend", "Preço vs nuvem Ichimoku", "Parabolic SAR", "Estrutura SMC (BOS/CHoCH)",
    "Preço vs VWAP", "Vela de força (fecho no extremo)",
]


def confirm12_matrix(df: pd.DataFrame) -> np.ndarray:
    """12 independent directional checks per bar: +1 bullish, -1 bearish, 0 neutral. Shape (n, 12)."""
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    sgn = lambda x: np.sign(np.nan_to_num(np.asarray(x, float)))  # noqa: E731
    e21, e50, e200 = ema(c, 21), ema(c, 50), ema(c, 200)
    m = ema(c, 12) - ema(c, 26)
    hist = m - ema(m, 9)
    r = rsi(c, 14)
    pdi, ndi, adx_ = adx_di(df, 14)
    _, _, sa, sb = ichimoku_lines(df)
    top, bot = np.maximum(sa, sb), np.minimum(sa, sb)
    rng = (h - l).replace(0, np.nan)
    pos = ((c - l) / rng).fillna(0.5)
    cols = [
        sgn(c - e200), sgn(e21 - e50), sgn(e50 - e50.shift(5)), sgn(hist),
        np.where((r > 50) & (r < 70), 1, np.where((r < 50) & (r > 30), -1, 0)),
        np.where(adx_ > 20, sgn(pdi - ndi), 0),
        supertrend_dir(df), np.where(c > top, 1, np.where(c < bot, -1, 0)),
        psar_dir(df), smc_analyze(df)["trend_arr"], sgn(c - rolling_vwap(df)),
        np.where((c > o) & (pos >= 0.7), 1, np.where((c < o) & (pos <= 0.3), -1, 0)),
    ]
    return np.column_stack([np.asarray(x, float) for x in cols])


C20_LABELS = C12_LABELS + [
    "EMA9 vs EMA21", "Preço vs média Bollinger (SMA20)", "Momentum ROC(10)", "CCI(20) acima/abaixo de 0",
    "Williams %R acima/abaixo de -50", "Stoch RSI %K vs %D", "Posição no canal Donchian(20)", "Vela Heikin-Ashi",
]


def confirm20_matrix(df: pd.DataFrame) -> np.ndarray:
    """The 12 confirmations plus 8 extra momentum/structure tools. Shape (n, 20)."""
    c = df["close"]
    sgn = lambda x: np.sign(np.nan_to_num(np.asarray(x, float)))  # noqa: E731
    tp = (df["high"] + df["low"] + c) / 3
    ma = tp.rolling(20).mean()
    md = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci_ = (tp - ma) / (0.015 * md.replace(0, np.nan))
    hh14, ll14 = df["high"].rolling(14).max(), df["low"].rolling(14).min()
    wr = (hh14 - c) / (hh14 - ll14).replace(0, np.nan) * -100
    r = rsi(c, 14)
    lo, hi = r.rolling(14).min(), r.rolling(14).max()
    k = ((r - lo) / (hi - lo).replace(0, np.nan) * 100).fillna(50).rolling(3).mean()
    dch, dcl = df["high"].rolling(20).max(), df["low"].rolling(20).min()
    ha_c = (df["open"] + df["high"] + df["low"] + c) / 4
    ha_o = ha_c.copy()
    hv, cv = ha_o.to_numpy(dtype=float, copy=True), ha_c.to_numpy(dtype=float, copy=True)
    ov = df["open"].to_numpy(float)
    hv[0] = (ov[0] + cv[0]) / 2
    for i in range(1, len(hv)):
        hv[i] = (hv[i - 1] + cv[i - 1]) / 2
    extra = [
        sgn(ema(c, 9) - ema(c, 21)), sgn(c - c.rolling(20).mean()), sgn(c - c.shift(10)), sgn(cci_),
        sgn(wr + 50), sgn(k - k.rolling(3).mean()), sgn(c - (dch + dcl) / 2), sgn(cv - hv),
    ]
    return np.column_stack([confirm12_matrix(df)] + [np.asarray(x, float) for x in extra])


def confirm_signals(mat: np.ndarray, min_conf: int) -> np.ndarray:
    up, dn = (mat > 0).sum(axis=1), (mat < 0).sum(axis=1)
    raw = np.where(up >= min_conf, 1, np.where(dn >= min_conf, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    return np.where(raw != prev, raw, 0).astype(float)


def confirm12_signals(df: pd.DataFrame, min_conf: int = 10) -> np.ndarray:
    mat = confirm12_matrix(df)
    up, dn = (mat > 0).sum(axis=1), (mat < 0).sum(axis=1)
    raw = np.where(up >= min_conf, 1, np.where(dn >= min_conf, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    return np.where(raw != prev, raw, 0).astype(float)


def _persist(sig: np.ndarray, memory: int) -> np.ndarray:
    """A plugin keeps its vote for `memory` bars after firing (signals rarely fire on the very same bar)."""
    return pd.Series(sig).replace(0, np.nan).ffill(limit=max(0, memory - 1)).fillna(0).to_numpy()


def plugin_weight(df: pd.DataFrame, sig: np.ndarray, horizon: int, lookback: int) -> np.ndarray:
    """Rolling win rate (0..1) of a plugin's past signals, using only outcomes already known at each bar.
    Win = price moved in the signal direction `horizon` bars later. 0.5 until 5 signals are known."""
    c = df["close"].to_numpy(float)
    out = np.zeros(len(c))
    out[:-horizon] = np.sign(c[horizon:] - c[:-horizon])
    res = sig * out
    win = pd.Series((res > 0).astype(float)).shift(horizon).fillna(0).rolling(lookback, min_periods=1).sum()
    cnt = pd.Series((sig != 0).astype(float)).shift(horizon).fillna(0).rolling(lookback, min_periods=1).sum()
    return np.where(cnt >= 5, (win / cnt.replace(0, np.nan)).fillna(0.5), 0.5)


def confluence_detail(df: pd.DataFrame, plugins: dict, conf: Optional[dict] = None) -> dict:
    conf = {**CONF_DEFAULT, **(conf or {})}
    names = [k for k, v in plugins.items() if k in PLUGIN_DEFAULTS and v.get("enabled")]
    n = len(df)
    up_n, dn_n, up_w, dn_w = (np.zeros(n) for _ in range(4))
    per = {}
    for name in names:
        s = compute_signals(name, df, plugins[name])
        v = _persist(s, int(conf["memory"]))
        w = plugin_weight(df, s, int(conf["horizon"]), int(conf["lookback"]))
        up_n += v > 0
        dn_n += v < 0
        up_w += (v > 0) * w
        dn_w += (v < 0) * w
        per[name] = {"vote": int(v[-2]) if n > 1 else 0, "weight": float(w[-1] * 100)}
    trend = np.where(df["close"] > ema(df["close"], 200), 1, -1)
    s_up, s_dn = up_w / np.maximum(up_n, 1) * 100, dn_w / np.maximum(dn_n, 1) * 100
    mv, ms = int(conf["min_votes"]), float(conf["min_score"])
    cond_up = (up_n >= mv) & (dn_n == 0) & (s_up >= ms) & (trend == 1)
    cond_dn = (dn_n >= mv) & (up_n == 0) & (s_dn >= ms) & (trend == -1)
    raw = np.where(cond_up, 1, np.where(cond_dn, -1, 0))
    prev = np.concatenate([[0], raw[:-1]])
    sig = np.where(raw != prev, raw, 0).astype(float)
    return {"signals": sig, "plugins": per, "score_up": float(s_up[-2]) if n > 1 else 0.0,
            "score_dn": float(s_dn[-2]) if n > 1 else 0.0, "votes_up": int(up_n[-2]) if n > 1 else 0,
            "votes_dn": int(dn_n[-2]) if n > 1 else 0, "trend": int(trend[-1]), "conf": conf}


def strategy_signals(df: pd.DataFrame, strategy: str, plugins: dict) -> np.ndarray:
    if strategy == "confluence":
        return confluence_detail(df, plugins, plugins.get("_conf"))["signals"]
    if strategy == "confirm12":
        return confirm12_signals(df, int((plugins.get("_c12") or C12_DEFAULT)["min"]))
    if strategy == "confirm20":
        return confirm_signals(confirm20_matrix(df), int((plugins.get("_c20") or {"min": 16})["min"]))
    if strategy != "combo":
        return compute_signals(strategy, df, plugins[strategy])
    trend = np.where(df["close"] > ema(df["close"], 200), 1, -1)
    total = np.zeros(len(df))
    for name, cfg in plugins.items():
        if name in PLUGIN_DEFAULTS and cfg.get("enabled"):
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
    if trend_filter and strategy not in ("combo", "confluence", "confirm12", "confirm20"):
        sig = trend_filtered(df, sig)
    if mtf:
        sig = mtf_filtered(df, sig, htf)
    return sig


def run_backtest(df, strategy, plugins, sl_atr=1.5, rr=2.0, risk_pct=1.0, capital=10000.0, fee=0.0005,
                 trend_filter=True, breakeven=True, mtf=False, htf=None, partial_pct=0.0, partial_r=1.0, all_trades=False):
    sig = strategy_signals(df, strategy, plugins)
    sig = apply_filters(df, sig, strategy, trend_filter, mtf, htf)
    return simulate(df, sig, sl_atr, rr, risk_pct, capital, fee, breakeven, partial_pct, partial_r, all_trades)


def optimize(df, plugins, fee, risk_pct=1.0, capital=10000.0, split=0.7, htf=None):
    """Walk-forward search: choose params on the first 70% (treino), validate on the unseen last 30% (teste)."""
    cut = int(len(df) * split)
    train, test = df.iloc[:cut], df.iloc[cut - 200:]  # warm-up bars for indicators
    variants = [(True, False), (False, False)]
    if htf is not None and not htf.empty:
        variants += [(True, True), (False, True)]
    results = []
    for strat in STRATEGIES:
        raw_tr = strategy_signals(train, strat, plugins)
        raw_te = strategy_signals(test, strat, plugins)
        for tfilt, mtf in variants:
            if strat in ("combo", "confluence", "confirm12", "confirm20") and not tfilt:
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


def simulate(df, sig, sl_atr=1.5, rr=2.0, risk_pct=1.0, capital=10000.0, fee=0.0005, breakeven=True,
             partial_pct=0.0, partial_r=1.0, all_trades=False):
    """partial_pct > 0: close that % of the position at +partial_r R and move the stop to break-even.
    all_trades: return every trade (simulations) instead of only the latest 50 (UI lists)."""
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
            if exit_px is None and partial_pct > 0 and not pos.get("ptp"):
                lvl = pos["entry"] + pos["dir"] * pos["stop"] * partial_r
                if (pos["dir"] == 1 and h[i] >= lvl) or (pos["dir"] == -1 and l[i] <= lvl):
                    q = pos["qty"] * partial_pct / 100
                    part = (lvl - pos["entry"]) * q * pos["dir"] - (pos["entry"] + lvl) * q * fee
                    eq += part
                    pos["realized"] += part
                    pos["qty"] -= q
                    pos["ptp"] = True
                    pos["sl"] = pos["entry"] * (1 + pos["dir"] * fee * 2)
                    pos["be"] = True
            # move stop to break-even (+fees) once price travels 1R in favour
            if exit_px is None and breakeven and not pos.get("be"):
                one_r = pos["entry"] + pos["dir"] * pos["stop"]
                if (pos["dir"] == 1 and h[i] >= one_r) or (pos["dir"] == -1 and l[i] <= one_r):
                    pos["sl"] = pos["entry"] * (1 + pos["dir"] * fee * 2)
                    pos["be"] = True
            if exit_px is not None:
                gross = (exit_px - pos["entry"]) * pos["qty"] * pos["dir"]
                fees = (pos["entry"] + exit_px) * pos["qty"] * fee
                eq += gross - fees
                pnl = gross - fees + pos["realized"]
                if reason == "BE" and pos.get("ptp"):
                    reason = "Parcial+BE"
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
            pos = {"dir": d, "entry": c[i], "sl": c[i] - d * stop, "tp": c[i] + d * stop * rr, "qty": qty, "risk": risk, "i": i, "stop": stop, "realized": 0.0}
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
        "trades": (trades if all_trades else trades[-50:])[::-1],
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
