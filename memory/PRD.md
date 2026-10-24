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
