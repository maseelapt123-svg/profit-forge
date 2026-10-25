import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money } from "@/src/api";
import { CandleChart, Candle } from "@/src/components/charts";
import { useToast } from "@/src/components/toast";
import { ChipRow, PressableScale, Segmented, haptic } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Source = "otc" | "real";
type Pair = { pair: string; display: string; price: number; decimals: number; change_pct: number; open: boolean };
type Chart = { pair: string; display: string; price: number; decimals: number; payout: number; open: boolean; server_ts: number; candles: Candle[] };
type RuleStat = { rule: string; label: string; winrate: number; samples: number; wins: number; losses: number; fires: number };
type Sig = { pair: string; display: string; signal: "CALL" | "PUT" | null; best: RuleStat | null; rules: RuleStat[]; breakeven: number; payout: number; open: boolean };
type Trade = {
  trade_id: string; display: string; direction: "CALL" | "PUT"; amount: number; payout: number; expiry: number; entry_price: number;
  expires_ts: number; status: string; profit?: number; current_price?: number; winning?: boolean; decimals: number; origin: string;
};
type Trades = { open: Trade[]; closed: Trade[]; server_ts: number; balance: number; stats: { trades: number; wins: number; winrate: number; profit: number } };

const AMOUNTS = [5, 10, 25, 50, 100];

export default function Hfx() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [source, setSource] = useState<Source>("otc");
  const [pair, setPair] = useState("EURUSD=X");
  const [expiry, setExpiry] = useState<"1" | "3">("1");
  const [amount, setAmount] = useState(10);
  const [now, setNow] = useState(Date.now() / 1000);
  const [focused, setFocused] = useState(true);
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  const pairs = useQuery({ queryKey: ["hfx-pairs", source], queryFn: () => api<Pair[]>(`/hfx/pairs?source=${source}`), refetchInterval: focused ? 15000 : false });
  const chart = useQuery({
    queryKey: ["hfx-chart", pair, source],
    queryFn: () => api<Chart>(`/hfx/candles?pair=${encodeURIComponent(pair)}&source=${source}`),
    refetchInterval: focused ? (source === "otc" ? 2000 : 15000) : false,
  });
  const sigs = useQuery({ queryKey: ["hfx-signals", source, expiry], queryFn: () => api<Sig[]>(`/hfx/signals?source=${source}&expiry=${expiry}`), refetchInterval: focused ? 10000 : false });
  const trades = useQuery({ queryKey: ["hfx-trades"], queryFn: () => api<Trades>("/hfx/trades"), refetchInterval: focused ? 2000 : false });

  const place = useMutation({
    mutationFn: (direction: "CALL" | "PUT") => api<Trade>("/hfx/trade", { method: "POST", body: { pair, source, direction, amount, expiry: Number(expiry) } }),
    onSuccess: (t) => {
      haptic("heavy");
      toast(`${t.direction === "CALL" ? "SOBE" : "DESCE"} ${money(t.amount)} · expira em ${t.expiry} min`, "success");
      qc.invalidateQueries({ queryKey: ["hfx-trades"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const c = chart.data;
  const offset = trades.data ? trades.data.server_ts - Date.now() / 1000 : 0;
  const secsToCandle = 60 - (Math.floor(now + offset) % 60);
  const sel = sigs.data?.find((s) => s.pair === pair);
  const payout = c?.payout ?? (source === "otc" ? 0.85 : 0.82);
  const st = trades.data?.stats;

  return (
    <View style={styles.root} testID="hfx-screen">
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View style={styles.titleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>HFX</Text>
            <Text style={styles.subtitle}>Sobe/Desce a 1 e 3 minutos · conta simulada</Text>
          </View>
          <Pressable testID="open-hfx-bot-button" style={styles.botBtn} onPress={() => router.push("/hfx-bot")}>
            <Ionicons name="hardware-chip" size={18} color={colors.brandPrimary} />
            <Text style={styles.botBtnText}>Robô HFX</Text>
          </Pressable>
        </View>
        <View style={{ marginTop: 12 }}>
          <Segmented
            options={[
              { value: "otc", label: "OTC 24/7 (simulado)" },
              { value: "real", label: "Forex real" },
            ]}
            value={source}
            onChange={setSource}
            testID="hfx-source"
          />
        </View>
      </View>
      <View style={styles.quick}>
        <Pressable testID="open-hfx-optimizer-button" style={[styles.quickBtn, styles.quickMain]} onPress={() => router.push("/hfx-optimizer")}>
          <Ionicons name="trophy" size={16} color={colors.onBrandPrimary} />
          <Text style={[styles.quickText, { color: colors.onBrandPrimary }]}>Estratégia Vencedora</Text>
        </Pressable>
        <Pressable testID="open-analysis-button" style={styles.quickBtn} onPress={() => router.push("/analysis")}>
          <Ionicons name="medkit" size={16} color={colors.brandPrimary} />
        </Pressable>
        <Pressable testID="open-hfx-plugins-button" style={styles.quickBtn} onPress={() => router.push("/hfx-plugins")}>
          <Ionicons name="extension-puzzle" size={16} color={colors.brandPrimary} />
          <Text style={styles.quickText}>Plugins</Text>
        </Pressable>
      </View>
      <ChipRow options={(pairs.data ?? []).map((p) => ({ value: p.pair, label: p.display }))} value={pair} onChange={setPair} testID="hfx-pairs" />
      <ScrollView contentContainerStyle={{ paddingBottom: bottomChrome + 24 }}>
        <View style={styles.priceRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.pairName}>{c?.display ?? "…"}</Text>
            <Text style={styles.price} testID="hfx-price">
              {c ? fmt(c.price, c.decimals) : "—"}
            </Text>
          </View>
          <View style={styles.timer}>
            <Text style={styles.timerLabel}>Próxima vela</Text>
            <Text style={styles.timerValue} testID="hfx-candle-timer">
              00:{String(secsToCandle).padStart(2, "0")}
            </Text>
          </View>
        </View>
        {c && !c.open && (
          <View style={styles.closed} testID="hfx-market-closed">
            <Ionicons name="moon" size={16} color={colors.warning} />
            <Text style={styles.closedText}>Mercado forex fechado. Usa os pares OTC para operar agora.</Text>
          </View>
        )}
        <View style={styles.chartBox}>
          {chart.isLoading || !c ? (
            <View style={styles.chartLoading}>
              <ActivityIndicator color={colors.brandPrimary} />
            </View>
          ) : (
            <CandleChart candles={c.candles} decimals={c.decimals} height={220} show={{ ob: false, fvg: false, bos: false }} />
          )}
        </View>

        {sel && (
          <Animated.View entering={FadeInDown} style={[styles.sigCard, sel.signal === "CALL" && styles.sigCall, sel.signal === "PUT" && styles.sigPut]} testID="hfx-selected-signal">
            <View style={{ flex: 1 }}>
              <Text style={styles.sigTitle}>
                {sel.signal ? `Sinal ${sel.signal === "CALL" ? "SOBE (CALL)" : "DESCE (PUT)"} · ${expiry} min` : "Sem sinal nesta vela"}
              </Text>
              <Text style={styles.sigMeta}>
                {sel.best
                  ? `${sel.best.label}: ${fmt(sel.best.winrate, 0)}% acerto em ${sel.best.samples} sinais recentes · mínimo p/ lucrar ${fmt(sel.breakeven, 1)}%`
                  : "Histórico insuficiente para avaliar"}
              </Text>
            </View>
            {sel.signal && <Ionicons name={sel.signal === "CALL" ? "trending-up" : "trending-down"} size={28} color={sel.signal === "CALL" ? colors.success : colors.error} />}
          </Animated.View>
        )}

        <View style={styles.ticket}>
          <View style={{ flexDirection: "row", gap: 12, alignItems: "center" }}>
            <View style={{ flex: 1 }}>
              <Segmented
                options={[
                  { value: "1", label: "1 min" },
                  { value: "3", label: "3 min" },
                ]}
                value={expiry}
                onChange={setExpiry}
                testID="hfx-expiry"
              />
            </View>
            <View style={styles.payout}>
              <Text style={styles.payoutLabel}>Payout</Text>
              <Text style={styles.payoutValue} testID="hfx-payout">
                {Math.round(payout * 100)}%
              </Text>
            </View>
          </View>
          <View style={styles.amountRow}>
            <Pressable testID="hfx-amount-minus" style={styles.amtBtn} onPress={() => setAmount((a) => Math.max(1, a - 5))}>
              <Text style={styles.amtBtnText}>−</Text>
            </Pressable>
            <View style={{ flex: 1, alignItems: "center" }}>
              <Text style={styles.amountValue} testID="hfx-amount">
                {money(amount)}
              </Text>
              <Text style={styles.sigMeta}>Lucro se acertar: +{money(amount * payout)}</Text>
            </View>
            <Pressable testID="hfx-amount-plus" style={styles.amtBtn} onPress={() => setAmount((a) => Math.min(1000, a + 5))}>
              <Text style={styles.amtBtnText}>+</Text>
            </Pressable>
          </View>
          <View style={{ flexDirection: "row", gap: 8, justifyContent: "center" }}>
            {AMOUNTS.map((a) => (
              <Pressable key={a} testID={`hfx-amount-${a}`} onPress={() => setAmount(a)} style={[styles.preset, amount === a && styles.presetOn]}>
                <Text style={[styles.presetText, amount === a && { color: colors.brandPrimary }]}>${a}</Text>
              </Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", gap: 12 }}>
            <PressableScale testID="hfx-call-button" disabled={place.isPending || !c?.open} style={[styles.dirBtn, { backgroundColor: colors.success }]} onPress={() => place.mutate("CALL")}>
              <Ionicons name="arrow-up" size={22} color={colors.onSuccess} />
              <Text style={styles.dirText}>SOBE</Text>
            </PressableScale>
            <PressableScale testID="hfx-put-button" disabled={place.isPending || !c?.open} style={[styles.dirBtn, { backgroundColor: colors.error }]} onPress={() => place.mutate("PUT")}>
              <Ionicons name="arrow-down" size={22} color={colors.onError} />
              <Text style={styles.dirText}>DESCE</Text>
            </PressableScale>
          </View>
        </View>

        {st && (
          <View style={styles.stats} testID="hfx-stats">
            <Stat label="Saldo" value={money(trades.data!.balance)} />
            <Stat label="Entradas" value={String(st.trades)} />
            <Stat label="Acerto" value={st.trades ? `${fmt(st.winrate, 0)}%` : "—"} />
            <Stat label="Resultado" value={money(st.profit)} color={st.profit >= 0 ? colors.success : colors.error} />
          </View>
        )}

        {!!trades.data?.open.length && <Text style={styles.section}>Em curso</Text>}
        {trades.data?.open.map((t) => {
          const left = Math.max(0, Math.ceil(t.expires_ts - (now + offset)));
          return (
            <View key={t.trade_id} style={[styles.tradeRow, { borderLeftColor: t.winning ? colors.success : colors.error }]} testID={`hfx-open-${t.trade_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.tradeTitle}>
                  {t.display} · {t.direction === "CALL" ? "SOBE" : "DESCE"} · {money(t.amount)}
                  {t.origin === "bot" ? " · ROBÔ" : ""}
                </Text>
                <Text style={styles.sigMeta}>
                  Entrada {fmt(t.entry_price, t.decimals)} · agora {fmt(t.current_price ?? t.entry_price, t.decimals)}
                </Text>
              </View>
              <Text style={[styles.countdown, { color: t.winning ? colors.success : colors.error }]}>
                {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
              </Text>
            </View>
          );
        })}

        <Text style={styles.section}>Sinais {expiry} min · todos os pares</Text>
        {sigs.isLoading && <ActivityIndicator color={colors.brandPrimary} style={{ margin: 16 }} />}
        {sigs.data?.map((s) => (
          <Pressable key={s.pair} testID={`hfx-signal-${s.pair}`} style={styles.sigRow} onPress={() => setPair(s.pair)}>
            <Text style={styles.sigPair}>{s.display}</Text>
            <Text style={styles.sigRule} numberOfLines={1}>
              {s.best ? `${s.best.label} · ${fmt(s.best.winrate, 0)}% (${s.best.samples})` : "—"}
            </Text>
            <View style={[styles.sigTag, s.signal === "CALL" ? styles.tagCall : s.signal === "PUT" ? styles.tagPut : styles.tagNone]}>
              <Text style={[styles.sigTagText, { color: s.signal === "CALL" ? colors.success : s.signal === "PUT" ? colors.error : colors.muted }]}>
                {s.signal ?? "—"}
              </Text>
            </View>
          </Pressable>
        ))}

        {!!trades.data?.closed.length && <Text style={styles.section}>Resultados recentes</Text>}
        {trades.data?.closed.slice(0, 15).map((t) => (
          <View key={t.trade_id} style={styles.resRow}>
            <Ionicons
              name={t.status === "won" ? "checkmark-circle" : t.status === "lost" ? "close-circle" : "remove-circle"}
              size={18}
              color={t.status === "won" ? colors.success : t.status === "lost" ? colors.error : colors.muted}
            />
            <Text style={[styles.sigMeta, { flex: 1 }]}>
              {t.display} {t.direction === "CALL" ? "SOBE" : "DESCE"} {t.expiry}m{t.origin === "bot" ? " · robô" : ""}
            </Text>
            <Text style={[styles.resPnl, { color: (t.profit ?? 0) >= 0 ? colors.success : colors.error }]}>
              {(t.profit ?? 0) >= 0 ? "+" : ""}
              {fmt(t.profit ?? 0, 2)}
            </Text>
          </View>
        ))}
        <Text style={styles.disclaimer}>
          Os pares OTC são um feed simulado pela app (como fazem as corretoras ao fim de semana) e não correspondem aos preços da tua corretora. Em movimentos de 1–3 minutos o resultado é muito aleatório: só há vantagem se a taxa de acerto ficar acima do mínimo indicado de forma consistente.
        </Text>
      </ScrollView>
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.payoutLabel}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: 16 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 32 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  botBtn: { flexDirection: "row", alignItems: "center", gap: 6, height: 44, paddingHorizontal: 14, borderRadius: 22, borderWidth: 1, borderColor: c.brandPrimary },
  botBtnText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 15 },
  quick: { flexDirection: "row", gap: 8, paddingHorizontal: 16, paddingTop: 12 },
  quickBtn: { flexDirection: "row", alignItems: "center", gap: 6, height: 44, paddingHorizontal: 14, borderRadius: 22, borderWidth: 1, borderColor: c.brandPrimary },
  quickMain: { flex: 1, justifyContent: "center", backgroundColor: c.brandPrimary },
  quickText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 15 },
  priceRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16 },
  pairName: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 14 },
  price: { color: c.onSurface, fontFamily: fonts.display, fontSize: 34 },
  timer: { alignItems: "flex-end", backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, paddingHorizontal: 12, paddingVertical: 6 },
  timerLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
  timerValue: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 22 },
  closed: { flexDirection: "row", gap: 8, alignItems: "center", marginHorizontal: 16, marginTop: 8, padding: 12, borderRadius: 12, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.warning },
  closedText: { flex: 1, color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
  chartBox: { marginTop: 8, paddingLeft: 8, borderTopWidth: 1, borderBottomWidth: 1, borderColor: c.border, overflow: "hidden" },
  chartLoading: { height: 220, alignItems: "center", justifyContent: "center" },
  sigCard: { flexDirection: "row", alignItems: "center", gap: 12, margin: 16, marginBottom: 0, padding: 12, borderRadius: 12, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border },
  sigCall: { borderColor: c.success, backgroundColor: c.successSoft },
  sigPut: { borderColor: c.error, backgroundColor: c.errorSoft },
  sigTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  sigMeta: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 12 },
  ticket: { margin: 16, gap: 12, padding: 16, borderRadius: 20, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border },
  payout: { alignItems: "center", minWidth: 64 },
  payoutLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
  payoutValue: { color: c.success, fontFamily: fonts.display, fontSize: 22 },
  amountRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  amtBtn: { width: 48, height: 48, borderRadius: 12, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  amtBtnText: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  amountValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 28 },
  preset: { height: 44, paddingHorizontal: 12, borderRadius: 999, borderWidth: 1, borderColor: c.borderStrong, justifyContent: "center" },
  presetOn: { borderColor: c.brandPrimary, backgroundColor: c.brandSoft },
  presetText: { color: c.onSurfaceSecondary, fontFamily: fonts.displaySemi, fontSize: 14 },
  dirBtn: { flex: 1, height: 64, borderRadius: 16, flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center" },
  dirText: { color: c.onSuccess, fontFamily: fonts.display, fontSize: 22, letterSpacing: 1 },
  stats: { flexDirection: "row", gap: 8, paddingHorizontal: 16 },
  stat: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8 },
  statValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 15 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", paddingHorizontal: 16, marginTop: 20, marginBottom: 4 },
  tradeRow: { flexDirection: "row", alignItems: "center", marginHorizontal: 16, marginTop: 8, padding: 12, borderRadius: 12, backgroundColor: c.surfaceSecondary, borderLeftWidth: 4 },
  tradeTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 15 },
  countdown: { fontFamily: fonts.display, fontSize: 24 },
  sigRow: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 48, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: c.divider },
  sigPair: { width: 104, color: c.onSurface, fontFamily: fonts.display, fontSize: 15 },
  sigRule: { flex: 1, color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 12 },
  sigTag: { minWidth: 52, alignItems: "center", paddingVertical: 4, borderRadius: 6 },
  tagCall: { backgroundColor: c.successSoft },
  tagPut: { backgroundColor: c.errorSoft },
  tagNone: { backgroundColor: c.surfaceTertiary },
  sigTagText: { fontFamily: fonts.display, fontSize: 13 },
  resRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 16, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.divider },
  resPnl: { fontFamily: fonts.display, fontSize: 15 },
  disclaimer: { color: c.muted, fontFamily: fonts.text, fontSize: 11, lineHeight: 16, padding: 16 },
}));
