# SmartTrade AI — PRD

## Original problem statement (PT)
"Consegues criar uma APP para trading. Que use estratégias lucrativas como Smartmoney e backtest, plugins integrados e mais coisas tudo para ser o mais lucrativo possível."
Follow-ups: "Faz trades automaticamente", "Está com resultados negativos", "Baixa também timeframe".

## User choices
- Markets: crypto + forex + stocks (yfinance, free, no key)
- Execution: paper trading now, real broker later
- Features: Smart Money signals, backtest, strategy plugins, AI analysis (GPT-5.4 via Emergent LLM key)
- Login: Emergent Google Sign-In

## Architecture
- Backend FastAPI (`server.py`, `strategies.py`), MongoDB (users, user_sessions, plugins, positions, accounts, bots, bot_logs, backtests, analyses)
- Frontend Expo Router, dark trading theme (Rajdhani + IBM Plex Sans), 4 tabs (Mercados, Sinais, Backtest, Portfólio) + chart, plugins, bot screens

## Implemented (2026-06)
- Google auth (Emergent), protected routes
- Live quotes + sparkline; candlestick chart with OB / FVG / BOS-CHoCH overlays; TFs 1m, 5m, 15m, 1H, 4H, 1D
- Plugins: SMC, RSI, EMA Cross, MACD, Bollinger (toggle + validated params)
- Signals feed (plugin consensus + EMA200 trend filter, entry/SL/TP by ATR)
- Backtest: realistic fees per asset class, EMA200 trend filter, break-even at 1R, skip trades whose stop is too tight for costs, equity curve + metrics vs Buy&Hold
- Optimizer: ~130 combos, 70% train / 30% unseen test, only recommends setups positive on both; "Aplicar" and "Usar no Robô" (per-asset override)
- AI analysis streaming (SMC plan, pt-PT)
- Paper trading: orders with SL/TP, 10x margin cap, close, reset (2-tap confirm), auto SL/TP monitor
- Bot (paper): 60s loop, closed-bar signals, multi-timeframe setups per asset (same asset on several TFs, each optimized), higher-TF trend confirmation (1m→15m, 5m→1H, 15m→4H, 1H→4H, 4H→1D), break-even, max positions, lock, activity log
- Multi-timeframe optimizer (background job, 6 TFs) → "Usar no Robô" adds all validated TF setups
- Signals show higher-TF trend and only fire when it agrees

## Backlog
- P1: Real broker connection (e.g. Binance / OANDA / Alpaca keys) — user wants later
- P1: Bot performance report per asset / equity curve over time
- P2: Price alerts, multi-timeframe confirmation, trailing stop options

## Iteration (2026-06) — Tools, HFX, loss analysis
- Tabs: Mercados, HFX, Backtest, Portfólio. Signals moved to /signals; Tools hub /tools
- Tools: chart EMA20/50, VWAP, S/R, Fibonacci, RSI panel; candle pattern scanner (/patterns); position calculator (/calculator)
- HFX tab: up/down 1 & 3 min (payout OTC 85%, real 82%) on paper account; sources: simulated OTC 24/7 feed (mean-reverting random walk anchored to real price) and real forex 1m (yfinance); live countdown, results, stats
- HFX plugins (7): BB+RSI, RSI(2), Estocástico, Momentum EMA, Engolfo, Pin bar, Sequência + Confluência; /hfx-plugins
- HFX "Estratégia Vencedora" optimizer: single/2-plugin combos/confluence on ~7k real 1m candles, 70/30 walk-forward, Wilson lower bound, strength forte/moderada; send setups to HFX bot
- HFX bot: auto | confluência | otimizada, daily stop/target, max/hour, only fresh closed candle
- Loss analysis (/analysis) for HFX bot (24h) and main bot (14d): diagnoses losing patterns (pair/strategy, hour, against trend, volatility, setup PF<1, against higher TF, too many stops) and auto-fixes the bots every 10 min (toggle)

## Backlog
- P1: Real broker connection (Binance/OANDA/Alpaca) — user wants later
- P1: Price alerts, currency strength
- P2: split hfx.py/server.py into modules

## Iteration 6 (fork 2)
- Fixed: saving HFX bot config no longer re-enables auto-fix (verified).
- AI Coach (Análise de Perdas): POST /api/ai/loss-review {scope hfx|bot} streams GPT-5.4 explanation of losses + exact corrections; last review saved (GET).
- AI Filter on both bots (ai_filter flag): gpt-5.4-mini approves/rejects each entry (fails closed, 8s timeout on HFX, stale-candle recheck). Logged as kind "ai".
- Backlog: real broker integration; AI filter approval-rate stat; split server.py.
- Daily AI Summary (/daily): on-demand (Gerar) per UTC day, GET /api/ai/daily-stats?date, POST /api/ai/daily-summary (SSE), GET /api/ai/daily-summaries (history). Entry points: Home header icon, Ferramentas, both bot screens.
- Bug fix: /daily was not registered in Stack.Protected → app landed on it when logged out/at start. Registered.
- New main-bot plugins: pullback, supertrend, stoch_rsi, adx, donchian. Weighted confluence strategy "confluence" (conf_votes, conf_score; weights = rolling hit rate per plugin), GET /api/confluence panel in /bot.
- Daily summary now also produces structured adjustments (validated by ADJ_SPEC) shown before→after; POST /api/ai/daily-summary/apply {date, ids}.
- PENDING: testing_agent run for these (only curl-verified).
- AI filter stats: rejections in db.ai_decisions, approved trades/positions tagged with ai{confidence,reason}; GET /api/ai/filter-stats?scope&days; screen /ai-stats (links from both bot screens).
- 13 new plugins (SMC: fvg, sweep, choch; classic: ichimoku, vwap, psar, williams_r, cci, keltner; candles: pin_bar, engulfing, inside_bar). Strategy "confirm12" (12 checks, min adjustable 6-12).
- Main bot: separate "12 Confirmações" entry stream (c12_enabled, c12_min=10, c12_max_positions=2; positions c12=True, setup "c12|sym|tf"); GET /api/confirm12 checklist.
- One-click "Otimizar tudo" for main bot: POST /api/bot/optimize-all + GET /api/bot/optimize-all/{id}; applies validated best setup per asset.
- Added 2m/3m timeframes (3m resampled from 1m); optimizer now covers 1m,2m,3m,5m,15m,1h,4h,1d.
- Backtest optimizer: per-TF checkboxes; 'Usar no Robô (N)' sends only selected TFs (replaces same symbol+tf setups, keeps others).
- Loss RCA (user sertgio): 18 closed bot trades, 1 win. Causes: (1) exits filled at polled price beyond SL (slippage) → fixed: SL/TP fill at order level; (2) 12C stream on 5m opened baskets of correlated trades (11 losses) → c12 now has own TF (c12_tf default 1h), requires HTF trend alignment, respects blocked hours, max 2 new per cycle; (3) 1m–3m setups noisy.
- 5 more SMC plugins: ote, breaker, eq_liquidity, sweep_choch, killzone.
- Otimizar tudo: now returns all validated (asset,tf) setups; user picks via checkboxes; POST /api/bot/optimize-all/{id}/apply {keys:['SYM|tf']} merges (max 40).
- Only setups with test return > 6% can go to bot (optimize-all filter+apply check; backtest per-TF picker).
- Otimizar tudo: clears old setups at start, adds each >6% setup live; untick removes (apply replace=true).
- Partial take profit: bot ptp_enabled(default true)/ptp_pct(50)/ptp_r(1R) → closes part at +R, banks pnl (realized), SL→BE; close_position adds realized. Backtest partial_pct/partial_r ("Parcial a 1R" stepper).
- "Sniper 20" independent stream (c20_*): 20-tool confluence (12C + 8 extra), R:R 1:5 or 1:10, own TF/min/max, partial at c20_ptp_r (2R). Strategy "confirm20" in backtest. /api/confirm12?set=c20.
- Generic _run_stream(kind) for c12/c20. Optimize-all jobs persisted in db.bot_opt_jobs and resumed on startup; GET /api/bot/optimize-all/current.
- Simular tab ((tabs)/simulate.tsx): calculator-style monthly sim of bot setups + 12C + Sniper20 per bot symbol, with/without AI filter (max 40 AI evals), partial TP toggle. POST /api/simulate, GET /api/simulate/{id}.
- Removed strategy limits (simulation unlimited items, bot setups unlimited); AI evals cap 150.
- Simulation: daily compounding (fixes inflated per-trade compounding), avg daily %, capital min $10 (dynamic step), 'Retirar negativos' removes negative setups from bot + deselects + re-runs.
- Sniper 20 per-pair optimizer: POST /api/bot/c20-optimize, GET /api/bot/c20-optimize/{id}; best TF(5m..1d)×R:R(5,10)×min(14,16,18) by train, saved live to bot.c20_pairs; pairs with test≤0 disabled. Stream + simulation use per-pair settings.
- Results screen /results: GET /api/bot/daily-results?scope=all|bot|hfx&days → per-day pnl/%/winrate, totals, avg/day, green/red days. Links: bot, hfx-bot, Ferramentas.
- Portfolio daily history: scope=portfolio (all positions + all HFX trades) in /results; entry card in Carteira tab (open-portfolio-daily).
- Binance Spot live execution (binance_exec.py): bot live_mode paper|binance, live_max_usd cap; crypto BUY entries only, sells on close/partial; GET /api/live/status. Keys BINANCE_API_KEY/SECRET, BINANCE_BASE_URL (default testnet). Forex.com pending.
- MetaTrader via MetaApi (metaapi_exec.py): live_mode 'metatrader', POST /api/live/mt/connect (password not stored), GET /api/live/mt/status, DELETE /api/live/mt; entries with SL/TP sent to MT (forex/gold/silver/BTC/ETH), partial via POSITION_PARTIAL + BE modify, close via POSITION_CLOSE_ID; mt_max_lots, mt_suffix. Needs METAAPI_TOKEN.
- Simulation negatives optimizer: POST /api/simulate/optimize-negatives {items}, GET .../{id}, POST .../{id}/apply (replace negative setups with >6% optimized or remove; Sniper20 pairs re-tuned or disabled). UI NegOptimize in Simular.
- Position limits up to 30 (default 30) for main/12C/20C; sizing capped by free margin at 1:500 leverage (_margin_qty). Existing bots set to 30.
- MQL5 EA: backend/static/SmartTrade12C.mq5 served at GET /api/ea/SmartTrade12C.mq5 (download button in MetaTrader card). Not compiled (.ex5 must be built in MetaEditor). c12 per-pair optimizer added (kind=c12, c12_pairs).

## Fork update (Jun 2026)
- FIXED: simulation counted at most 50 trades per strategy (run_backtest trades[-50:]); now uses all trades (all_trades=True). avg_daily uses the days the data actually covers (days_covered returned + UI note).
- FIXED: c12/c20 optimizer lock is now per kind. Results best/worst day coloured by sign.
- NEW: /ea-guide screen (Ferramentas + MT card) with the .mq5 download + 4 steps to compile .ex5 in MetaEditor (an .ex5 cannot be compiled on Linux).
- NEW: SmartTradeAll.mq5 generator (ea_gen.py + static/SmartTradeAll.mq5.tpl). One EA on one chart trades ALL bot setups (all 31 strategies incl. SMC/combo/confluence) + 12C/20C per-pair optimized TF/R:R/min, HTF filter, partial TP, BE, per-kind max positions, blocked hours. Endpoints: GET /api/ea/all (preview), POST /api/ea/all/link -> GET /api/ea/all/{token}/SmartTradeAll.mq5 (15 min token). Parity test tests/mql_parity.py: MQL5 signals == Python 100%.
- NEW: SmartTradeNow.mq5 one-shot MT5 script (POST /api/ea/all/link?script=1): evaluates all setups (signals of last N=3 bars), MessageBox confirm, opens orders with same magic IDs as EA.
- MetaApi live: link existing MetaApi account (GET /live/mt/accounts, POST /live/mt/link, /live/mt/deploy), POST /live/mt/test-order & /test-close. FIX: removed invalid clientId (MetaApi pattern) from bot MT orders. Verified real demo order BTCUSD 0.01 on Vantage MT5 26366289 (london) linked to user_test1.
- Bot of user_ae22099ebd57 (sertgio) switched to live_mode=metatrader until 2026-11-08 (auto back to paper via live_until). MT sizing now uses real MT equity + broker tick value; symbols checked against broker list (XAUUSD skipped when min lot > 2x risk). MT account moved from user_test1 to that user.
- FIX: MT orders skipped when broker spread > 30% of stop distance (ADAUSD spread 3.4% caused INVALID_STOPS).
