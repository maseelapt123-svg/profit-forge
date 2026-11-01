"""Parity test: run the MQL5 signal code (translated to C++) on real candles and compare with the Python strategies."""
import subprocess
import sys

import numpy as np

sys.path.insert(0, "/app/backend")
import asyncio  # noqa: E402

import server  # noqa: E402
import strategies as S  # noqa: E402

sym, tf = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("BTC-USD", "1h")
df = asyncio.run(server.get_df(sym, tf, long=True)).iloc[-600:]
df = df.copy()
df["volume"] = 0.0  # MT CFDs usually have no real volume -> both sides use the typical-price mean
with open("/tmp/bars.csv", "w") as f:
    for t, r in df.iterrows():
        f.write(f"{int(t.timestamp())},{float(r.open)!r},{float(r.high)!r},{float(r.low)!r},{float(r.close)!r}\n")
subprocess.run([sys.executable, "/app/backend/tests/mql_check.py", "/tmp/full.mq5"], check=True, capture_output=True)
harness = r'''
#include <cstdio>
#include <fstream>
#include <sstream>
#include <iostream>
double MathMax(double a, double b){return a>b?a:b;} double MathMin(double a, double b){return a<b?a:b;} double MathAbs(double a){return std::fabs(a);}
double MathSqrt(double a){return std::sqrt(a);} double MathFloor(double a){return std::floor(a);} double MathRound(double a){return std::round(a);}
void TimeToStruct(datetime t, MqlDateTime& dt){ dt.hour = (int)((t % 86400) / 3600); }
double NormalizeDouble(double a, int d){return a;} int CopyRates(std::string, ENUM_TIMEFRAMES, int, int, std::vector<MqlRates>&){return 0;}
datetime iTime(std::string, ENUM_TIMEFRAMES, int){return 0;} datetime TimeGMT(){return 0;} datetime TimeTradeServer(){return 0;}
double SymbolInfoDouble(std::string, int){return 0;} long SymbolInfoInteger(std::string, int){return 0;} bool SymbolSelect(std::string, bool){return 0;}
double AccountInfoDouble(int){return 0;} bool OrderCalcMargin(ENUM_ORDER_TYPE, std::string, double, double, double&){return 0;}
int PositionsTotal(){return 0;} ulong PositionGetTicket(int){return 0;} long PositionGetInteger(int){return 0;} double PositionGetDouble(int){return 0;}
std::string PositionGetString(int){return "";} bool GlobalVariableCheck(std::string){return 0;} double GlobalVariableSet(std::string, double){return 0;}
std::string IntegerToString(long){return "";} std::string DoubleToString(double, int){return "";}
template<class... A> void PrintFormat(const char*, A...){} template<class... A> void Print(A...){}
bool EventSetTimer(int){return 0;} void EventKillTimer(){}
void CTrade::SetExpertMagicNumber(long){} bool CTrade::Buy(double, std::string, double, double, double, std::string){return 0;}
bool CTrade::Sell(double, std::string, double, double, double, std::string){return 0;} bool CTrade::PositionClose(ulong){return 0;}
bool CTrade::PositionClosePartial(ulong, double){return 0;} bool CTrade::PositionModify(ulong, double, double){return 0;}
uint CTrade::ResultRetcode(){return 0;} std::string CTrade::ResultRetcodeDescription(){return "";}
int main(){
  std::ifstream f("/tmp/bars.csv"); std::string line; std::vector<double> o,h,l,c; std::vector<long> t;
  while(std::getline(f,line)){ std::stringstream ss(line); std::string x; std::getline(ss,x,','); t.push_back(std::stol(x));
    std::getline(ss,x,','); o.push_back(std::stod(x)); std::getline(ss,x,','); h.push_back(std::stod(x)); std::getline(ss,x,','); l.push_back(std::stod(x)); std::getline(ss,x,','); c.push_back(std::stod(x)); }
  N = (int)c.size(); O=o; H=h; L=l; C=c; V.assign(N,0); T.assign(t.begin(), t.end()); SmcK=-1; SrvOffset=0;
  std::vector<std::string> names = { NAMES };
  for(auto& nm : names){ std::vector<double> s; SmcK=-1; Signals(nm, s); std::cout << nm; for(double v : s) std::cout << " " << (int)v; std::cout << "\n"; }
  for(int n : {12, 20}){ std::vector<double> u, d; Votes(n, u, d); std::cout << "votes" << n; for(int i=0;i<N;i++) std::cout << " " << (int)(u[i]-d[i]) ; std::cout << "\n"; }
}
'''
names = [s for s in S.STRATEGIES]
src = open("/tmp/ea_check.cpp").read() + harness.replace("NAMES", ",".join(f'"{n}"' for n in names))
open("/tmp/ea_run.cpp", "w").write(src)
r = subprocess.run(["g++", "-std=c++17", "-O1", "-w", "-o", "/tmp/ea_run", "/tmp/ea_run.cpp"], capture_output=True, text=True)
if r.returncode:
    print(r.stderr[:3000])
    sys.exit(1)
out = subprocess.run(["/tmp/ea_run"], capture_output=True, text=True).stdout.strip().split("\n")
mq = {ln.split()[0]: np.array([int(x) for x in ln.split()[1:]]) for ln in out}
import os, json
base = json.loads(json.dumps(S.PLUGIN_DEFAULTS))
if os.environ.get("ALL"):
    for v in base.values():
        v["enabled"] = True
plugins = {**base, "_conf": S.CONF_DEFAULT, "_c12": {"min": 10}, "_c20": {"min": 16}}
W = 300  # compare the last 300 bars (indicator warm-up differs slightly at the start)
bad = []
for n in names:
    py = S.strategy_signals(df, n, plugins).astype(int)
    a, b = py[-W:], mq[n][-W:]
    agree = (a == b).mean() * 100
    print(f"{n:<14} py={np.count_nonzero(a):>3} mq={np.count_nonzero(b):>3} match={agree:5.1f}%")
    if agree < 97:
        bad.append(n)
for n, fn in ((12, S.confirm12_matrix), (20, S.confirm20_matrix)):
    m = fn(df)
    py = ((m > 0).sum(1) - (m < 0).sum(1)).astype(int)[-W:]
    agree = (py == mq[f"votes{n}"][-W:]).mean() * 100
    print(f"votes{n:<9} match={agree:5.1f}%")
    if agree < 97:
        bad.append(f"votes{n}")
print("MISMATCH:", bad)
