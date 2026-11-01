//+------------------------------------------------------------------+
//| SmartTradeAll.mq5 — Expert Advisor "Todas as Estratégias" (SmartTrade AI)
//| Gerado para: __USER__ em __DATE__
//| Contém TODAS as estratégias/setups do teu robô com os timeframes, R:R, stops,
//| filtros e confirmações otimizados na app (+ 12 Confirmações e Sniper 20 por par).
//| Funciona num ÚNICO gráfico: opera sozinho todos os pares/timeframes da tabela.
//| Compilar no MetaEditor (F7) para gerar o .ex5. Testar SEMPRE primeiro em conta demo.
//+------------------------------------------------------------------+
#property copyright "SmartTrade AI"
#property version   "2.00"
#include <Trade/Trade.mqh>

input double RiskPercent       = __RISK__;   // Risco por trade (% do capital)
input bool   EnableSetups      = true;       // Ativar setups de estratégia
input bool   EnableC12         = __C12ON__;  // Ativar 12 Confirmações
input bool   EnableC20         = __C20ON__;  // Ativar Sniper 20
input int    MaxSetupPositions = __MAXS__;   // Máx. posições abertas (setups)
input int    MaxC12Positions   = __MAX12__;  // Máx. posições abertas (12C)
input int    MaxC20Positions   = __MAX20__;  // Máx. posições abertas (20C)
input bool   UsePartial        = __PTPON__;  // TP parcial + break-even
input double PartialPct        = __PTPPCT__; // % a fechar no alvo parcial
input double MaxLots           = __MAXLOTS__;// Máx. lotes por ordem
input string SymbolSuffix      = "__SUFFIX__"; // Sufixo dos símbolos na corretora (ex.: .m)
input long   MagicBase         = 2600000;    // Número mágico base (cada setup tem um ID fixo)

#define NA EMPTY_VALUE
__CONFIG__

int SmcK = -1;
int SigBars = 1;     // EA: só a última vela fechada · script: últimas N velas
int StreamCap = 2;   // máx. novas entradas 12C/20C por ciclo
void Confluence(double &sig[]);
void Votes(int n, double &up[], double &dn[]);

CTrade trade;
datetime LastBar[];
long     SrvOffset = 0;   // servidor - UTC (segundos)
int      BarsLoad = 600;

// ---------------------------------------------------------------- dados
double O[], H[], L[], C[], V[];
datetime T[];
int N = 0;

bool LoadBars(string sym, ENUM_TIMEFRAMES tf, int count) {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(sym, tf, 1, count, r);   // só velas FECHADAS
   if(got < 260) return false;
   N = got;
   ArrayResize(O, N); ArrayResize(H, N); ArrayResize(L, N); ArrayResize(C, N); ArrayResize(V, N); ArrayResize(T, N);
   for(int i = 0; i < N; i++) { O[i] = r[i].open; H[i] = r[i].high; L[i] = r[i].low; C[i] = r[i].close; V[i] = (double)r[i].real_volume; T[i] = r[i].time; }
   SmcK = -1;
   return true;
}

double P(string key) {
   for(int i = 0; i < ArraySize(PKey); i++) if(PKey[i] == key) return PVal[i];
   return 0;
}

int Sgn(double x) { return x > 0 ? 1 : (x < 0 ? -1 : 0); }
int SgnV(double a, double b) { if(a == NA || b == NA) return 0; return Sgn(a - b); }

// ---------------------------------------------------------------- indicadores (iguais aos da app)
void Ema(const double &x[], int p, double &o[]) {
   int n = ArraySize(x); ArrayResize(o, n); if(n == 0) return;
   double a = 2.0 / (p + 1); o[0] = x[0];
   for(int i = 1; i < n; i++) o[i] = a * x[i] + (1 - a) * o[i - 1];
}
void Sma(const double &x[], int p, double &o[]) {
   int n = ArraySize(x); ArrayResize(o, n);
   for(int i = 0; i < n; i++) {
      o[i] = NA; if(i < p - 1) continue;
      double s = 0; bool ok = true;
      for(int k = i - p + 1; k <= i; k++) { if(x[k] == NA) { ok = false; break; } s += x[k]; }
      if(ok) o[i] = s / p;
   }
}
void Std(const double &x[], int p, double &o[]) {
   int n = ArraySize(x); ArrayResize(o, n);
   for(int i = 0; i < n; i++) {
      if(i < p - 1) { o[i] = NA; continue; }
      double m = 0; for(int k = i - p + 1; k <= i; k++) m += x[k]; m /= p;
      double v = 0; for(int k = i - p + 1; k <= i; k++) v += (x[k] - m) * (x[k] - m);
      o[i] = MathSqrt(v / (p - 1));
   }
}
void Rsi(const double &c[], int p, double &o[]) {
   int n = ArraySize(c); ArrayResize(o, n); if(n == 0) return; o[0] = 50;
   double a = 1.0 / p, au = 0, ad = 0;
   for(int i = 1; i < n; i++) {
      double d = c[i] - c[i - 1], u = d > 0 ? d : 0, w = d < 0 ? -d : 0;
      if(i == 1) { au = u; ad = w; } else { au = a * u + (1 - a) * au; ad = a * w + (1 - a) * ad; }
      o[i] = ad == 0 ? 50 : 100 - 100 / (1 + au / ad);
   }
}
void Atr(int p, double &o[]) {
   ArrayResize(o, N); if(N == 0) return; o[0] = H[0] - L[0];
   for(int i = 1; i < N; i++) {
      double tr = MathMax(H[i] - L[i], MathMax(MathAbs(H[i] - C[i - 1]), MathAbs(L[i] - C[i - 1])));
      o[i] = o[i - 1] + (tr - o[i - 1]) / p;
   }
}
double Hi(int from, int to) { double m = -DBL_MAX; for(int k = from; k <= to; k++) m = MathMax(m, H[k]); return m; }
double Lo(int from, int to) { double m = DBL_MAX; for(int k = from; k <= to; k++) m = MathMin(m, L[k]); return m; }
int Cross(const double &a[], const double &b[], int i) {
   if(i < 1 || a[i] == NA || b[i] == NA || a[i - 1] == NA || b[i - 1] == NA) return 0;
   if(a[i] > b[i] && a[i - 1] <= b[i - 1]) return 1;
   if(a[i] < b[i] && a[i - 1] >= b[i - 1]) return -1;
   return 0;
}
void Flips(const double &d[], double &o[]) { int n = ArraySize(d); ArrayResize(o, n); o[0] = 0; for(int i = 1; i < n; i++) o[i] = d[i] != d[i - 1] ? d[i] : 0; }
void Changes(const double &raw[], double &o[]) { int n = ArraySize(raw); ArrayResize(o, n); for(int i = 0; i < n; i++) { double pv = i > 0 ? raw[i - 1] : 0; o[i] = raw[i] != pv ? raw[i] : 0; } }

void SupertrendDir(int p, double m, double &d[]) {
   double a[]; Atr(p, a); ArrayResize(d, N);
   double fu = (H[0] + L[0]) / 2 + m * a[0], fl = (H[0] + L[0]) / 2 - m * a[0]; d[0] = 1;
   for(int i = 1; i < N; i++) {
      double hl2 = (H[i] + L[i]) / 2, ub = hl2 + m * a[i], lb = hl2 - m * a[i];
      double pfu = fu, pfl = fl;
      fu = (ub < pfu || C[i - 1] > pfu) ? ub : pfu;
      fl = (lb > pfl || C[i - 1] < pfl) ? lb : pfl;
      d[i] = C[i] > pfu ? 1 : (C[i] < pfl ? -1 : d[i - 1]);
   }
}
void PsarDir(double step, double mx, double &d[]) {
   ArrayResize(d, N); d[0] = 1; if(N < 2) return;
   bool up = true; double sar = L[0], ep = H[0], af = step;
   for(int i = 1; i < N; i++) {
      sar = sar + af * (ep - sar);
      if(up) {
         sar = MathMin(sar, MathMin(L[i - 1], i > 1 ? L[i - 2] : L[i - 1]));
         if(L[i] < sar) { up = false; sar = ep; ep = L[i]; af = step; }
         else if(H[i] > ep) { ep = H[i]; af = MathMin(af + step, mx); }
      } else {
         sar = MathMax(sar, MathMax(H[i - 1], i > 1 ? H[i - 2] : H[i - 1]));
         if(H[i] > sar) { up = true; sar = ep; ep = H[i]; af = step; }
         else if(L[i] < ep) { ep = L[i]; af = MathMin(af + step, mx); }
      }
      d[i] = up ? 1 : -1;
   }
}
void AdxDi(int p, double &pdi[], double &ndi[], double &adx[]) {
   double a[]; Atr(p, a); ArrayResize(pdi, N); ArrayResize(ndi, N); ArrayResize(adx, N);
   double al = 1.0 / p, ep = 0, en = 0, ex = 0;
   for(int i = 0; i < N; i++) {
      double upm = i > 0 ? H[i] - H[i - 1] : 0, dnm = i > 0 ? L[i - 1] - L[i] : 0;
      double pdm = (upm > dnm && upm > 0) ? upm : 0, ndm = (dnm > upm && dnm > 0) ? dnm : 0;
      if(i == 0) { ep = pdm; en = ndm; } else { ep = al * pdm + (1 - al) * ep; en = al * ndm + (1 - al) * en; }
      pdi[i] = a[i] > 0 ? ep / a[i] * 100 : 0; ndi[i] = a[i] > 0 ? en / a[i] * 100 : 0;
      double s = pdi[i] + ndi[i], dx = s > 0 ? MathAbs(pdi[i] - ndi[i]) / s * 100 : 0;
      ex = i == 0 ? dx : al * dx + (1 - al) * ex; adx[i] = ex;
   }
}
void Ichimoku(int t, int k, double &tk[], double &kj[], double &sa[], double &sb[]) {
   ArrayResize(tk, N); ArrayResize(kj, N); ArrayResize(sa, N); ArrayResize(sb, N);
   double s2[]; ArrayResize(s2, N);
   for(int i = 0; i < N; i++) {
      tk[i] = i >= t - 1 ? (Hi(i - t + 1, i) + Lo(i - t + 1, i)) / 2 : NA;
      kj[i] = i >= k - 1 ? (Hi(i - k + 1, i) + Lo(i - k + 1, i)) / 2 : NA;
      s2[i] = i >= 2 * k - 1 ? (Hi(i - 2 * k + 1, i) + Lo(i - 2 * k + 1, i)) / 2 : NA;
   }
   for(int i = 0; i < N; i++) {
      int j = i - k;
      sa[i] = (j >= 0 && tk[j] != NA && kj[j] != NA) ? (tk[j] + kj[j]) / 2 : NA;
      sb[i] = (j >= 0 && s2[j] != NA) ? s2[j] : NA;
   }
}
void RollVwap(int p, double &o[]) {
   ArrayResize(o, N);
   for(int i = 0; i < N; i++) {
      if(i < p - 1) { o[i] = NA; continue; }
      double pv = 0, vs = 0, tpm = 0;
      for(int k = i - p + 1; k <= i; k++) { double tp = (H[k] + L[k] + C[k]) / 3; pv += tp * V[k]; vs += V[k]; tpm += tp; }
      o[i] = vs > 0 ? pv / vs : tpm / p;
   }
}
void StochK(int rl, int sl, double &k[]) {
   double r[]; Rsi(C, rl, r); double raw[]; ArrayResize(raw, N); ArrayResize(k, N);
   for(int i = 0; i < N; i++) {
      if(i < sl - 1) { raw[i] = 50; continue; }
      double lo = DBL_MAX, hi = -DBL_MAX; for(int j = i - sl + 1; j <= i; j++) { lo = MathMin(lo, r[j]); hi = MathMax(hi, r[j]); }
      raw[i] = hi - lo > 0 ? (r[i] - lo) / (hi - lo) * 100 : 50;
   }
   Sma(raw, 3, k);
}
void Cci(int p, double &o[]) {
   ArrayResize(o, N);
   for(int i = 0; i < N; i++) {
      if(i < p - 1) { o[i] = NA; continue; }
      double m = 0; for(int k = i - p + 1; k <= i; k++) m += (H[k] + L[k] + C[k]) / 3; m /= p;
      double md = 0; for(int k = i - p + 1; k <= i; k++) md += MathAbs((H[k] + L[k] + C[k]) / 3 - m); md /= p;
      o[i] = md > 0 ? ((H[i] + L[i] + C[i]) / 3 - m) / (0.015 * md) : NA;
   }
}

// ---------------------------------------------------------------- Smart Money (BOS/CHoCH, OB, FVG, Breaker, OTE)
struct OBx { int dir; double top, bottom; int created; bool active; };
struct FVx { int dir; double top, bottom; int idx; bool filled, used; };
struct BRx { int dir; double top, bottom; int created; bool done; };
double SmcSig[], SmcTrend[], SmcChoch[], SmcFvg[], SmcBreaker[], SmcOte[], SwHi[], SwLo[];

void Smc(int k) {
   if(SmcK == k) return;
   SmcK = k;
   ArrayResize(SmcSig, N); ArrayResize(SmcTrend, N); ArrayResize(SmcChoch, N); ArrayResize(SmcFvg, N);
   ArrayResize(SmcBreaker, N); ArrayResize(SmcOte, N); ArrayResize(SwHi, N); ArrayResize(SwLo, N);
   ArrayInitialize(SmcSig, 0); ArrayInitialize(SmcTrend, 0); ArrayInitialize(SmcChoch, 0); ArrayInitialize(SmcFvg, 0);
   ArrayInitialize(SmcBreaker, 0); ArrayInitialize(SmcOte, 0); ArrayInitialize(SwHi, NA); ArrayInitialize(SwLo, NA);
   OBx obs[]; FVx fv[]; BRx br[];
   int trend = 0, shI = -1, slI = -1; double shP = 0, slP = 0; bool shB = true, slB = true;
   bool legOn = false, legUsed = true; int legDir = 0; double legLo = 0, legHi = 0;
   for(int i = 0; i < N; i++) {
      int j = i - k;
      if(j >= k) {
         if(H[j] == Hi(j - k, j + k)) { shI = j; shP = H[j]; shB = false; SwHi[i] = H[j]; }
         if(L[j] == Lo(j - k, j + k)) { slI = j; slP = L[j]; slB = false; SwLo[i] = L[j]; }
      }
      if(i >= 2) {
         int f = ArraySize(fv);
         if(L[i] > H[i - 2]) { ArrayResize(fv, f + 1); fv[f].dir = 1; fv[f].top = L[i]; fv[f].bottom = H[i - 2]; fv[f].idx = i - 1; fv[f].filled = false; fv[f].used = false; }
         else if(H[i] < L[i - 2]) { ArrayResize(fv, f + 1); fv[f].dir = -1; fv[f].top = L[i - 2]; fv[f].bottom = H[i]; fv[f].idx = i - 1; fv[f].filled = false; fv[f].used = false; }
      }
      if(shI >= 0 && !shB && C[i] > shP) {
         if(trend == -1) SmcChoch[i] = 1;
         trend = 1; shB = true;
         legOn = true; legUsed = false; legDir = 1; legLo = slI >= 0 ? slP : Lo(MathMax(0, i - 20), i); legHi = H[i];
         for(int m = i - 1; m >= MathMax(shI - 10, 0); m--) if(C[m] < O[m]) {
            int b = ArraySize(obs); ArrayResize(obs, b + 1); obs[b].dir = 1; obs[b].top = H[m]; obs[b].bottom = L[m]; obs[b].created = i; obs[b].active = true; break;
         }
      }
      if(slI >= 0 && !slB && C[i] < slP) {
         if(trend == 1) SmcChoch[i] = -1;
         trend = -1; slB = true;
         legOn = true; legUsed = false; legDir = -1; legHi = shI >= 0 ? shP : Hi(MathMax(0, i - 20), i); legLo = L[i];
         for(int m = i - 1; m >= MathMax(slI - 10, 0); m--) if(C[m] > O[m]) {
            int b = ArraySize(obs); ArrayResize(obs, b + 1); obs[b].dir = -1; obs[b].top = H[m]; obs[b].bottom = L[m]; obs[b].created = i; obs[b].active = true; break;
         }
      }
      for(int q = 0; q < ArraySize(obs); q++) {
         if(!obs[q].active || i <= obs[q].created) continue;
         if(obs[q].dir == 1) {
            if(C[i] < obs[q].bottom) { obs[q].active = false; int b = ArraySize(br); ArrayResize(br, b + 1); br[b].dir = -1; br[b].top = obs[q].top; br[b].bottom = obs[q].bottom; br[b].created = i; br[b].done = false; }
            else if(L[i] <= obs[q].top && trend == 1 && SmcSig[i] == 0) { SmcSig[i] = 1; obs[q].active = false; }
         } else {
            if(C[i] > obs[q].top) { obs[q].active = false; int b = ArraySize(br); ArrayResize(br, b + 1); br[b].dir = 1; br[b].top = obs[q].top; br[b].bottom = obs[q].bottom; br[b].created = i; br[b].done = false; }
            else if(H[i] >= obs[q].bottom && trend == -1 && SmcSig[i] == 0) { SmcSig[i] = -1; obs[q].active = false; }
         }
      }
      for(int q = 0; q < ArraySize(fv); q++) {
         if(fv[q].filled || i <= fv[q].idx + 1) continue;
         if((fv[q].dir == 1 && L[i] <= fv[q].bottom) || (fv[q].dir == -1 && H[i] >= fv[q].top)) fv[q].filled = true;
         else if(!fv[q].used && fv[q].dir == 1 && trend == 1 && L[i] <= fv[q].top && C[i] > fv[q].top) { SmcFvg[i] = 1; fv[q].used = true; }
         else if(!fv[q].used && fv[q].dir == -1 && trend == -1 && H[i] >= fv[q].bottom && C[i] < fv[q].bottom) { SmcFvg[i] = -1; fv[q].used = true; }
      }
      for(int q = 0; q < ArraySize(br); q++) {
         if(br[q].done || i <= br[q].created) continue;
         if(br[q].dir == 1 && trend == 1 && L[i] <= br[q].top && C[i] > br[q].top) { SmcBreaker[i] = 1; br[q].done = true; }
         else if(br[q].dir == -1 && trend == -1 && H[i] >= br[q].bottom && C[i] < br[q].bottom) { SmcBreaker[i] = -1; br[q].done = true; }
         else if((br[q].dir == 1 && C[i] < br[q].bottom) || (br[q].dir == -1 && C[i] > br[q].top)) br[q].done = true;
      }
      if(legOn && !legUsed) {
         if(legDir == 1) {
            if(trend != 1 || C[i] < legLo) legUsed = true;
            else {
               legHi = MathMax(legHi, H[i]); double rng = legHi - legLo, zt = legHi - 0.62 * rng, zb = legHi - 0.79 * rng;
               if(rng > 0 && L[i] <= zt && C[i] > zb && C[i] > O[i]) { SmcOte[i] = 1; legUsed = true; }
            }
         } else {
            if(trend != -1 || C[i] > legHi) legUsed = true;
            else {
               legLo = MathMin(legLo, L[i]); double rng = legHi - legLo, zb = legLo + 0.62 * rng, zt = legLo + 0.79 * rng;
               if(rng > 0 && H[i] >= zb && C[i] < zt && C[i] < O[i]) { SmcOte[i] = -1; legUsed = true; }
            }
         }
      }
      SmcTrend[i] = trend;
   }
}

// ---------------------------------------------------------------- sinais por estratégia (1 compra, -1 venda, 0 nada)
void Sweep(int n, double &o[]) {
   ArrayResize(o, N); ArrayInitialize(o, 0);
   for(int i = n; i < N; i++) {
      double ph = Hi(i - n, i - 1), pl = Lo(i - n, i - 1);
      if(L[i] < pl && C[i] > pl && C[i] > O[i]) o[i] = 1; else if(H[i] > ph && C[i] < ph && C[i] < O[i]) o[i] = -1;
   }
}

void Signals(string s, double &sig[]) {
   ArrayResize(sig, N); ArrayInitialize(sig, 0);
   if(s == "smc") { Smc((int)P("smc.swing")); ArrayCopy(sig, SmcSig); return; }
   if(s == "fvg") { Smc((int)P("fvg.swing")); ArrayCopy(sig, SmcFvg); return; }
   if(s == "choch") { Smc((int)P("choch.swing")); ArrayCopy(sig, SmcChoch); return; }
   if(s == "ote") { Smc((int)P("ote.swing")); ArrayCopy(sig, SmcOte); return; }
   if(s == "breaker") { Smc((int)P("breaker.swing")); ArrayCopy(sig, SmcBreaker); return; }
   if(s == "rsi") {
      double r[]; Rsi(C, (int)P("rsi.length"), r); double os = P("rsi.oversold"), ob = P("rsi.overbought");
      for(int i = 1; i < N; i++) sig[i] = (r[i] > os && r[i - 1] <= os) ? 1 : ((r[i] < ob && r[i - 1] >= ob) ? -1 : 0);
      return;
   }
   if(s == "ema_cross") { double a[], b[]; Ema(C, (int)P("ema_cross.fast"), a); Ema(C, (int)P("ema_cross.slow"), b); for(int i = 1; i < N; i++) sig[i] = Cross(a, b, i); return; }
   if(s == "macd") {
      double a[], b[], m[], g[]; Ema(C, (int)P("macd.fast"), a); Ema(C, (int)P("macd.slow"), b); ArrayResize(m, N);
      for(int i = 0; i < N; i++) m[i] = a[i] - b[i];
      Ema(m, (int)P("macd.signal"), g); for(int i = 1; i < N; i++) sig[i] = Cross(m, g, i); return;
   }
   if(s == "bollinger") {
      int n = (int)P("bollinger.length"); double k = P("bollinger.mult"); double mid[], sd[]; Sma(C, n, mid); Std(C, n, sd);
      for(int i = n; i < N; i++) {
         double lo = mid[i] - k * sd[i], hi = mid[i] + k * sd[i], plo = mid[i - 1] - k * sd[i - 1], phi = mid[i - 1] + k * sd[i - 1];
         sig[i] = (C[i] > lo && C[i - 1] <= plo) ? 1 : ((C[i] < hi && C[i - 1] >= phi) ? -1 : 0);
      }
      return;
   }
   if(s == "pullback") {
      double e[], t[], e2[], raw[]; Ema(C, (int)P("pullback.ema"), e); Ema(C, (int)P("pullback.trend"), t); Ema(C, 200, e2); ArrayResize(raw, N);
      for(int i = 0; i < N; i++) {
         bool up = t[i] > e2[i] && C[i] > t[i] && L[i] <= e[i] && C[i] > e[i] && C[i] > O[i];
         bool dn = t[i] < e2[i] && C[i] < t[i] && H[i] >= e[i] && C[i] < e[i] && C[i] < O[i];
         raw[i] = up ? 1 : (dn ? -1 : 0);
      }
      Changes(raw, sig); return;
   }
   if(s == "supertrend") { double d[]; SupertrendDir((int)P("supertrend.atr_len"), P("supertrend.st_mult"), d); Flips(d, sig); return; }
   if(s == "psar") { double d[]; PsarDir(P("psar.step"), P("psar.max_step"), d); Flips(d, sig); return; }
   if(s == "stoch_rsi") {
      double k[], dd[]; StochK((int)P("stoch_rsi.length"), (int)P("stoch_rsi.stoch"), k); Sma(k, 3, dd); double lv = P("stoch_rsi.lvl");
      for(int i = 1; i < N; i++) {
         if(k[i] == NA || dd[i] == NA || k[i - 1] == NA || dd[i - 1] == NA) continue;
         if(k[i] > dd[i] && k[i - 1] <= dd[i - 1] && dd[i] < lv) sig[i] = 1;
         else if(k[i] < dd[i] && k[i - 1] >= dd[i - 1] && dd[i] > 100 - lv) sig[i] = -1;
      }
      return;
   }
   if(s == "adx") {
      double p[], n[], a[]; AdxDi((int)P("adx.length"), p, n, a); double th = P("adx.threshold");
      for(int i = 1; i < N; i++) sig[i] = a[i] > th ? Cross(p, n, i) : 0; return;
   }
   if(s == "donchian") {
      int n = (int)P("donchian.length");
      for(int i = n + 1; i < N; i++) {
         double hh = Hi(i - n, i - 1), ll = Lo(i - n, i - 1), phh = Hi(i - n - 1, i - 2), pll = Lo(i - n - 1, i - 2);
         sig[i] = (C[i] > hh && C[i - 1] <= phh) ? 1 : ((C[i] < ll && C[i - 1] >= pll) ? -1 : 0);
      }
      return;
   }
   if(s == "killzone") {
      Smc((int)P("killzone.swing"));
      for(int i = 0; i < N; i++) {
         MqlDateTime dt; TimeToStruct(T[i] - SrvOffset, dt); int h = dt.hour;
         bool kz = h == 7 || h == 8 || h == 9 || h == 12 || h == 13 || h == 14;
         sig[i] = kz ? (SmcSig[i] != 0 ? SmcSig[i] : SmcFvg[i]) : 0;
      }
      return;
   }
   if(s == "eq_liquidity") {
      Smc((int)P("eq_liquidity.swing")); double a[]; Atr(14, a); double tol = P("eq_liquidity.tol");
      double hs[2], ls[2]; int nh = 0, nl = 0;
      for(int i = 0; i < N; i++) {
         if(SwHi[i] != NA) { if(nh == 2) { hs[0] = hs[1]; nh = 1; } hs[nh++] = SwHi[i]; }
         if(SwLo[i] != NA) { if(nl == 2) { ls[0] = ls[1]; nl = 1; } ls[nl++] = SwLo[i]; }
         if(nh == 2 && MathAbs(hs[0] - hs[1]) <= a[i] * tol) { double lv = MathMax(hs[0], hs[1]); if(H[i] > lv && C[i] < lv && C[i] < O[i]) { sig[i] = -1; nh = 0; } }
         if(nl == 2 && MathAbs(ls[0] - ls[1]) <= a[i] * tol) { double lv = MathMin(ls[0], ls[1]); if(L[i] < lv && C[i] > lv && C[i] > O[i]) { sig[i] = 1; nl = 0; } }
      }
      return;
   }
   if(s == "sweep") { Sweep((int)P("sweep.length"), sig); return; }
   if(s == "sweep_choch") {
      double sw[]; Sweep((int)P("sweep_choch.length"), sw); Smc(3); int w = (int)P("sweep_choch.window");
      double last = 0; int lastI = -100000;
      for(int i = 0; i < N; i++) {
         if(sw[i] != 0) { last = sw[i]; lastI = i; }
         double recent = (i - lastI <= w) ? last : 0;
         sig[i] = (SmcChoch[i] != 0 && SmcChoch[i] == recent) ? SmcChoch[i] : 0;
      }
      return;
   }
   if(s == "ichimoku") {
      double tk[], kj[], sa[], sb[]; Ichimoku((int)P("ichimoku.tenkan"), (int)P("ichimoku.kijun"), tk, kj, sa, sb);
      for(int i = 1; i < N; i++) {
         if(sa[i] == NA || sb[i] == NA) continue; int x = Cross(tk, kj, i);
         if(x > 0 && C[i] > MathMax(sa[i], sb[i])) sig[i] = 1; else if(x < 0 && C[i] < MathMin(sa[i], sb[i])) sig[i] = -1;
      }
      return;
   }
   if(s == "vwap") { double vw[]; RollVwap((int)P("vwap.length"), vw); for(int i = 1; i < N; i++) sig[i] = Cross(C, vw, i); return; }
   if(s == "williams_r") {
      int n = (int)P("williams_r.length"); double wr[]; ArrayResize(wr, N);
      for(int i = 0; i < N; i++) { if(i < n - 1) { wr[i] = -50; continue; } double hh = Hi(i - n + 1, i), ll = Lo(i - n + 1, i); wr[i] = hh - ll > 0 ? (hh - C[i]) / (hh - ll) * -100 : -50; }
      for(int i = 1; i < N; i++) sig[i] = (wr[i] > -80 && wr[i - 1] <= -80) ? 1 : ((wr[i] < -20 && wr[i - 1] >= -20) ? -1 : 0);
      return;
   }
   if(s == "cci") {
      double c[]; Cci((int)P("cci.length"), c);
      for(int i = 1; i < N; i++) { double a = c[i] == NA ? 0 : c[i], b = c[i - 1] == NA ? 0 : c[i - 1]; sig[i] = (a > -100 && b <= -100) ? 1 : ((a < 100 && b >= 100) ? -1 : 0); }
      return;
   }
   if(s == "keltner") {
      double mid[], a[], up[], dn[]; Ema(C, (int)P("keltner.length"), mid); Atr(10, a); double m = P("keltner.mult"); ArrayResize(up, N); ArrayResize(dn, N);
      for(int i = 0; i < N; i++) { up[i] = mid[i] + a[i] * m; dn[i] = mid[i] - a[i] * m; }
      for(int i = 1; i < N; i++) sig[i] = Cross(C, up, i) > 0 ? 1 : (Cross(C, dn, i) < 0 ? -1 : 0);
      return;
   }
   if(s == "pin_bar") {
      double k = P("pin_bar.wick");
      for(int i = 0; i < N; i++) {
         double body = MathMax(MathAbs(C[i] - O[i]), 1e-12), rng = H[i] - L[i]; if(rng <= 0) continue;
         double lw = MathMin(O[i], C[i]) - L[i], uw = H[i] - MathMax(O[i], C[i]);
         if(lw >= k * body && lw >= 0.6 * rng && (C[i] - L[i]) / rng >= 0.66) sig[i] = 1;
         else if(uw >= k * body && uw >= 0.6 * rng && (H[i] - C[i]) / rng >= 0.66) sig[i] = -1;
      }
      return;
   }
   if(s == "engulfing") {
      for(int i = 1; i < N; i++) {
         if(C[i] > O[i] && C[i - 1] < O[i - 1] && C[i] >= O[i - 1] && O[i] <= C[i - 1]) sig[i] = 1;
         else if(C[i] < O[i] && C[i - 1] > O[i - 1] && C[i] <= O[i - 1] && O[i] >= C[i - 1]) sig[i] = -1;
      }
      return;
   }
   if(s == "inside_bar") {
      for(int i = 2; i < N; i++) {
         bool ins = H[i - 1] < H[i - 2] && L[i - 1] > L[i - 2];
         if(ins && C[i] > H[i - 2]) sig[i] = 1; else if(ins && C[i] < L[i - 2]) sig[i] = -1;
      }
      return;
   }
   if(s == "combo") {
      double e2[], tot[]; Ema(C, 200, e2); ArrayResize(tot, N); ArrayInitialize(tot, 0);
      for(int p = 0; p < ArraySize(Plugins); p++) {
         if(P(Plugins[p] + ".enabled") < 0.5) continue;
         double x[]; Signals(Plugins[p], x); for(int i = 0; i < N; i++) tot[i] += x[i];
      }
      for(int i = 0; i < N; i++) { int tr = C[i] > e2[i] ? 1 : -1; sig[i] = Sgn(tot[i]) == tr ? tr : 0; }
      return;
   }
   if(s == "confluence") { Confluence(sig); return; }
   if(s == "confirm12" || s == "confirm20") {
      int n = s == "confirm12" ? 12 : 20, need = (int)P(s == "confirm12" ? "_c12.min" : "_c20.min");
      double up[], dn[], raw[]; Votes(n, up, dn); ArrayResize(raw, N);
      for(int i = 0; i < N; i++) raw[i] = up[i] >= need ? 1 : (dn[i] >= need ? -1 : 0);
      Changes(raw, sig); return;
   }
}

void Confluence(double &sig[]) {
   int mem = (int)P("_conf.memory"), hz = (int)P("_conf.horizon"), lb = (int)P("_conf.lookback"), mv = (int)P("_conf.min_votes");
   double ms = P("_conf.min_score");
   double un[], dn[], uw[], dw[], e2[], fut[];
   ArrayResize(un, N); ArrayResize(dn, N); ArrayResize(uw, N); ArrayResize(dw, N); ArrayResize(fut, N);
   ArrayInitialize(un, 0); ArrayInitialize(dn, 0); ArrayInitialize(uw, 0); ArrayInitialize(dw, 0); ArrayInitialize(fut, 0);
   for(int i = 0; i + hz < N; i++) fut[i] = Sgn(C[i + hz] - C[i]);
   for(int p = 0; p < ArraySize(Plugins); p++) {
      if(P(Plugins[p] + ".enabled") < 0.5) continue;
      double s[]; Signals(Plugins[p], s);
      double last = 0; int lastI = -100000, win = 0, cnt = 0;
      for(int i = 0; i < N; i++) {
         if(s[i] != 0) { last = s[i]; lastI = i; }
         double v = (i - lastI <= mem - 1) ? last : 0;
         int j = i - hz;                       // resultados já conhecidos na vela i
         if(j >= 0) { if(s[j] * fut[j] > 0) win++; if(s[j] != 0) cnt++; }
         int jo = i - hz - lb;                 // sai da janela
         if(jo >= 0) { if(s[jo] * fut[jo] > 0) win--; if(s[jo] != 0) cnt--; }
         double w = cnt >= 5 ? (double)win / cnt : 0.5;
         if(v > 0) { un[i]++; uw[i] += w; } else if(v < 0) { dn[i]++; dw[i] += w; }
      }
   }
   Ema(C, 200, e2);
   double raw[]; ArrayResize(raw, N);
   for(int i = 0; i < N; i++) {
      int tr = C[i] > e2[i] ? 1 : -1;
      double su = uw[i] / MathMax(un[i], 1) * 100, sd = dw[i] / MathMax(dn[i], 1) * 100;
      raw[i] = (un[i] >= mv && dn[i] == 0 && su >= ms && tr == 1) ? 1 : ((dn[i] >= mv && un[i] == 0 && sd >= ms && tr == -1) ? -1 : 0);
   }
   Changes(raw, sig);
}

// ---------------------------------------------------------------- 12 / 20 confirmações
void Votes(int n, double &up[], double &dn[]) {
   ArrayResize(up, N); ArrayResize(dn, N); ArrayInitialize(up, 0); ArrayInitialize(dn, 0);
   double e9[], e21[], e50[], e200[], e12[], e26[], m[], ms[], r[], pdi[], ndi[], adx[], st[], ps[], tk[], kj[], sa[], sb[], vw[];
   Ema(C, 21, e21); Ema(C, 50, e50); Ema(C, 200, e200); Ema(C, 12, e12); Ema(C, 26, e26); ArrayResize(m, N);
   for(int i = 0; i < N; i++) m[i] = e12[i] - e26[i];
   Ema(m, 9, ms); Rsi(C, 14, r); AdxDi(14, pdi, ndi, adx); SupertrendDir(10, 3.0, st); PsarDir(0.02, 0.2, ps);
   Ichimoku(9, 26, tk, kj, sa, sb); Smc(3); RollVwap(20, vw);
   double s20[], cc[], k[], kd[], hav[];
   if(n == 20) {
      Ema(C, 9, e9); Sma(C, 20, s20); Cci(20, cc); StochK(14, 14, k); Sma(k, 3, kd); ArrayResize(hav, N);
      hav[0] = (O[0] + (O[0] + H[0] + L[0] + C[0]) / 4) / 2;
      for(int i = 1; i < N; i++) hav[i] = (hav[i - 1] + (O[i - 1] + H[i - 1] + L[i - 1] + C[i - 1]) / 4) / 2;
   }
   for(int i = 0; i < N; i++) {
      int v[20]; ArrayInitialize(v, 0);
      double rng = H[i] - L[i], pos = rng > 0 ? (C[i] - L[i]) / rng : 0.5;
      v[0] = Sgn(C[i] - e200[i]); v[1] = Sgn(e21[i] - e50[i]); v[2] = i >= 5 ? Sgn(e50[i] - e50[i - 5]) : 0; v[3] = Sgn(m[i] - ms[i]);
      v[4] = (r[i] > 50 && r[i] < 70) ? 1 : ((r[i] < 50 && r[i] > 30) ? -1 : 0);
      v[5] = adx[i] > 20 ? Sgn(pdi[i] - ndi[i]) : 0; v[6] = (int)st[i];
      v[7] = (sa[i] == NA || sb[i] == NA) ? 0 : (C[i] > MathMax(sa[i], sb[i]) ? 1 : (C[i] < MathMin(sa[i], sb[i]) ? -1 : 0));
      v[8] = (int)ps[i]; v[9] = (int)SmcTrend[i]; v[10] = SgnV(C[i], vw[i]);
      v[11] = (C[i] > O[i] && pos >= 0.7) ? 1 : ((C[i] < O[i] && pos <= 0.3) ? -1 : 0);
      if(n == 20) {
         v[12] = Sgn(e9[i] - e21[i]); v[13] = SgnV(C[i], s20[i]); v[14] = i >= 10 ? Sgn(C[i] - C[i - 10]) : 0;
         v[15] = cc[i] == NA ? 0 : Sgn(cc[i]);
         if(i >= 13) { double hh = Hi(i - 13, i), ll = Lo(i - 13, i); v[16] = hh - ll > 0 ? Sgn((hh - C[i]) / (hh - ll) * -100 + 50) : 0; }
         v[17] = SgnV(k[i], kd[i]);
         if(i >= 19) v[18] = Sgn(C[i] - (Hi(i - 19, i) + Lo(i - 19, i)) / 2);
         v[19] = Sgn((O[i] + H[i] + L[i] + C[i]) / 4 - hav[i]);
      }
      for(int q = 0; q < n; q++) { if(v[q] > 0) up[i]++; else if(v[q] < 0) dn[i]++; }
   }
}

// ---------------------------------------------------------------- filtros
int HtfTrend(string sym, ENUM_TIMEFRAMES htf) {
   MqlRates r[]; ArraySetAsSeries(r, false);
   int got = CopyRates(sym, htf, 1, 400, r);
   if(got < 210) return 0;
   double c[]; ArrayResize(c, got); for(int i = 0; i < got; i++) c[i] = r[i].close;
   double e50[], e200[]; Ema(c, 50, e50); Ema(c, 200, e200);
   int k = got - 1;
   if(c[k] > e50[k] && e50[k] > e200[k]) return 1;
   if(c[k] < e50[k] && e50[k] < e200[k]) return -1;
   return 0;
}

// ---------------------------------------------------------------- execução
string Sym(int i) { return CSym[i] + SymbolSuffix; }
long MagicOf(int i) { return MagicBase + CMagic[i]; }
int IndexOfMagic(long m) { for(int i = 0; i < NCFG; i++) if(MagicBase + CMagic[i] == m) return i; return -1; }

ulong MyTicket(int i) {
   for(int k = PositionsTotal() - 1; k >= 0; k--) {
      ulong t = PositionGetTicket(k);
      if(t && PositionGetInteger(POSITION_MAGIC) == MagicOf(i)) return t;
   }
   return 0;
}
int CountKind(int kind) {
   int n = 0;
   for(int k = PositionsTotal() - 1; k >= 0; k--) {
      ulong t = PositionGetTicket(k); if(!t) continue;
      int ix = IndexOfMagic(PositionGetInteger(POSITION_MAGIC));
      if(ix >= 0 && CKind[ix] == kind) n++;
   }
   return n;
}

double LotsForRisk(string sym, double slDist, ENUM_ORDER_TYPE type, double price) {
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(tv <= 0 || ts <= 0 || slDist <= 0 || step <= 0) return 0;
   double risk = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0;
   double lots = MathFloor(risk / (slDist / ts * tv) / step) * step;
   lots = MathMin(lots, MathMin(MaxLots, vmax));
   double margin = 0;   // nunca usar mais do que a margem livre (respeita a alavancagem da conta)
   while(lots >= vmin && OrderCalcMargin(type, sym, lots, price, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.9) lots -= step;
   if(lots < vmin) return 0;
   return NormalizeDouble(lots, 2);
}

bool Blocked() {
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt);
   for(int i = 0; i < ArraySize(BlockHours); i++) if(BlockHours[i] == dt.hour) return true;
   return false;
}

void ManagePositions() {
   for(int k = PositionsTotal() - 1; k >= 0; k--) {
      ulong t = PositionGetTicket(k); if(!t) continue;
      int i = IndexOfMagic(PositionGetInteger(POSITION_MAGIC));
      if(i < 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double open = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP), vol = PositionGetDouble(POSITION_VOLUME);
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      if(sl == 0 || tp == 0 || CRr[i] <= 0) continue;
      if(buy ? sl >= open : sl <= open) continue;               // já em break-even
      double r = MathAbs(tp - open) / CRr[i];
      double px = buy ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
      double moved = buy ? px - open : open - px;
      string gv = "ST_ptp_" + IntegerToString((long)t);
      if(UsePartial && PartialPct > 0 && !GlobalVariableCheck(gv) && moved >= r * CPtpR[i]) {
         double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), part = MathFloor(vol * PartialPct / 100.0 / step) * step;
         if(part >= SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN) && part < vol) trade.PositionClosePartial(t, part);
         GlobalVariableSet(gv, 1);
         trade.PositionModify(t, open, tp);
         continue;
      }
      if(moved >= r) trade.PositionModify(t, open, tp);         // +1R → stop para break-even
   }
}

// dry=true: só verifica e descreve a ordem em 'plan' (usado pelo script para pedir confirmação)
bool Evaluate(int i, int &opened12, int &opened20, bool dry, string &plan) {
   string sym = Sym(i);
   int kind = CKind[i];
   if((kind == 0 && !EnableSetups) || (kind == 1 && !EnableC12) || (kind == 2 && !EnableC20)) return false;
   if((kind == 1 && opened12 >= StreamCap) || (kind == 2 && opened20 >= StreamCap)) return false;   // evita cestos de trades correlacionados
   datetime bt = iTime(sym, CTf[i], 1);
   if(bt == 0 || bt == LastBar[i]) return false;
   LastBar[i] = bt;
   if(Blocked()) return false;
   if(!LoadBars(sym, CTf[i], BarsLoad)) return false;
   int last = N - 1, s = 0;
   if(kind == 0) {
      double sig[]; Signals(CStrat[i], sig);
      for(int k = last; k > last - SigBars && k >= 0; k--) if(sig[k] != 0) { s = (int)sig[k]; break; }
      if(s != 0 && CTrend[i] && CStrat[i] != "combo" && CStrat[i] != "confluence" && CStrat[i] != "confirm12" && CStrat[i] != "confirm20") {
         double e2[]; Ema(C, 200, e2); if(s != (C[last] > e2[last] ? 1 : -1)) s = 0;
      }
   } else {
      double up[], dn[]; Votes(kind == 1 ? 12 : 20, up, dn);
      s = up[last] >= CMin[i] ? 1 : (dn[last] >= CMin[i] ? -1 : 0);
   }
   if(s == 0) return false;
   if(CMtf[i] && CHtf[i] != PERIOD_CURRENT && HtfTrend(sym, CHtf[i]) != s) { PrintFormat("%s %s: sinal ignorado, contra a tendência do TF superior", sym, CLabel[i]); return false; }
   ulong t = MyTicket(i);
   if(t) {
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      if((buy ? 1 : -1) == s) return false;
   }
   int mx = kind == 0 ? MaxSetupPositions : (kind == 1 ? MaxC12Positions : MaxC20Positions);
   if(!t && CountKind(kind) >= mx) { PrintFormat("%s %s: limite de posições atingido", sym, CLabel[i]); return false; }
   double a[]; Atr(14, a);
   double slDist = a[last] * CSl[i];
   double price = s > 0 ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   if(slDist <= 0 || price <= 0 || slDist < 8 * CFee[i] * price) return false;   // stop curto demais face aos custos
   double pt = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(slDist < SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * pt) return false;
   ENUM_ORDER_TYPE type = s > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double lots = LotsForRisk(sym, slDist, type, price);
   if(lots <= 0) { PrintFormat("%s %s: margem/risco insuficiente", sym, CLabel[i]); return false; }
   if(dry) {
      plan += StringFormat("%s %s %s · %.2f lotes%s\n", s > 0 ? "COMPRA" : "VENDA", sym, CLabel[i], lots, t ? " (inverte posição)" : "");
      if(kind == 1) opened12++; if(kind == 2) opened20++;
      return true;
   }
   if(t) {
      trade.SetExpertMagicNumber(MagicOf(i));
      trade.PositionClose(t);
      PrintFormat("%s %s: fechado por sinal contrário", sym, CLabel[i]);
      price = s > 0 ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   }
   int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double sl = NormalizeDouble(price - s * slDist, dg), tp = NormalizeDouble(price + s * slDist * CRr[i], dg);
   trade.SetExpertMagicNumber(MagicOf(i));
   string cmt = "ST " + CLabel[i];
   bool ok = s > 0 ? trade.Buy(lots, sym, price, sl, tp, cmt) : trade.Sell(lots, sym, price, sl, tp, cmt);
   if(ok) { if(kind == 1) opened12++; if(kind == 2) opened20++; PrintFormat("%s %s %s %.2f lotes · SL %s · TP %s", s > 0 ? "COMPRA" : "VENDA", sym, CLabel[i], lots, DoubleToString(sl, dg), DoubleToString(tp, dg)); }
   else PrintFormat("%s %s: ordem recusada (%d) %s", sym, CLabel[i], trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return ok;
}

//__RUNTIME__
int OnInit() {
   ArrayResize(LastBar, NCFG); for(int i = 0; i < NCFG; i++) LastBar[i] = 0;
   SrvOffset = (long)(MathRound((double)(TimeTradeServer() - TimeGMT()) / 1800.0) * 1800);
   int ok = 0;
   for(int i = 0; i < NCFG; i++) {
      if(SymbolSelect(Sym(i), true)) ok++;
      else PrintFormat("Símbolo %s não existe nesta corretora — ajusta o sufixo (SymbolSuffix). Setup %s ignorado.", Sym(i), CLabel[i]);
   }
   PrintFormat("SmartTradeAll: %d/%d setups prontos (estratégias, 12C e 20C otimizados).", ok, NCFG);
   EventSetTimer(5);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() {
   ManagePositions();
   int o12 = 0, o20 = 0;
   string plan = "";
   for(int i = 0; i < NCFG; i++) if(SymbolInfoInteger(Sym(i), SYMBOL_SELECT)) Evaluate(i, o12, o20, false, plan);
}
void OnTick() {}
//+------------------------------------------------------------------+
