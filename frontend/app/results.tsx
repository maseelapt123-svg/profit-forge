import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money } from "@/src/api";
import { ChipRow, Segmented } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Day = { date: string; trades: number; wins: number; winrate: number; pnl: number; pct: number; bot: number; hfx: number };
type Resp = {
  daily: Day[];
  total: {
    pnl: number; pct: number; trades: number; wins: number; winrate: number; trading_days: number; green_days: number; red_days: number;
    avg_day_pnl: number; avg_day_pct: number; best_day: Day | null; worst_day: Day | null;
  };
};
const PERIODS = [
  { value: "7", label: "7 dias" },
  { value: "30", label: "30 dias" },
  { value: "90", label: "90 dias" },
  { value: "365", label: "1 ano" },
];
const dlabel = (d: string) => {
  const [y, m, dd] = d.split("-");
  return `${dd}/${m}/${y.slice(2)}`;
};

export default function Results() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ scope?: string }>();
  const [scope, setScope] = useState<"all" | "bot" | "hfx" | "portfolio">(
    params.scope === "hfx" ? "hfx" : params.scope === "bot" ? "bot" : params.scope === "portfolio" ? "portfolio" : "all",
  );
  const [days, setDays] = useState("30");
  const q = useQuery({ queryKey: ["daily-results", scope, days], queryFn: () => api<Resp>(`/bot/daily-results?scope=${scope}&days=${days}`) });
  const d = q.data;
  const maxAbs = Math.max(1, ...(d?.daily ?? []).map((x) => Math.abs(x.pnl)));
  const col = (v: number) => (v >= 0 ? colors.success : colors.error);

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="results-screen">
      <View style={styles.header}>
        <Pressable testID="results-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>{scope === "portfolio" ? "Histórico da carteira" : "Resultados dos robôs"}</Text>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); }} tintColor={colors.brandPrimary} />}
      >
        <Segmented
          options={[{ value: "portfolio", label: "Carteira" }, { value: "all", label: "Robôs" }, { value: "bot", label: "Principal" }, { value: "hfx", label: "HFX" }]}
          value={scope}
          onChange={setScope}
          testID="results-scope"
        />
        <View style={{ marginHorizontal: -16 }}>
          <ChipRow options={PERIODS} value={days} onChange={setDays} testID="results-days" />
        </View>
        {!d ? (
          <ActivityIndicator color={colors.brandPrimary} />
        ) : (
          <>
            <View style={styles.row}>
              <View style={styles.card} testID="results-total">
                <Text style={styles.muted}>Total</Text>
                <Text style={[styles.big, { color: col(d.total.pnl) }]} numberOfLines={1} adjustsFontSizeToFit>{money(d.total.pnl)}</Text>
                <Text style={styles.muted}>{d.total.pct >= 0 ? "+" : ""}{fmt(d.total.pct, 2)}% · {d.total.trades} ops · {fmt(d.total.winrate, 0)}%</Text>
              </View>
              <View style={styles.card} testID="results-avg">
                <Text style={styles.muted}>Média por dia</Text>
                <Text style={[styles.big, { color: col(d.total.avg_day_pnl) }]} numberOfLines={1} adjustsFontSizeToFit>{money(d.total.avg_day_pnl)}</Text>
                <Text style={styles.muted}>{d.total.avg_day_pct >= 0 ? "+" : ""}{fmt(d.total.avg_day_pct, 2)}%/dia</Text>
              </View>
            </View>
            <View style={styles.row}>
              <Mini label="Dias verdes" value={String(d.total.green_days)} color={colors.success} />
              <Mini label="Dias vermelhos" value={String(d.total.red_days)} color={colors.error} />
              <Mini label="Melhor dia" value={d.total.best_day ? money(d.total.best_day.pnl) : "—"} color={d.total.best_day ? col(d.total.best_day.pnl) : colors.muted} />
              <Mini label="Pior dia" value={d.total.worst_day ? money(d.total.worst_day.pnl) : "—"} color={d.total.worst_day ? col(d.total.worst_day.pnl) : colors.muted} />
            </View>
            <Text style={styles.section}>Por dia</Text>
            {d.daily.length === 0 ? (
              <Text style={styles.muted}>Os robôs ainda não fecharam operações neste período.</Text>
            ) : (
              d.daily.map((x) => (
                <View key={x.date} style={styles.day} testID={`results-day-${x.date}`}>
                  <View style={{ width: 70 }}>
                    <Text style={styles.dayDate}>{dlabel(x.date)}</Text>
                    <Text style={styles.muted}>{x.trades} ops · {fmt(x.winrate, 0)}%</Text>
                  </View>
                  <View style={styles.barTrack}>
                    <View style={[styles.bar, { width: `${(Math.abs(x.pnl) / maxAbs) * 100}%`, backgroundColor: col(x.pnl) }]} />
                  </View>
                  <View style={{ alignItems: "flex-end", minWidth: 84 }}>
                    <Text style={[styles.dayPnl, { color: col(x.pnl) }]}>{money(x.pnl)}</Text>
                    <Text style={styles.muted}>{x.pct >= 0 ? "+" : ""}{fmt(x.pct, 2)}%</Text>
                    {(scope === "all" || scope === "portfolio") && (x.bot !== 0 || x.hfx !== 0) && (
                      <Text style={styles.muted}>Pos. {money(x.bot)} · HFX {money(x.hfx)}</Text>
                    )}
                  </View>
                </View>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Mini({ label, value, color }: { label: string; value: string; color: string }) {
  const styles = useStyles();
  return (
    <View style={[styles.card, { padding: 8 }]}>
      <Text style={styles.muted} numberOfLines={1}>{label}</Text>
      <Text style={[styles.miniVal, { color }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  row: { flexDirection: "row", gap: 8 },
  card: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 4 },
  big: { fontFamily: fonts.display, fontSize: 22 },
  miniVal: { fontFamily: fonts.display, fontSize: 15 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8 },
  day: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  dayDate: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  barTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  bar: { height: 8, borderRadius: 4 },
  dayPnl: { fontFamily: fonts.display, fontSize: 15 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
}));
