"""Rough MQL5 -> C++ syntax/type check: translate arrays to std::vector and stub the MQL5 API, then g++ -fsyntax-only."""
import re
import subprocess
import sys

src = open(sys.argv[1], encoding="utf-8").read()
src = re.sub(r"^#property.*$|^#include.*$", "", src, flags=re.M)
src = re.sub(r"^input\s+", "", src, flags=re.M)
src = re.sub(r"\bstring\b", "std::string", src)
T = r"(double|int|long|bool|datetime|std::string|ENUM_TIMEFRAMES|OBx|FVx|BRx|MqlRates)"
# params: const double &x[] / double &x[]
src = re.sub(r"(const\s+)?" + T + r"\s*&\s*(\w+)\[\]", lambda m: f"{m.group(1) or ''}std::vector<{m.group(2)}> &{m.group(3)}", src)
# declarations with initializer: double X[] = {...};
src = re.sub(T + r"\s+(\w+)\[\]\s*=", r"std::vector<\1> \2 =", src)


# declarations of dynamic arrays (possibly several): double a[], b[], c[];
def decl(m):
    typ, rest = m.group(1), m.group(2)
    names = [x.strip() for x in rest.split(",")]
    if all(re.fullmatch(r"\w+\[\]", n) for n in names):
        return f"std::vector<{typ}> " + ", ".join(n[:-2] for n in names) + ";"
    return m.group(0)


src = re.sub(T + r"\s+([^;=(){}]+\[\][^;=(){}]*);", decl, src)
prelude = r'''
#include <string>
#include <vector>
#include <cmath>
#include <cfloat>
typedef long datetime; typedef unsigned long ulong; typedef unsigned int uint;
enum ENUM_TIMEFRAMES { PERIOD_CURRENT, PERIOD_M1, PERIOD_M2, PERIOD_M3, PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4, PERIOD_D1 };
enum ENUM_ORDER_TYPE { ORDER_TYPE_BUY, ORDER_TYPE_SELL };
enum { POSITION_TYPE_BUY, POSITION_TYPE_SELL, POSITION_MAGIC, POSITION_TYPE, POSITION_PRICE_OPEN, POSITION_SL, POSITION_TP, POSITION_VOLUME, POSITION_SYMBOL,
 SYMBOL_TRADE_TICK_VALUE, SYMBOL_TRADE_TICK_SIZE, SYMBOL_VOLUME_STEP, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX, SYMBOL_BID, SYMBOL_ASK, SYMBOL_POINT,
 SYMBOL_TRADE_STOPS_LEVEL, SYMBOL_DIGITS, SYMBOL_SELECT, ACCOUNT_EQUITY, ACCOUNT_MARGIN_FREE, INIT_SUCCEEDED, INIT_FAILED };
#define EMPTY_VALUE DBL_MAX
struct MqlRates { datetime time; double open, high, low, close; long tick_volume; int spread; long real_volume; };
struct MqlDateTime { int year, mon, day, hour, min, sec, day_of_week, day_of_year; };
template<class X> int ArrayResize(std::vector<X>& a, int n) { a.resize(n); return n; }
template<class X> int ArraySize(const std::vector<X>& a) { return (int)a.size(); }
template<class X> int ArraySize(const X (&a)[2]) { return 2; }
template<class X, class Y> void ArrayInitialize(std::vector<X>& a, Y v) { for(auto& x : a) x = v; }
template<class X, size_t K> void ArrayInitialize(X (&a)[K], int v) { for(auto& x : a) x = v; }
template<class X> int ArrayCopy(std::vector<X>& a, const std::vector<X>& b) { a = b; return (int)a.size(); }
template<class X> bool ArraySetAsSeries(std::vector<X>& a, bool f) { return true; }
double MathMax(double a, double b); double MathMin(double a, double b); double MathAbs(double a); double MathSqrt(double a); double MathFloor(double a); double MathRound(double a);
double NormalizeDouble(double a, int d);
int CopyRates(std::string s, ENUM_TIMEFRAMES tf, int start, int count, std::vector<MqlRates>& r);
datetime iTime(std::string s, ENUM_TIMEFRAMES tf, int shift);
void TimeToStruct(datetime t, MqlDateTime& dt); datetime TimeGMT(); datetime TimeTradeServer();
double SymbolInfoDouble(std::string s, int p); long SymbolInfoInteger(std::string s, int p); bool SymbolSelect(std::string s, bool b);
double AccountInfoDouble(int p); bool OrderCalcMargin(ENUM_ORDER_TYPE t, std::string s, double l, double p, double& m);
int PositionsTotal(); ulong PositionGetTicket(int i); long PositionGetInteger(int p); double PositionGetDouble(int p); std::string PositionGetString(int p);
bool GlobalVariableCheck(std::string n); double GlobalVariableSet(std::string n, double v);
std::string IntegerToString(long v); std::string DoubleToString(double v, int d);
template<class... A> void PrintFormat(const char* f, A... a); template<class... A> void Print(A... a);
bool EventSetTimer(int s); void EventKillTimer();
struct CTrade { void SetExpertMagicNumber(long m); bool Buy(double, std::string, double, double, double, std::string); bool Sell(double, std::string, double, double, double, std::string);
 bool PositionClose(ulong t); bool PositionClosePartial(ulong t, double v); bool PositionModify(ulong t, double sl, double tp); uint ResultRetcode(); std::string ResultRetcodeDescription(); };
'''
open("/tmp/ea_check.cpp", "w").write(prelude + src)
r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-Wno-format", "/tmp/ea_check.cpp"], capture_output=True, text=True)
print(r.stderr[:6000] or "SYNTAX OK")
