import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Text, View } from "react-native";

import { api, fmt } from "@/src/api";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Resp = {
  display: string; tf: string; signal: "BUY" | "SELL" | null; trend: number; votes_up: number; votes_dn: number;
  score_up: number; score_dn: number; plugins: { plugin: string; label: string; vote: number; weight: number }[];
};

/** Live view of the weighted confluence: each enabled plugin's vote and its weight (recent hit rate). */
export function ConfluencePanel({ symbol, tf, votes, score }: { symbol: string; tf: string; votes: number; score: number }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery({
    queryKey: ["confluence", symbol, tf, votes, score],
    queryFn: () => api<Resp>(`/confluence?symbol=${encodeURIComponent(symbol)}&tf=${tf}&votes=${votes}&score=${score}`),
    refetchInterval: 60000,
  });
  const d = q.data;
  return (
    <View style={styles.card} testID="confluence-panel">
      {!d ? (
        q.isError ? <Text style={styles.muted}>Sem dados de confluência para este ativo.</Text> : <ActivityIndicator color={colors.brandPrimary} />
      ) : (
        <>
          <Text style={styles.title}>
            {d.display} · {d.tf.toUpperCase()} · tendência {d.trend > 0 ? "alta" : "baixa"}
          </Text>
          {d.plugins.length === 0 && <Text style={styles.muted}>Ativa plugins no ecrã de Plugins para usar a confluência.</Text>}
          {d.plugins.map((p) => (
            <View key={p.plugin} style={styles.row} testID={`confluence-plugin-${p.plugin}`}>
              <Text style={[styles.label, { flex: 1 }]} numberOfLines={1}>{p.label}</Text>
              <Text style={[styles.vote, { color: p.vote > 0 ? colors.success : p.vote < 0 ? colors.error : colors.muted }]}>
                {p.vote > 0 ? "COMPRA" : p.vote < 0 ? "VENDA" : "—"}
              </Text>
              <View style={styles.barBg}>
                <View style={[styles.bar, { width: `${Math.min(100, p.weight)}%`, backgroundColor: p.weight >= score ? colors.success : colors.warning }]} />
              </View>
              <Text style={styles.weight}>{fmt(p.weight, 0)}%</Text>
            </View>
          ))}
          <Text style={styles.muted} testID="confluence-status">
            {d.signal
              ? `Sinal ${d.signal === "BUY" ? "de COMPRA" : "de VENDA"} na última vela fechada`
              : `A favor: ${d.votes_up} compra (${fmt(d.score_up, 0)}%) · ${d.votes_dn} venda (${fmt(d.score_dn, 0)}%) — precisa de ${votes}+ plugins com média ≥ ${score}%`}
          </Text>
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginBottom: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12, gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  label: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 12 },
  vote: { width: 56, fontFamily: fonts.displaySemi, fontSize: 12, textAlign: "center" },
  barBg: { width: 64, height: 6, borderRadius: 3, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  bar: { height: 6, borderRadius: 3 },
  weight: { width: 36, color: c.onSurface, fontFamily: fonts.display, fontSize: 13, textAlign: "right" },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));
