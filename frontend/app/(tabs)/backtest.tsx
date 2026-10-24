import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money, pct } from "@/src/api";
import { LineChart } from "@/src/components/charts";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow, Segmented } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { CATEGORIES, Category } from "@/src/markets";

const STRATS = [
  { value: "smc", label: "Smart Money" },
  { value: "combo", label: "Combo plugins" },
  { value: "ema_cross", label: "EMA Cross" },
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
  { value: "bollinger", label: "Bollinger" },
];
const TFS = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];

type OptCand = { strategy: string; trend_filter: boolean; sl_atr: number; rr: number; train: Result["metrics"]; test: Result["metrics"] };
type OptResult = { best: OptCand | null; candidates: OptCand[]; tested: number; symbol: string; display: string; tf: string };
type Result = {
  metrics: { skipped_cost?: number; net_profit: number; return_pct: number; win_rate: number; profit_factor: number; max_drawdown: number; total_trades: number; avg_r: number; buy_hold_pct: number; final_equity: number };
  equity: number[];
  trades: { dir: string; entry: number; exit: number; pnl: number; r: number; reason: string; closed: string }[];
  display: string; from: string; to: string; bars: number; tf: string;
};

function Stepper({ label, value, step, min, max, onChange, testID, suffix = "" }: {
  label: string; value: number; step: number; min: number; max: number; onChange: (v: number) => void; testID: string; suffix?: string;
}) {
  const styles = useStyles();
  const set = (v: number) => onChange(Math.round(Math.min(max, Math.max(min, v)) * 10) / 10);
  return (
    <View style={styles.stepper}>
      <Text style={styles.stepLabel}>{label}</Text>
      <View style={styles.stepRow}>
        <Pressable testID={`${testID}-minus`} style={styles.stepBtn} onPress={() => set(value - step)}>
          <Text style={styles.stepBtnText}>−</Text>
        </Pressable>
        <Text style={styles.stepValue} testID={`${testID}-value`}>
          {value}
          {suffix}
        </Text>
        <Pressable testID={`${testID}-plus`} style={styles.stepBtn} onPress={() => set(value + step)}>
          <Text style={styles.stepBtnText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function Backtest() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const styles = useStyles();
  const { colors } = useTheme();
  const [cat, setCat] = useState<Category>("crypto");
  const [symbol, setSymbol] = useState("BTC-USD");
  const [strategy, setStrategy] = useState("smc");
  const [tf, setTf] = useState("1h");
  const [slAtr, setSlAtr] = useState(1.5);
  const [rr, setRr] = useState(2);
  const [risk, setRisk] = useState(1);
  const [trendFilter, setTrendFilter] = useState(true);
  const [breakeven, setBreakeven] = useState(true);
  const toast = useToast();
  const qc = useQueryClient();
  const assets = useQuery({ queryKey: ["markets", cat], queryFn: () => api<{ symbol: string; display: string }[]>(`/markets?category=${cat}`) });
  const run = useMutation({
    mutationFn: () => api<Result>("/backtest", { method: "POST", body: { symbol, tf, strategy, sl_atr: slAtr, rr, risk_pct: risk, trend_filter: trendFilter, breakeven } }),
  });
  const opt = useMutation({ mutationFn: () => api<OptResult>("/optimize", { method: "POST", body: { symbol, tf } }) });
  const applyBest = (b: OptCand) => {
    setStrategy(b.strategy);
    setSlAtr(b.sl_atr);
    setRr(b.rr);
    setTrendFilter(b.trend_filter);
    setBreakeven(true);
    setTimeout(() => run.mutate(), 0);
  };
  const sendToBot = async (b: OptCand) => {
    try {
      const cur = await api<{ bot: any }>("/bot");
      const sym = opt.data!.symbol;
      const symbols = Array.from(new Set([...(cur.bot.symbols ?? []), sym]));
      const overrides = { ...(cur.bot.overrides ?? {}), [sym]: { tf: opt.data!.tf, strategy: b.strategy, sl_atr: b.sl_atr, rr: b.rr, trend_filter: b.trend_filter } };
      await api("/bot", { method: "PUT", body: { ...cur.bot, symbols, overrides } });
      qc.invalidateQueries({ queryKey: ["bot"] });
      toast(`Robô: ${opt.data!.display} ${opt.data!.tf.toUpperCase()} usa esta configuração`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const ob = opt.data?.best;
  const { reset: resetOpt } = opt;
  useEffect(() => {
    resetOpt();
  }, [symbol, tf, resetOpt]);
  const r = run.data;
  const m = r?.metrics;

  return (
    <View style={styles.root} testID="backtest-screen">
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <Text style={styles.title}>Backtest</Text>
        <Text style={styles.subtitle}>Testa estratégias em dados históricos reais</Text>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <Text style={styles.section}>Estratégia</Text>
        <ChipRow options={STRATS} value={strategy} onChange={setStrategy} testID="bt-strategy" />
        <View style={{ paddingHorizontal: 16 }}>
          <Segmented
            options={CATEGORIES}
            value={cat}
            onChange={(v) => {
              setCat(v);
              setSymbol({ crypto: "BTC-USD", forex: "EURUSD=X", stocks: "AAPL" }[v]);
            }}
            testID="bt-category"
          />
        </View>
        <ChipRow options={(assets.data ?? []).map((a) => ({ value: a.symbol, label: a.display }))} value={symbol} onChange={setSymbol} testID="bt-asset" />
        <Text style={styles.section}>Timeframe</Text>
        <ChipRow options={TFS} value={tf} onChange={setTf} testID="bt-tf" />
        <ChipRow
          options={[
            { value: "trend", label: "Filtro de tendência EMA200" },
            { value: "be", label: "Break-even a 1R" },
          ]}
          value={[...(trendFilter ? ["trend"] : []), ...(breakeven ? ["be"] : [])]}
          onChange={(v) => (v === "trend" ? setTrendFilter((x) => !x) : setBreakeven((x) => !x))}
          testID="bt-options"
        />
        <View style={styles.steppers}>
          <Stepper label="Stop (ATR)" value={slAtr} step={0.5} min={0.5} max={5} onChange={setSlAtr} testID="bt-sl" suffix="x" />
          <Stepper label="Risco:Retorno" value={rr} step={0.5} min={0.5} max={6} onChange={setRr} testID="bt-rr" />
          <Stepper label="Risco/trade" value={risk} step={0.5} min={0.5} max={5} onChange={setRisk} testID="bt-risk" suffix="%" />
        </View>

        {opt.isPending && <Text style={styles.empty}>A testar ~130 combinações (treino 70% / teste 30%)…</Text>}
        {opt.isError && <Text style={styles.error}>{(opt.error as Error).message}</Text>}
        {opt.data && (
          <Animated.View entering={FadeInDown} style={[styles.card, styles.optCard]} testID="opt-results">
            <Text style={styles.optTitle}>
              Otimizador · {opt.data.display} {opt.data.tf.toUpperCase()} · {opt.data.tested} combinações
            </Text>
            {ob ? (
              <>
                <Text style={styles.optBest} testID="opt-best">
                  {STRATS.find((x) => x.value === ob.strategy)?.label} · Stop {ob.sl_atr}x ATR · R:R {ob.rr}
                  {ob.trend_filter ? " · c/ filtro" : ""}
                </Text>
                <View style={styles.optRow}>
                  <Text style={styles.cardLabel}>Treino: {pct(ob.train.return_pct)} · PF {fmt(ob.train.profit_factor, 2)}</Text>
                  <Text style={[styles.cardLabel, { color: ob.test.return_pct >= 0 ? colors.success : colors.error }]}>
                    Teste (dados não vistos): {pct(ob.test.return_pct)} · {ob.test.total_trades} trades
                  </Text>
                </View>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button label="Aplicar" variant="ghost" style={{ flex: 1, height: 44 }} onPress={() => applyBest(ob)} testID="opt-apply-button" />
                  <Button label="Usar no Robô" style={{ flex: 1, height: 44 }} onPress={() => sendToBot(ob)} testID="opt-bot-button" />
                </View>
              </>
            ) : (
              <Text style={styles.note} testID="opt-none">
                Nenhuma configuração foi lucrativa em treino E teste para este ativo/timeframe. Experimenta um timeframe maior ou outro ativo — não operes esta combinação.
              </Text>
            )}
          </Animated.View>
        )}
        {run.isError && (
          <Text style={styles.error} testID="bt-error">
            {(run.error as Error).message}
          </Text>
        )}
        {!r && !run.isPending && !run.isError && <Text style={styles.empty}>Escolhe os parâmetros e executa o backtest.</Text>}
        {r && m && (
          <Animated.View entering={FadeInDown} style={{ paddingHorizontal: 16, gap: 12 }} testID="bt-results">
            <View style={styles.card}>
              <Text style={styles.cardLabel}>
                {r.display} · {r.tf.toUpperCase()} · {r.bars} velas
              </Text>
              <Text style={[styles.big, { color: m.return_pct >= 0 ? colors.success : colors.error }]} testID="bt-return">
                {pct(m.return_pct)}
              </Text>
              <Text style={styles.cardLabel}>
                {money(m.net_profit)} · Buy & Hold {pct(m.buy_hold_pct)}
              </Text>
              <LineChart data={r.equity} height={160} testID="bt-equity-chart" baseline={10000} />
            </View>
            <View style={styles.grid}>
              <Metric label="Taxa de acerto" value={`${fmt(m.win_rate, 1)}%`} testID="bt-winrate" />
              <Metric label="Profit factor" value={fmt(m.profit_factor, 2)} testID="bt-pf" good={m.profit_factor >= 1} />
              <Metric label="Drawdown máx." value={`${fmt(m.max_drawdown, 1)}%`} testID="bt-dd" good={false} />
              <Metric label="Total trades" value={String(m.total_trades)} testID="bt-trades" />
              <Metric label="Média R" value={fmt(m.avg_r, 2)} testID="bt-avgr" good={m.avg_r >= 0} />
              <Metric label="Capital final" value={money(m.final_equity)} testID="bt-final" />
            </View>
            {!!m.skipped_cost && (
              <Text style={styles.note} testID="bt-skipped-note">
                {m.skipped_cost} sinais ignorados: o stop ficava demasiado curto face às comissões/spread. Aumenta o Stop (ATR) ou usa um timeframe maior.
              </Text>
            )}
            {m.return_pct < m.buy_hold_pct && (
              <Text style={styles.note}>Esta configuração ficou abaixo do Buy & Hold. Ajusta parâmetros ou experimenta outra estratégia.</Text>
            )}
            <Text style={styles.section2}>Últimas operações</Text>
            {r.trades.slice(0, 15).map((t, i) => (
              <View key={i} style={styles.tradeRow}>
                <Text style={[styles.tradeDir, { color: t.dir === "BUY" ? colors.success : colors.error }]}>{t.dir === "BUY" ? "LONG" : "SHORT"}</Text>
                <Text style={styles.tradeMeta}>
                  {new Date(t.closed).toLocaleDateString("pt-PT")} · {t.reason}
                </Text>
                <Text style={[styles.tradePnl, { color: t.pnl >= 0 ? colors.success : colors.error }]}>
                  {t.pnl >= 0 ? "+" : ""}
                  {fmt(t.pnl, 2)}
                </Text>
              </View>
            ))}
          </Animated.View>
        )}
      </ScrollView>
      <View style={[styles.sticky, { paddingBottom: bottomChrome + 12 }]}>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Button label="Otimizar" variant="ghost" loading={opt.isPending} onPress={() => opt.mutate()} testID="bt-optimize-button" style={{ flex: 1 }} />
          <Button label={run.isPending ? "A simular…" : "Executar Backtest"} loading={run.isPending} onPress={() => run.mutate()} testID="bt-run-button" style={{ flex: 1.6 }} />
        </View>
      </View>
    </View>
  );
}

function Metric({ label, value, testID, good }: { label: string; value: string; testID: string; good?: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.metric}>
      <Text style={styles.cardLabel}>{label}</Text>
      <Text style={[styles.metricValue, good === true && { color: colors.success }, good === false && label.includes("Drawdown") && { color: colors.error }]} testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: 16, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 32 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", paddingHorizontal: 16, marginTop: 16 },
  section2: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8 },
  steppers: { flexDirection: "row", gap: 8, paddingHorizontal: 16, marginTop: 8, marginBottom: 16 },
  stepper: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8, gap: 4 },
  stepLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11, textAlign: "center" },
  stepRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  stepValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  empty: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 14, textAlign: "center", padding: 24 },
  error: { color: c.error, fontFamily: fonts.text, fontSize: 14, textAlign: "center", padding: 16 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16, gap: 4 },
  cardLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  big: { fontFamily: fonts.display, fontSize: 40 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  metric: { width: "48.5%", backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12 },
  metricValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  note: { color: c.warning, fontFamily: fonts.text, fontSize: 13 },
  tradeRow: { flexDirection: "row", alignItems: "center", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.divider, gap: 8 },
  tradeDir: { fontFamily: fonts.display, fontSize: 14, width: 52 },
  tradeMeta: { flex: 1, color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 12 },
  tradePnl: { fontFamily: fonts.display, fontSize: 15 },
  optCard: { marginHorizontal: 16, marginBottom: 12, borderColor: c.brandSecondary, gap: 8 },
  optTitle: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase" },
  optBest: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  optRow: { gap: 2 },
  sticky: { paddingHorizontal: 16, paddingTop: 12, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surface },
}));
