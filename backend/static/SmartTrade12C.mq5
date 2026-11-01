//+------------------------------------------------------------------+
//| SmartTrade12C.mq5 — Expert Advisor "12 Confirmações" (SmartTrade AI)
//| Entra só quando >= MinConfirm das 12 confirmações concordam (na vela fechada),
//| com tendência do timeframe superior, risco % do capital, TP parcial e break-even.
//| Compilar no MetaEditor (F7) para gerar o .ex5. Testar SEMPRE primeiro em conta demo.
//+------------------------------------------------------------------+
#property copyright "SmartTrade AI"
#property version   "1.00"
#include <Trade/Trade.mqh>

input double RiskPercent   = 1.0;      // Risco por trade (% do capital)
input int    MinConfirm    = 10;       // Mínimo de confirmações (6–12)
input double RR            = 2.0;      // Risco:Retorno (TP = SL x RR)
input double SL_ATR        = 1.5;      // Stop = ATR(14) x este valor
input double PartialPct    = 50.0;     // % a fechar no alvo parcial (0 = desligado)
input double PartialR      = 1.0;      // Alvo parcial em R
input int    MaxPositions  = 30;       // Máx. posições abertas deste EA
input bool   UseHTF        = true;     // Exigir tendência do TF superior (EMA200)
input ENUM_TIMEFRAMES HTF  = PERIOD_H4;// Timeframe superior
input long   Magic         = 120012;   // Número mágico

CTrade trade;
int hE200, hE21, hE50, hMACD, hRSI, hADX, hATR, hICH, hSAR, hHTF;
datetime lastBar = 0;

double Buf(int h, int buffer, int shift) { double v[1]; if(CopyBuffer(h, buffer, shift, 1, v) != 1) return EMPTY_VALUE; return v[0]; }

int OnInit() {
   hE200 = iMA(_Symbol, _Period, 200, 0, MODE_EMA, PRICE_CLOSE);
   hE21  = iMA(_Symbol, _Period, 21, 0, MODE_EMA, PRICE_CLOSE);
   hE50  = iMA(_Symbol, _Period, 50, 0, MODE_EMA, PRICE_CLOSE);
   hMACD = iMACD(_Symbol, _Period, 12, 26, 9, PRICE_CLOSE);
   hRSI  = iRSI(_Symbol, _Period, 14, PRICE_CLOSE);
   hADX  = iADX(_Symbol, _Period, 14);
   hATR  = iATR(_Symbol, _Period, 14);
   hICH  = iIchimoku(_Symbol, _Period, 9, 26, 52);
   hSAR  = iSAR(_Symbol, _Period, 0.02, 0.2);
   hHTF  = iMA(_Symbol, HTF, 200, 0, MODE_EMA, PRICE_CLOSE);
   if(hE200 == INVALID_HANDLE || hHTF == INVALID_HANDLE) return INIT_FAILED;
   trade.SetExpertMagicNumber(Magic);
   return INIT_SUCCEEDED;
}

int Sgn(double x) { return x > 0 ? 1 : (x < 0 ? -1 : 0); }

// Supertrend(10,3) direction at bar `s` (computed over the last 300 bars)
int SupertrendDir(int s) {
   int n = 300; double up = 0, dn = 0; int dir = 1;
   int hA = iATR(_Symbol, _Period, 10);
   for(int i = s + n; i >= s; i--) {
      double a = Buf(hA, 0, i); if(a == EMPTY_VALUE) continue;
      double hl2 = (iHigh(_Symbol, _Period, i) + iLow(_Symbol, _Period, i)) / 2.0, c = iClose(_Symbol, _Period, i), pc = iClose(_Symbol, _Period, i + 1);
      double ub = hl2 + 3 * a, lb = hl2 - 3 * a;
      double nu = (up == 0 || ub < up || pc > up) ? ub : up, nd = (dn == 0 || lb > dn || pc < dn) ? lb : dn;
      if(c > up && up != 0) dir = 1; else if(c < dn && dn != 0) dir = -1;
      up = nu; dn = nd;
   }
   return dir;
}

// The 12 confirmations on closed bar `s`: returns votes up/down
void Confirmations(int s, int &up, int &down) {
   up = 0; down = 0;
   double c = iClose(_Symbol, _Period, s), o = iOpen(_Symbol, _Period, s), h = iHigh(_Symbol, _Period, s), l = iLow(_Symbol, _Period, s);
   double e50 = Buf(hE50, 0, s), e50p = Buf(hE50, 0, s + 5);
   double macd = Buf(hMACD, 0, s), sig = Buf(hMACD, 1, s), rsi = Buf(hRSI, 0, s);
   double adx = Buf(hADX, 0, s), pdi = Buf(hADX, 1, s), ndi = Buf(hADX, 2, s);
   double sa = Buf(hICH, 2, s), sb = Buf(hICH, 3, s), sar = Buf(hSAR, 0, s);
   double tp = 0; for(int k = s; k < s + 20; k++) tp += (iHigh(_Symbol, _Period, k) + iLow(_Symbol, _Period, k) + iClose(_Symbol, _Period, k)) / 3.0; tp /= 20.0;
   int hi = iHighest(_Symbol, _Period, MODE_HIGH, 50, s + 1), lo = iLowest(_Symbol, _Period, MODE_LOW, 50, s + 1);
   double mid = (iHigh(_Symbol, _Period, hi) + iLow(_Symbol, _Period, lo)) / 2.0, pos = (h - l) > 0 ? (c - l) / (h - l) : 0.5;
   int v[12];
   v[0] = Sgn(c - Buf(hE200, 0, s));
   v[1] = Sgn(Buf(hE21, 0, s) - e50);
   v[2] = Sgn(e50 - e50p);
   v[3] = Sgn(macd - sig);
   v[4] = (rsi > 50 && rsi < 70) ? 1 : ((rsi < 50 && rsi > 30) ? -1 : 0);
   v[5] = adx > 20 ? Sgn(pdi - ndi) : 0;
   v[6] = SupertrendDir(s);
   v[7] = c > MathMax(sa, sb) ? 1 : (c < MathMin(sa, sb) ? -1 : 0);
   v[8] = Sgn(c - sar);
   v[9] = Sgn(c - mid);                       // estrutura (preço vs meio do range de 50 velas)
   v[10] = Sgn(c - tp);                       // preço vs VWAP aproximada (média do preço típico)
   v[11] = (c > o && pos >= 0.7) ? 1 : ((c < o && pos <= 0.3) ? -1 : 0);
   for(int i = 0; i < 12; i++) { if(v[i] > 0) up++; else if(v[i] < 0) down++; }
}

int MyPositions() {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) if(PositionGetTicket(i) && PositionGetInteger(POSITION_MAGIC) == Magic) n++;
   return n;
}

double LotsForRisk(double slDist, ENUM_ORDER_TYPE type, double price) {
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tv <= 0 || ts <= 0 || slDist <= 0) return 0;
   double risk = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0;
   double lots = MathFloor(risk / (slDist / ts * tv) / step) * step;
   // margin check: never use more than the free margin (respects the account leverage, e.g. 1:500)
   double margin = 0;
   while(lots >= vmin && OrderCalcMargin(type, _Symbol, lots, price, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.9) lots -= step;
   if(lots < vmin) return 0;
   return MathMin(lots, vmax);
}

void ManagePositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong t = PositionGetTicket(i);
      if(!t || PositionGetInteger(POSITION_MAGIC) != Magic) continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tpv = PositionGetDouble(POSITION_TP), vol = PositionGetDouble(POSITION_VOLUME);
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      if(sl == 0 || MathAbs(sl - open) < _Point) continue;   // already at break-even
      double r = MathAbs(open - sl), px = buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      bool lossSide = buy ? sl < open : sl > open;
      if(!lossSide) continue;
      if((buy && px >= open + r * PartialR) || (!buy && px <= open - r * PartialR)) {
         double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), part = MathFloor(vol * PartialPct / 100.0 / step) * step;
         if(PartialPct > 0 && part >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN) && part < vol) trade.PositionClosePartial(t, part);
         trade.PositionModify(t, open, tpv);                    // stop to break-even
      }
   }
}

void OnTick() {
   ManagePositions();
   datetime bar = iTime(_Symbol, _Period, 0);
   if(bar == lastBar) return;
   lastBar = bar;
   int up, dn, pu, pd;
   Confirmations(1, up, dn);
   Confirmations(2, pu, pd);
   int s = (up >= MinConfirm && pu < MinConfirm) ? 1 : ((dn >= MinConfirm && pd < MinConfirm) ? -1 : 0);
   if(s == 0 || MyPositions() >= MaxPositions) return;
   if(UseHTF && Sgn(iClose(_Symbol, HTF, 1) - Buf(hHTF, 0, 1)) != s) return;
   double atr = Buf(hATR, 0, 1); if(atr == EMPTY_VALUE || atr <= 0) return;
   double slDist = atr * SL_ATR;
   ENUM_ORDER_TYPE type = s > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price = s > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double lots = LotsForRisk(slDist, type, price);
   if(lots <= 0) { Print("12C: margem/risco insuficiente para abrir"); return; }
   double sl = NormalizeDouble(price - s * slDist, _Digits), tp = NormalizeDouble(price + s * slDist * RR, _Digits);
   string cmt = StringFormat("12C %d/12", s > 0 ? up : dn);
   if(s > 0) trade.Buy(lots, _Symbol, price, sl, tp, cmt); else trade.Sell(lots, _Symbol, price, sl, tp, cmt);
}
//+------------------------------------------------------------------+
