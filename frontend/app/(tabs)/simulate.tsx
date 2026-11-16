import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money } from "@/src/api";
import { MarketScan } from "@/src/components/market-scan";
import { MtSim } from "@/src/components/mt-sim";
import { NegOptimize } from "@/src/components/neg-optimize";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow, haptic } from "@/src/components/ui";
import { STRATS } from "@/src/strategies";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Setup = { symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean };
type BotCfg = {
  symbols: string[]; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean; setups?: Setup[];
  c12_tf: string; c12_min: number; c20_tf: string; c20_min: number; c20_rr: number; ptp_enabled: boolean; ptp_pct: number;
  c20_pairs?: { symbol: string; tf: string; rr: number; min: number; enabled: boolean }[];
  c12_pairs?: { symbol: string; tf: string; rr: number; min: number; enabled: boolean }[];
};
type St = {
  trades: number; wins: number; winrate: number; r: number; pnl: number; pct: number; final: number; max_dd: number; pnl_simple: number;
  avg_daily_pct: number; avg_trading_day_pct: number; trading_days: number; best_day_pct: number; worst_day_pct: number;
};
type Row = { kind: string; symbol: string; tf: string; label: string; strategy: string; rr: number; error?: string; no_ai?: St; ai_eval?: St; with_ai?: St };
type Job = {
  status: "running" | "done"; current: string | null; step: number; steps: number; ai: boolean; ai_total: number; ai_done: number;
  ai_capped: boolean; rows: Row[]; total?: { no_ai: St; ai_eval?: St; with_ai?: St }; error?: string; days: number; days_covered?: number;
};
type Item = { id: string; kind: "setup" | "c12" | "c20"; symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean; min: number; title: string };

const disp = (s: string) => s.replace("=X", "").replace("-USD", "/USD");
const stratLabel = (v: string) => STRATS.find((x) => x.value === v)?.label ?? v;

export default function Simulate() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const bot = useQuery({ queryKey: ["bot"], queryFn: () => api<{ bot: BotCfg }>("/bot") });
  const [capital, setCapital] = useState(10000);
  const [risk, setRisk] = useState(1);
  const [days, setDays] = useState("30");
  const [partial, setPartial] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [sel, setSel] = useState<string[] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const params = useLocalSearchParams<{ mode?: string }>();
  const [mode, setMode] = useState<"bot" | "b2" | "mt" | "scan">(params.mode === "b2" ? "b2" : "bot");
  useEffect(() => {
    if (params.mode === "b2") setMode("b2");
  }, [params.mode]);
  const bot2 = useQuery({ queryKey: ["bot2"], queryFn: () => api<{ bot: { setups: BotCfg["setups"] } }>("/bot2"), enabled: mode === "b2" });
  useEffect(() => {  // each mode has its own selection and result
    setSel(null);
    setJobId(null);
  }, [mode]);

  const items = useMemo<Item[]>(() => {
    const b = bot.data?.bot;
    if (mode === "b2")
      return (bot2.data?.bot.setups ?? []).map((s) => ({ id: `setup|${s.symbol}|${s.tf}|${s.strategy}`, kind: "setup" as const, ...s, min: 10, title: `${disp(s.symbol)} ${s.tf.toUpperCase()} · ${stratLabel(s.strategy)}` }));
    if (!b) return [];
    const out: Item[] = [];
    const setups = b.setups?.length
      ? b.setups
      : b.symbols.map((s) => ({ symbol: s, tf: b.tf, strategy: b.strategy, sl_atr: b.sl_atr, rr: b.rr, trend_filter: b.trend_filter, mtf: b.mtf }));
    setups.forEach((s) =>
      out.push({ id: `setup|${s.symbol}|${s.tf}|${s.strategy}`, kind: "setup", ...s, min: 10, title: `${disp(s.symbol)} ${s.tf.toUpperCase()} · ${stratLabel(s.strategy)}` }),
    );
    b.symbols.forEach((s) => {
      const p = b.c20_pairs?.find((x) => x.symbol === s);
      const c20 = p ? { tf: p.tf, rr: p.rr, min: p.min } : { tf: b.c20_tf, rr: b.c20_rr, min: b.c20_min };
      const p12 = b.c12_pairs?.find((x) => x.symbol === s);
      const c12 = p12 ? { tf: p12.tf, rr: p12.rr, min: p12.min } : { tf: b.c12_tf, rr: b.rr, min: b.c12_min };
      if (!p12 || p12.enabled)
        out.push({ id: `c12|${s}`, kind: "c12", symbol: s, tf: c12.tf, strategy: "confirm12", sl_atr: b.sl_atr, rr: c12.rr, trend_filter: false, mtf: true, min: c12.min, title: `${disp(s)} ${c12.tf.toUpperCase()} · 12 Confirmações (1:${c12.rr}, ${c12.min}/12)` });
      if (!p || p.enabled)
        out.push({ id: `c20|${s}`, kind: "c20", symbol: s, tf: c20.tf, strategy: "confirm20", sl_atr: b.sl_atr, rr: c20.rr, trend_filter: false, mtf: true, min: c20.min, title: `${disp(s)} ${c20.tf.toUpperCase()} · Sniper 20 (1:${c20.rr}, ${c20.min}/20)` });
    });
    return out;
  }, [bot.data, bot2.data, mode]);
  useEffect(() => {
    if (bot.data && sel === null && (mode !== "b2" || bot2.data)) {
      setSel(items.filter((i) => i.kind === "setup").map((i) => i.id));
      setPartial(!!bot.data.bot.ptp_enabled);
    }
  }, [bot.data, bot2.data, items, sel, mode]);
  const chosen = items.filter((i) => sel?.includes(i.id));

  const start = useMutation({
    mutationFn: () =>
      api<{ job_id: string }>("/simulate", {
        method: "POST",
        body: {
          capital, risk_pct: risk, days: Number(days), ai: useAi, partial_pct: partial ? bot.data?.bot.ptp_pct ?? 50 : 0,
          items: chosen.map(({ kind, symbol, tf, strategy, sl_atr, rr, trend_filter, mtf, min }) => ({ kind, symbol, tf, strategy, sl_atr, rr, trend_filter, mtf, min })),
        },
      }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const job = useQuery({
    queryKey: ["simulate", jobId],
    queryFn: () => api<Job>(`/simulate/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "done" ? false : 2500),
  });
  const j = job.data;
  const running = start.isPending || (!!jobId && j?.status !== "done");
  const rowId = (r: Row) => (r.kind === "setup" ? `setup|${r.symbol}|${r.tf}|${r.strategy}` : `${r.kind}|${r.symbol}`);
  const negIds = j?.status === "done" ? j.rows.filter((r) => r.no_ai && r.no_ai.pnl < 0).map(rowId) : [];
  const removeNeg = useMutation({
    mutationFn: async () => {
      const neg = new Set(negIds);
      const path = mode === "b2" ? "/bot2" : "/bot";
      const cur = await api<{ bot: BotCfg }>(path);
      const setups = (cur.bot.setups ?? []).filter((s) => !neg.has(`setup|${s.symbol}|${s.tf}|${s.strategy}`));
      const removed = (cur.bot.setups ?? []).length - setups.length;
      if (removed) await api(path, { method: "PUT", body: { ...cur.bot, setups } });
      return { removed, neg };
    },
    onSuccess: ({ removed, neg }) => {
      haptic("medium");
      toast(`${removed} setup(s) negativo(s) retirado(s) do ${mode === "b2" ? "Robô 2" : "robô"}`, "success");
      qc.invalidateQueries({ queryKey: [mode === "b2" ? "bot2" : "bot"] });
      setSel((s) => (s ?? []).filter((x) => !neg.has(x)));
      setRerun(true);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const [rerun, setRerun] = useState(false);
  useEffect(() => {
    if (rerun && sel && sel.length) {
      setRerun(false);
      start.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerun, sel]);
  const toggle = (id: string) => setSel((s) => (s ?? []).includes(id) ? (s ?? []).filter((x) => x !== id) : [...(s ?? []), id]);
  const group = (k: Item["kind"]) => items.filter((i) => i.kind === k);

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="simulate-screen">
      <View style={styles.header}>
        <Text style={styles.title}>Simulação</Text>
        <Text style={styles.subtitle}>
          {mode === "scan" ? "Procura os pares e estratégias mais lucrativos de um mercado e envia-os para o Robô 2" : mode === "mt" ? "Quanto os dois robôs teriam feito na tua conta MetaTrader, com spreads e lotes reais" : "Calcula com juros compostos quanto as estratégias teriam feito no período, com e sem filtro IA"}
        </Text>
      </View>
      <ChipRow options={[{ value: "bot", label: "Robô 1" }, { value: "b2", label: "Robô 2" }, { value: "mt", label: "MetaTrader" }, { value: "scan", label: "Vários pares" }]} value={mode} onChange={setMode} testID="sim-mode" />
      {mode === "mt" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}>
          <MtSim />
        </ScrollView>
      ) : mode === "scan" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}>
          <MarketScan />
        </ScrollView>
      ) : (
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 32, gap: 8 }}>
        <View style={styles.steps}>
          <Num label="Capital" value={capital} step={capital <= 100 ? 10 : capital <= 1000 ? 100 : 1000} min={10} max={1000000} onChange={setCapital} testID="sim-capital" prefix="$" />
          <Num label="Risco/trade" value={risk} step={0.5} min={0.5} max={5} onChange={setRisk} testID="sim-risk" suffix="%" />
        </View>
        <Text style={styles.section}>Período</Text>
        <ChipRow options={[{ value: "7", label: "7 dias" }, { value: "30", label: "1 mês" }, { value: "90", label: "3 meses" }, { value: "180", label: "6 meses" }, { value: "365", label: "12 meses" }]} value={days} onChange={setDays} testID="sim-days" />
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleTitle}>Comparar com filtro IA</Text>
            <Text style={styles.muted}>A IA avalia até 150 entradas (as mais recentes) como faria no robô.</Text>
          </View>
          <Switch testID="sim-ai-switch" value={useAi} onValueChange={setUseAi} trackColor={{ true: colors.success, false: colors.surfaceTertiary }} thumbColor={colors.onBrandPrimary} />
        </View>
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleTitle}>Take profit parcial</Text>
            <Text style={styles.muted}>{bot.data?.bot.ptp_pct ?? 50}% fechado a 1R (2R no Sniper 20) e stop em break-even.</Text>
          </View>
          <Switch testID="sim-ptp-switch" value={partial} onValueChange={setPartial} trackColor={{ true: colors.success, false: colors.surfaceTertiary }} thumbColor={colors.onBrandPrimary} />
        </View>

        {!bot.data || (mode === "b2" && !bot2.data) ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 16 }} />
        ) : mode === "b2" && !items.length ? (
          <Text style={[styles.muted, { paddingHorizontal: 16 }]} testID="sim-b2-empty">
            O Robô 2 ainda não tem setups. Usa «Vários pares» para procurar os mais lucrativos e adicioná-los.
          </Text>
        ) : (
          (["setup", "c12", "c20"] as const).map((k) =>
            group(k).length ? (
              <View key={k} style={{ gap: 6 }}>
                <View style={styles.groupHead}>
                  <Text style={[styles.section, { flex: 1 }]}>{k === "setup" ? (mode === "b2" ? "Setups do Robô 2" : "Setups do robô") : k === "c12" ? "12 Confirmações" : "Sniper 20"}</Text>
                  <Pressable
                    testID={`sim-all-${k}`}
                    hitSlop={8}
                    style={styles.allBtn}
                    onPress={() => {
                      const ids = group(k).map((i) => i.id);
                      const all = ids.every((id) => sel?.includes(id));
                      setSel((s) => (all ? (s ?? []).filter((x) => !ids.includes(x)) : [...new Set([...(s ?? []), ...ids])]));
                    }}
                  >
                    <Text style={styles.allText}>{group(k).every((i) => sel?.includes(i.id)) ? "Limpar" : "Todos"}</Text>
                  </Pressable>
                </View>
                {group(k).map((i) => {
                  const on = !!sel?.includes(i.id);
                  return (
                    <Pressable key={i.id} onPress={() => toggle(i.id)} style={[styles.item, on && { borderColor: colors.brandPrimary }]} testID={`sim-item-${i.id}`}>
                      <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.brandPrimary : colors.muted} />
                      <Text style={styles.itemText} numberOfLines={2}>{i.title}</Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : null,
          )
        )}

        <View style={{ paddingHorizontal: 16, marginTop: 8 }}>
          <Button label={running ? "A simular…" : `Simular (${chosen.length})`} onPress={() => start.mutate()} loading={running} disabled={!chosen.length} testID="sim-run-button" />
        </View>

        {running && j && (
          <Text style={[styles.muted, { paddingHorizontal: 16 }]} testID="sim-progress">
            {j.current === "Filtro IA" ? `Filtro IA: ${j.ai_done}/${j.ai_total} entradas avaliadas` : `${j.current ?? "…"} · ${j.step}/${j.steps}`}
          </Text>
        )}
        {j?.status === "done" && j.total && <Results j={j} />}
        {j?.status === "done" && negIds.length > 0 && mode !== "b2" && (
          <NegOptimize
            key={jobId ?? ""}
            items={items.filter((i) => negIds.includes(i.id) && i.kind !== "c12")}
            onApplied={() => qc.invalidateQueries({ queryKey: ["bot"] })}
          />
        )}
        {j?.status === "done" && negIds.length > 0 && (
          <View style={{ paddingHorizontal: 16, gap: 6 }}>
            <Button
              label={`Retirar negativos (${negIds.length})`}
              variant="ghost"
              onPress={() => removeNeg.mutate()}
              loading={removeNeg.isPending}
              testID="sim-remove-negatives"
            />
            <Text style={styles.muted}>Remove do robô os setups com resultado negativo, desmarca-os aqui e volta a simular.</Text>
          </View>
        )}
        {j?.error && <Text style={[styles.muted, { paddingHorizontal: 16, color: colors.error }]}>{j.error}</Text>}
      </ScrollView>
      )}
    </View>
  );
}

function Results({ j }: { j: Job }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const t = j.total!;
  const col = (v: number) => (v >= 0 ? colors.success : colors.error);
  return (
    <View style={{ gap: 8 }} testID="sim-results">
      <Text style={styles.section}>Resultado</Text>
      {j.days_covered != null && j.days_covered < j.days && (
        <Text style={[styles.muted, { paddingHorizontal: 16 }]} testID="sim-coverage-note">
          Os dados disponíveis cobrem {j.days_covered} dias (timeframes curtos têm menos histórico); a média diária usa esse período.
        </Text>
      )}
      <View style={styles.steps}>
        <Card title="Sem filtro IA" s={t.no_ai} testID="sim-total-no-ai" />
        {j.ai && t.with_ai && <Card title="Com filtro IA" s={t.with_ai} testID="sim-total-ai" highlight />}
      </View>
      {j.ai && t.ai_eval && (
        <Text style={[styles.muted, { paddingHorizontal: 16 }]} testID="sim-ai-note">
          Nas {t.ai_eval.trades} entradas avaliadas pela IA: sem filtro {money(t.ai_eval.pnl)} ({fmt(t.ai_eval.winrate, 0)}% acerto) → com filtro {money(t.with_ai!.pnl)} ({fmt(t.with_ai!.winrate, 0)}% acerto, {t.with_ai!.trades} aprovadas).
          {j.ai_capped ? " Só as 150 entradas mais recentes foram avaliadas pela IA." : ""}
        </Text>
      )}
      <Text style={styles.section}>Por estratégia</Text>
      {j.rows.map((r, i) => (
        <View key={i} style={styles.rowCard} testID={`sim-row-${i}`}>
          <Text style={styles.itemText}>
            {r.label} · {r.kind === "setup" ? stratLabel(r.strategy) : r.strategy}
          </Text>
          {r.error ? (
            <Text style={styles.muted}>{r.error}</Text>
          ) : (
            <View style={{ flexDirection: "row", gap: 12 }}>
              <Line label="Sem IA" s={r.no_ai!} color={col(r.no_ai!.pnl)} />
              {j.ai && r.with_ai && <Line label="Com IA" s={r.with_ai} color={col(r.with_ai.pnl)} />}
            </View>
          )}
        </View>
      ))}
      <Text style={[styles.muted, { paddingHorizontal: 16 }]}>
        Juros compostos diários: o resultado de cada dia aplica-se ao capital do início desse dia. Setups otimizados com dados recentes tendem a parecer melhores nesse mesmo período do que vão ser no futuro. Resultados passados não garantem resultados futuros.
      </Text>
    </View>
  );
}

function Card({ title, s, testID, highlight }: { title: string; s: St; testID: string; highlight?: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={[styles.card, highlight && { borderColor: colors.brandPrimary }]} testID={testID}>
      <Text style={styles.muted}>{title}</Text>
      <Text style={[styles.big, { color: s.pnl >= 0 ? colors.success : colors.error }]} numberOfLines={1} adjustsFontSizeToFit>
        {money(s.pnl)}
      </Text>
      <Text style={styles.muted}>
        {s.pct >= 0 ? "+" : ""}{fmt(s.pct, 1)}% · {s.trades} ops · {fmt(s.winrate, 0)}% acerto
      </Text>
      <Text style={styles.muted}>Final {money(s.final)} · DD máx. {fmt(s.max_dd, 1)}%</Text>
      <Text style={[styles.daily, { color: s.avg_daily_pct >= 0 ? colors.success : colors.error }]} testID={`${testID}-daily`}>
        Média diária {s.avg_daily_pct >= 0 ? "+" : ""}{fmt(s.avg_daily_pct, 2)}%
      </Text>
      <Text style={styles.muted}>
        {s.trading_days} dias com operações · média {fmt(s.avg_trading_day_pct, 2)}%/dia · melhor {fmt(s.best_day_pct, 1)}% · pior {fmt(s.worst_day_pct, 1)}%
      </Text>
      <Text style={styles.muted}>Sem juros compostos: {money(s.pnl_simple)}</Text>
    </View>
  );
}

function Line({ label, s, color }: { label: string; s: St; color: string }) {
  const styles = useStyles();
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.muted}>{label}</Text>
      <Text style={[styles.lineVal, { color }]}>{money(s.pnl)}</Text>
      <Text style={styles.muted}>{s.trades} ops · {fmt(s.winrate, 0)}% · {fmt(s.avg_daily_pct, 2)}%/dia</Text>
    </View>
  );
}

function Num({ label, value, step, min, max, onChange, testID, suffix = "", prefix = "" }: {
  label: string; value: number; step: number; min: number; max: number; onChange: (v: number) => void; testID: string; suffix?: string; prefix?: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const set = (v: number) => onChange(Math.round(Math.min(max, Math.max(min, v)) * 10) / 10);
  return (
    <View style={styles.card}>
      <Text style={styles.muted}>{label}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Pressable onPress={() => set(value - step)} style={styles.stepBtn} testID={`${testID}-minus`}>
          <Ionicons name="remove" size={18} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.lineVal} testID={`${testID}-value`}>{prefix}{value.toLocaleString("pt-PT")}{suffix}</Text>
        <Pressable onPress={() => set(value + step)} style={styles.stepBtn} testID={`${testID}-plus`}>
          <Ionicons name="add" size={18} color={colors.onSurface} />
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8, gap: 2 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 28 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 13 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8, paddingHorizontal: 16 },
  groupHead: { flexDirection: "row", alignItems: "center", paddingRight: 16 },
  allBtn: { height: 36, paddingHorizontal: 12, justifyContent: "center", marginTop: 8 },
  allText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 14 },
  steps: { flexDirection: "row", gap: 8, paddingHorizontal: 16 },
  card: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 4 },
  big: { fontFamily: fonts.display, fontSize: 22 },
  daily: { fontFamily: fonts.display, fontSize: 15 },
  stepBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  lineVal: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12 },
  toggleTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 15 },
  item: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, paddingHorizontal: 12, minHeight: 52 },
  itemText: { flex: 1, color: c.onSurface, fontFamily: fonts.text, fontSize: 13 },
  rowCard: { marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 8 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));
