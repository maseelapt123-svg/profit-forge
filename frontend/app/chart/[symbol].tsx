import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useRef, useState } from "react";
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import Animated, { FadeIn } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, streamSSE } from "@/src/api";
import { CandleChart, Candle, Struct, Zone } from "@/src/components/charts";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow, Segmented, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type ChartData = {
  symbol: string; display: string; name: string; price: number; decimals: number; candles: Candle[];
  order_blocks: Zone[]; fvgs: Zone[]; structure: Struct[]; trend: number;
};
const TFS = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];
const OVERLAYS = [
  { value: "ob", label: "Order Blocks" },
  { value: "fvg", label: "FVG" },
  { value: "bos", label: "BOS / CHoCH" },
] as const;

export default function ChartScreen() {
  const { symbol, tf: tf0 } = useLocalSearchParams<{ symbol: string; tf?: string }>();
  const [tf, setTf] = useState(tf0 ?? "1h");
  const [overlays, setOverlays] = useState<string[]>(["ob", "fvg", "bos"]);
  const [ai, setAi] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [side, setSide] = useState<"BUY" | "SELL" | null>(null);
  const abort = useRef<AbortController | null>(null);
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const q = useQuery({ queryKey: ["candles", symbol, tf], queryFn: () => api<ChartData>(`/candles?symbol=${encodeURIComponent(symbol)}&tf=${tf}`), refetchInterval: 30000 });
  const d = q.data;
  const first = d?.candles[0]?.o ?? 0;
  const chg = d && first ? ((d.price - first) / first) * 100 : 0;

  const toggle = (v: string) => setOverlays((o) => (o.includes(v) ? o.filter((x) => x !== v) : [...o, v]));

  const runAi = async () => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setAi("");
    setAiLoading(true);
    try {
      await streamSSE("/ai/analyze", { symbol, tf }, (t) => setAi((a) => a + t), ctrl.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") toast(e.message ?? "Falha na análise IA", "error");
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <View style={styles.root} testID="chart-screen">
      <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
        <Pressable testID="chart-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.sym}>{d?.display ?? symbol}</Text>
          <Text style={styles.name}>{d?.name}</Text>
        </View>
        {d && (
          <View style={{ alignItems: "flex-end" }}>
            <Text style={styles.price} testID="chart-price">
              {fmt(d.price, d.decimals)}
            </Text>
            <Text style={[styles.chg, { color: chg >= 0 ? colors.success : colors.error }]}>
              {chg >= 0 ? "+" : ""}
              {chg.toFixed(2)}% · {d.trend === 1 ? "Estrutura de alta" : d.trend === -1 ? "Estrutura de baixa" : "Sem estrutura"}
            </Text>
          </View>
        )}
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 16 }}>
        <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
          <Segmented options={TFS} value={tf} onChange={setTf} testID="chart-tf" />
        </View>
        <View style={styles.chartBox}>
          {q.isLoading ? (
            <View style={styles.chartLoading}>
              <ActivityIndicator color={colors.brandPrimary} />
            </View>
          ) : q.isError || !d ? (
            <View style={styles.chartLoading}>
              <Text style={styles.muted}>Erro ao carregar gráfico</Text>
              <Button label="Tentar Novamente" onPress={() => q.refetch()} variant="ghost" testID="chart-retry" />
            </View>
          ) : (
            <CandleChart
              candles={d.candles}
              obs={d.order_blocks}
              fvgs={d.fvgs}
              structure={d.structure}
              decimals={d.decimals}
              show={{ ob: overlays.includes("ob"), fvg: overlays.includes("fvg"), bos: overlays.includes("bos") }}
            />
          )}
        </View>
        <ChipRow options={OVERLAYS as any} value={overlays} onChange={toggle} testID="chart-overlay" />
        {d && (
          <View style={styles.legend}>
            <Text style={styles.legendText}>
              {d.order_blocks.length} order blocks ativos · {d.fvgs.length} FVG abertos · {d.structure.length} quebras de estrutura
            </Text>
          </View>
        )}
        <View style={styles.aiCard} testID="ai-card">
          <View style={styles.aiHead}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="sparkles" size={18} color={colors.brandPrimary} />
              <Text style={styles.aiTitle}>Análise IA Smart Money</Text>
            </View>
            <Pressable testID="ai-analyze-button" onPress={runAi} disabled={aiLoading} style={styles.aiBtn}>
              {aiLoading ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Text style={styles.aiBtnText}>{ai ? "Atualizar" : "Analisar"}</Text>}
            </Pressable>
          </View>
          {ai ? (
            <Animated.View entering={FadeIn}>
              <MarkdownLite text={ai} />
            </Animated.View>
          ) : (
            <Text style={styles.muted2}>A IA lê a estrutura, order blocks e FVG deste gráfico e sugere entrada, stop e alvo.</Text>
          )}
        </View>
      </ScrollView>
      <View style={[styles.bar, { paddingBottom: insets.bottom + 12 }]}>
        <Button label="Comprar" variant="buy" style={{ flex: 1 }} onPress={() => setSide("BUY")} disabled={!d} testID="buy-button" />
        <Button label="Vender" variant="sell" style={{ flex: 1 }} onPress={() => setSide("SELL")} disabled={!d} testID="sell-button" />
      </View>
      {d && <OrderSheet side={side} onClose={() => setSide(null)} data={d} />}
    </View>
  );
}

function MarkdownLite({ text }: { text: string }) {
  const styles = useStyles();
  return (
    <View style={{ gap: 4 }} testID="ai-analysis-text">
      {text.split("\n").map((line, i) => {
        const t = line.trim();
        if (!t) return <View key={i} style={{ height: 4 }} />;
        const heading = /^(#+\s|\*\*[^*]+\*\*:?$)/.test(t);
        const clean = t.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "• ");
        const parts = clean.split(/(\*\*[^*]+\*\*)/g);
        return (
          <Text key={i} style={heading ? styles.mdHead : styles.mdText}>
            {parts.map((p, j) =>
              p.startsWith("**") && p.endsWith("**") ? (
                <Text key={j} style={styles.mdBold}>
                  {p.slice(2, -2)}
                </Text>
              ) : (
                p
              ),
            )}
          </Text>
        );
      })}
    </View>
  );
}

function OrderSheet({ side, onClose, data }: { side: "BUY" | "SELL" | null; onClose: () => void; data: ChartData }) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [qty, setQty] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const num = (s: string) => (s.trim() ? Number(s.replace(",", ".")) : undefined);
  const notional = (num(qty) ?? 0) * data.price;

  const submit = async () => {
    setErr(null);
    const q = num(qty);
    if (!q || q <= 0 || isNaN(q)) return setErr("Indica uma quantidade válida");
    setBusy(true);
    try {
      await api("/orders", { method: "POST", body: { symbol: data.symbol, side, qty: q, stop_loss: num(sl), take_profit: num(tp) } });
      haptic("heavy");
      toast(`${side === "BUY" ? "Compra" : "Venda"} executada em ${data.display}`, "success");
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      setQty("");
      setSl("");
      setTp("");
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={!!side} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <Pressable style={styles.scrim} onPress={onClose} testID="order-sheet-backdrop" />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="order-sheet">
          <View style={styles.grabber} />
          <Text style={styles.sheetTitle}>
            {side === "BUY" ? "Comprar" : "Vender"} {data.display}
          </Text>
          <Text style={styles.muted2}>
            Preço de mercado {fmt(data.price, data.decimals)} · Conta simulada
          </Text>
          <Field label="Quantidade" value={qty} onChange={setQty} testID="order-qty-input" placeholder="ex: 0.01" />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Field label="Stop Loss (opcional)" value={sl} onChange={setSl} testID="order-sl-input" placeholder={fmt(data.price * (side === "BUY" ? 0.98 : 1.02), data.decimals)} />
            </View>
            <View style={{ flex: 1 }}>
              <Field label="Take Profit (opcional)" value={tp} onChange={setTp} testID="order-tp-input" placeholder={fmt(data.price * (side === "BUY" ? 1.04 : 0.96), data.decimals)} />
            </View>
          </View>
          <Text style={styles.muted2} testID="order-notional">
            Valor nocional: ${fmt(notional, 2)}
          </Text>
          {err && (
            <Text style={{ color: colors.error, fontFamily: fonts.text }} testID="order-error">
              {err}
            </Text>
          )}
          <Button label={`Confirmar ${side === "BUY" ? "Compra" : "Venda"}`} variant={side === "BUY" ? "buy" : "sell"} loading={busy} onPress={submit} testID="order-confirm-button" />
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Field({ label, value, onChange, testID, placeholder }: { label: string; value: string; onChange: (s: string) => void; testID: string; placeholder?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput testID={testID} value={value} onChangeText={onChange} keyboardType="decimal-pad" placeholder={placeholder} placeholderTextColor={colors.muted} style={styles.input} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  sym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  name: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  price: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  chg: { fontFamily: fonts.displaySemi, fontSize: 12 },
  chartBox: { marginTop: 12, paddingLeft: 8, borderTopWidth: 1, borderBottomWidth: 1, borderColor: c.border, backgroundColor: c.surface, overflow: "hidden" },
  chartLoading: { height: 320, alignItems: "center", justifyContent: "center", gap: 12 },
  legend: { paddingHorizontal: 16 },
  legendText: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  aiCard: { margin: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16, gap: 12 },
  aiHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  aiTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  aiBtn: { height: 36, minWidth: 92, paddingHorizontal: 14, borderRadius: 999, backgroundColor: c.brandSoft, alignItems: "center", justifyContent: "center" },
  aiBtnText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 14 },
  muted: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 14 },
  muted2: { color: c.muted, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  mdHead: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 16, marginTop: 6 },
  mdText: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 14, lineHeight: 21 },
  mdBold: { color: c.onSurface, fontWeight: "700" },
  bar: { flexDirection: "row", gap: 12, paddingHorizontal: 16, paddingTop: 12, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surface },
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surfaceSecondary, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, gap: 12, borderTopWidth: 1, borderColor: c.borderStrong },
  grabber: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: c.borderStrong },
  sheetTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  fieldLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  input: { height: 48, borderRadius: 8, backgroundColor: c.surfaceTertiary, color: c.onSurfaceTertiary, paddingHorizontal: 12, fontFamily: fonts.display, fontSize: 18, borderWidth: 1, borderColor: c.borderStrong },
}));
