import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fmt, money } from "@/src/api";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const num = (s: string) => Number(s.replace(",", "."));

function Field({ label, value, onChange, testID, suffix }: { label: string; value: string; onChange: (s: string) => void; testID: string; suffix?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ flex: 1, gap: 4 }}>
      <Text style={styles.label}>
        {label}
        {suffix ? ` (${suffix})` : ""}
      </Text>
      <TextInput testID={testID} value={value} onChangeText={onChange} keyboardType="decimal-pad" style={styles.input} placeholderTextColor={colors.muted} />
    </View>
  );
}

export default function Calculator() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [capital, setCapital] = useState("10000");
  const [riskPct, setRiskPct] = useState("1");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");

  const cap = num(capital);
  const rp = num(riskPct);
  const e = num(entry);
  const s = num(stop);
  const t = num(target);
  const valid = cap > 0 && rp > 0 && e > 0 && s > 0 && e !== s;
  const riskAmt = valid ? (cap * rp) / 100 : 0;
  const dist = valid ? Math.abs(e - s) : 0;
  const qty = valid ? riskAmt / dist : 0;
  const notional = qty * e;
  const side = valid ? (s < e ? "COMPRA (long)" : "VENDA (short)") : "—";
  const hasT = valid && t > 0 && (s < e ? t > e : t < e);
  const reward = hasT ? Math.abs(t - e) * qty : 0;
  const rr = hasT ? Math.abs(t - e) / dist : 0;
  const leverage = valid ? notional / cap : 0;
  const breakevenWr = hasT ? (1 / (1 + rr)) * 100 : 0;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="calculator-screen">
      <View style={styles.header}>
        <Pressable testID="calculator-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Calculadora de Posição</Text>
      </View>
      <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}>
        <View style={styles.row}>
          <Field label="Capital" suffix="$" value={capital} onChange={setCapital} testID="calc-capital" />
          <Field label="Risco" suffix="%" value={riskPct} onChange={setRiskPct} testID="calc-risk" />
        </View>
        <Field label="Preço de entrada" value={entry} onChange={setEntry} testID="calc-entry" />
        <View style={styles.row}>
          <Field label="Stop loss" value={stop} onChange={setStop} testID="calc-stop" />
          <Field label="Alvo (opcional)" value={target} onChange={setTarget} testID="calc-target" />
        </View>
        <View style={styles.result} testID="calc-result">
          <Text style={styles.label}>Quantidade a abrir</Text>
          <Text style={styles.big} testID="calc-qty">
            {valid ? fmt(qty, qty >= 100 ? 2 : 6) : "—"}
          </Text>
          <Text style={styles.side}>{side}</Text>
          <View style={styles.grid}>
            <Cell label="Risco em $" value={valid ? money(riskAmt) : "—"} color={colors.error} testID="calc-risk-amount" />
            <Cell label="Valor nocional" value={valid ? money(notional) : "—"} testID="calc-notional" />
            <Cell label="Alavancagem" value={valid ? `${fmt(leverage, 2)}x` : "—"} testID="calc-leverage" />
            <Cell label="Ganho no alvo" value={hasT ? money(reward) : "—"} color={colors.success} testID="calc-reward" />
            <Cell label="Risco:Retorno" value={hasT ? `1:${fmt(rr, 2)}` : "—"} testID="calc-rr" />
            <Cell label="Acerto mínimo" value={hasT ? `${fmt(breakevenWr, 1)}%` : "—"} testID="calc-breakeven" />
          </View>
          {valid && leverage > 10 && <Text style={styles.warn}>Atenção: alavancagem acima de 10x. Considera um stop mais largo ou menos risco.</Text>}
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}

function Cell({ label, value, color, testID }: { label: string; value: string; color?: string; testID: string }) {
  const styles = useStyles();
  return (
    <View style={styles.cell}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.cellValue, color ? { color } : null]} testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  row: { flexDirection: "row", gap: 12 },
  label: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  input: { height: 48, borderRadius: 8, backgroundColor: c.surfaceTertiary, color: c.onSurfaceTertiary, paddingHorizontal: 12, fontFamily: fonts.display, fontSize: 18, borderWidth: 1, borderColor: c.borderStrong },
  result: { marginTop: 8, backgroundColor: c.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: c.brandTertiary, padding: 16, gap: 4 },
  big: { color: c.onSurface, fontFamily: fonts.display, fontSize: 40 },
  side: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 15, marginBottom: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  cell: { width: "48.5%", backgroundColor: c.surfaceTertiary, borderRadius: 12, padding: 10 },
  cellValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  warn: { color: c.warning, fontFamily: fonts.text, fontSize: 12, marginTop: 8 },
}));
