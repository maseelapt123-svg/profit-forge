import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Text, View } from "react-native";

import { api } from "@/src/api";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Resp = { display: string; tf: string; n: number; up: number; down: number; signal: "BUY" | "SELL" | null; checks: { label: string; state: number }[] };

/** Live checklist of the 12 confirmations on the last closed candle. */
export function Confirm12Panel({ symbol, tf, min, set = "c12" }: { symbol: string; tf: string; min: number; set?: "c12" | "c20" }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery({
    queryKey: ["confirm12", symbol, tf, min, set],
    queryFn: () => api<Resp>(`/confirm12?symbol=${encodeURIComponent(symbol)}&tf=${tf}&min=${min}&set=${set}`),
    refetchInterval: 60000,
  });
  const d = q.data;
  if (!d) {
    return (
      <View style={styles.card}>
        {q.isError ? <Text style={styles.muted}>Sem dados suficientes para este ativo.</Text> : <ActivityIndicator color={colors.brandPrimary} />}
      </View>
    );
  }
  const dir = d.up >= d.down ? 1 : -1;
  return (
    <View style={styles.card} testID={`confirm-panel-${set}`}>
      <View style={styles.head}>
        <Text style={[styles.title, { flex: 1 }]}>
          {d.display} · {d.tf.toUpperCase()}
        </Text>
        <Text style={[styles.score, { color: d.signal ? colors.success : colors.muted }]} testID="confirm12-score">
          {Math.max(d.up, d.down)}/{d.n} {dir > 0 ? "compra" : "venda"}
        </Text>
      </View>
      {d.checks.map((c) => {
        const ok = c.state === dir;
        return (
          <View key={c.label} style={styles.row}>
            <Ionicons
              name={ok ? "checkmark-circle" : c.state === 0 ? "remove-circle-outline" : "close-circle"}
              size={16}
              color={ok ? colors.success : c.state === 0 ? colors.muted : colors.error}
            />
            <Text style={styles.label}>{c.label}</Text>
          </View>
        );
      })}
      <Text style={styles.muted}>
        {d.signal ? `Entrada de ${d.signal === "BUY" ? "COMPRA" : "VENDA"} confirmada (mín. ${min})` : `Faltam ${Math.max(0, min - Math.max(d.up, d.down))} confirmação(ões) para entrar`}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginBottom: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 6 },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  score: { fontFamily: fonts.display, fontSize: 15 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  label: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));
