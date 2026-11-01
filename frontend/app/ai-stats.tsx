import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money } from "@/src/api";
import { ChipRow, Segmented } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Perf = { trades: number; wins: number; winrate: number; pnl: number };
type Stats = {
  evaluated: number; approved: number; rejected: number; approval_rate: number; open: number;
  approved_perf: Perf; no_ai_perf: Perf; by_confidence: ({ bucket: string } & Perf)[];
  top_reasons: { reason: string; count: number }[];
  recent_rejections: { symbol: string; side: string; confidence: number; reason: string; created_at: string }[];
};
const DAYS = [
  { value: "1", label: "24h" },
  { value: "7", label: "7 dias" },
  { value: "30", label: "30 dias" },
];

export default function AiStats() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ scope?: string }>();
  const [scope, setScope] = useState<"hfx" | "bot">(params.scope === "bot" ? "bot" : "hfx");
  const [days, setDays] = useState("7");
  const q = useQuery({ queryKey: ["ai-filter-stats", scope, days], queryFn: () => api<Stats>(`/ai/filter-stats?scope=${scope}&days=${days}`) });
  const d = q.data;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="ai-stats-screen">
      <View style={styles.header}>
        <Pressable testID="ai-stats-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Filtro IA · Desempenho</Text>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => {
              q.refetch();
            }} tintColor={colors.brandPrimary} />}
      >
        <Segmented options={[{ value: "hfx", label: "Robô HFX" }, { value: "bot", label: "Robô principal" }]} value={scope} onChange={setScope} testID="ai-stats-scope" />
        <View style={{ marginHorizontal: -16 }}>
          <ChipRow options={DAYS} value={days} onChange={setDays} testID="ai-stats-days" />
        </View>
        {!d ? (
          q.isError ? <Text style={styles.muted}>Não foi possível carregar as estatísticas.</Text> : <ActivityIndicator color={colors.brandPrimary} />
        ) : d.evaluated === 0 ? (
          <View style={styles.card} testID="ai-stats-empty">
            <Ionicons name="sparkles-outline" size={28} color={colors.muted} />
            <Text style={styles.muted}>Ainda não há sinais avaliados pela IA neste período. Liga o «Filtro IA» no robô para começar a recolher dados.</Text>
          </View>
        ) : (
          <>
            <View style={styles.row}>
              <Stat label="Avaliados" value={String(d.evaluated)} testID="ai-stats-evaluated" />
              <Stat label="Aprovados" value={String(d.approved)} color={colors.success} testID="ai-stats-approved" />
              <Stat label="Rejeitados" value={String(d.rejected)} color={colors.error} testID="ai-stats-rejected" />
            </View>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Taxa de aprovação</Text>
              <View style={styles.barBg}>
                <View style={[styles.bar, { width: `${Math.min(100, d.approval_rate)}%` }]} />
              </View>
              <Text style={styles.big} testID="ai-stats-rate">{fmt(d.approval_rate, 0)}%</Text>
            </View>
            <Text style={styles.section}>Resultado das entradas</Text>
            <View style={styles.row}>
              <PerfCard title="Aprovadas pela IA" p={d.approved_perf} testID="ai-stats-approved-perf" />
              <PerfCard title="Sem filtro IA" p={d.no_ai_perf} testID="ai-stats-noai-perf" />
            </View>
            {d.open > 0 && <Text style={styles.muted}>{d.open} entrada(s) aprovada(s) ainda em aberto.</Text>}
            {!!d.by_confidence.length && (
              <>
                <Text style={styles.section}>Acerto por confiança da IA</Text>
                {d.by_confidence.map((b) => (
                  <View key={b.bucket} style={styles.line} testID={`ai-stats-bucket-${b.bucket}`}>
                    <Text style={[styles.lineLabel, { flex: 1 }]}>Confiança {b.bucket}</Text>
                    <Text style={styles.muted}>{b.trades} ops</Text>
                    <Text style={styles.lineValue}>{fmt(b.winrate, 0)}%</Text>
                    <Text style={[styles.lineValue, { color: b.pnl >= 0 ? colors.success : colors.error }]}>{money(b.pnl)}</Text>
                  </View>
                ))}
              </>
            )}
            {!!d.top_reasons.length && (
              <>
                <Text style={styles.section}>Principais motivos de rejeição</Text>
                {d.top_reasons.map((r, i) => (
                  <View key={i} style={styles.line}>
                    <Text style={[styles.lineLabel, { flex: 1 }]}>{r.reason}</Text>
                    <Text style={styles.lineValue}>×{r.count}</Text>
                  </View>
                ))}
              </>
            )}
            {!!d.recent_rejections.length && (
              <>
                <Text style={styles.section}>Últimas rejeições</Text>
                {d.recent_rejections.map((r, i) => (
                  <View key={i} style={styles.line} testID={`ai-stats-rejection-${i}`}>
                    <Ionicons name="close-circle" size={18} color={colors.error} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.lineLabel}>
                        {r.symbol.replace("=X", "")} · {r.side} · {r.confidence}%
                      </Text>
                      <Text style={styles.muted}>{r.reason}</Text>
                    </View>
                    <Text style={styles.muted}>{new Date(r.created_at).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}</Text>
                  </View>
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function PerfCard({ title, p, testID }: { title: string; p: Perf; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={[styles.card, { flex: 1 }]} testID={testID}>
      <Text style={styles.muted}>{title}</Text>
      {p.trades ? (
        <>
          <Text style={styles.big}>{fmt(p.winrate, 0)}%</Text>
          <Text style={styles.muted}>{p.wins}/{p.trades} ganhos</Text>
          <Text style={[styles.lineValue, { color: p.pnl >= 0 ? colors.success : colors.error }]}>{money(p.pnl)}</Text>
        </>
      ) : (
        <Text style={styles.big}>—</Text>
      )}
    </View>
  );
}

function Stat({ label, value, color, testID }: { label: string; value: string; color?: string; testID: string }) {
  const styles = useStyles();
  return (
    <View style={[styles.card, { flex: 1 }]} testID={testID}>
      <Text style={styles.muted}>{label}</Text>
      <Text style={[styles.big, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22, flexShrink: 1 },
  row: { flexDirection: "row", gap: 8 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 4 },
  cardTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  big: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  barBg: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden", marginVertical: 4 },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.brandPrimary },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8 },
  line: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 48 },
  lineLabel: { color: c.onSurface, fontFamily: fonts.text, fontSize: 13 },
  lineValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 14, minWidth: 44, textAlign: "right" },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));
