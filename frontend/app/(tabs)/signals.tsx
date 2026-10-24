import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt } from "@/src/api";
import { Button, Center, ChipRow, PressableScale, Segmented, SideBadge } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { fonts, makeStyles, useTheme } from "@/src/theme";
import { CATEGORIES, Category } from "@/src/markets";

type Signal = {
  symbol: string; display: string; name: string; direction: "BUY" | "SELL" | "NEUTRAL"; entry: number; stop_loss: number;
  take_profit: number; decimals: number; confidence: number; triggered: { label: string; dir: number }[]; trend: string; rsi: number; htf: string | null; htf_trend: number | null;
};
const TFS = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];

export default function Signals() {
  const [cat, setCat] = useState<Category>("crypto");
  const [tf, setTf] = useState("1h");
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useQuery({ queryKey: ["signals", cat, tf], queryFn: () => api<Signal[]>(`/signals?category=${cat}&tf=${tf}`), refetchInterval: 60000 });

  return (
    <View style={styles.root} testID="signals-screen">
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View style={styles.titleRow}>
          <View>
            <Text style={styles.title}>Sinais</Text>
            <Text style={styles.subtitle}>Consenso dos teus plugins ativos</Text>
          </View>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable testID="signals-open-bot-button" style={styles.iconBtn} onPress={() => router.push("/bot")}>
              <Ionicons name="hardware-chip" size={20} color={colors.brandPrimary} />
            </Pressable>
            <Pressable testID="open-plugins-button" style={styles.iconBtn} onPress={() => router.push("/plugins")}>
              <Ionicons name="extension-puzzle" size={20} color={colors.brandPrimary} />
              <Text style={styles.iconBtnText}>Plugins</Text>
            </Pressable>
          </View>
        </View>
        <View style={{ marginTop: 12 }}>
          <Segmented options={CATEGORIES} value={cat} onChange={setCat} testID="signals-category" />
        </View>
      </View>
      <ChipRow options={TFS} value={tf} onChange={setTf} testID="signals-tf" />
      {q.isLoading ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
          <Text style={styles.muted}>A analisar mercados…</Text>
        </Center>
      ) : q.isError ? (
        <Center>
          <Text style={styles.muted}>Falha ao obter sinais</Text>
          <Button label="Tentar Novamente" onPress={() => q.refetch()} testID="signals-retry" />
        </Center>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(i) => i.symbol}
          contentContainerStyle={{ padding: 16, paddingTop: 4, gap: 12, paddingBottom: bottomChrome + 16 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); }} tintColor={colors.brandPrimary} />}
          renderItem={({ item, index }) => (
            <Animated.View entering={FadeInDown.delay(index * 50)}>
              <PressableScale
                testID={`signal-card-${item.symbol}`}
                style={[styles.card, item.direction === "NEUTRAL" && { opacity: 0.6 }]}
                onPress={() => router.push({ pathname: "/chart/[symbol]", params: { symbol: item.symbol, tf } })}
              >
                <View style={styles.cardHead}>
                  <View>
                    <Text style={styles.sym}>{item.display}</Text>
                    <Text style={styles.name}>
                      Tendência {item.trend} · RSI {item.rsi}
                      {item.htf ? ` · ${item.htf.toUpperCase()} ${item.htf_trend === 1 ? "alta" : item.htf_trend === -1 ? "baixa" : "lateral"}` : ""}
                    </Text>
                  </View>
                  <SideBadge dir={item.direction} />
                </View>
                {item.direction !== "NEUTRAL" ? (
                  <>
                    <View style={styles.levels}>
                      <Level label="Entrada" value={fmt(item.entry, item.decimals)} />
                      <Level label="Stop Loss" value={fmt(item.stop_loss, item.decimals)} color={colors.error} />
                      <Level label="Alvo (2R)" value={fmt(item.take_profit, item.decimals)} color={colors.success} />
                    </View>
                    <View style={styles.confRow}>
                      <View style={styles.confBar}>
                        <View style={[styles.confFill, { width: `${item.confidence}%` }]} />
                      </View>
                      <Text style={styles.confText}>{item.confidence}%</Text>
                    </View>
                    <Text style={styles.trig}>Disparado por: {item.triggered.map((t) => t.label).join(", ")}</Text>
                  </>
                ) : (
                  <Text style={styles.trig}>Sem sinal nas últimas 3 velas</Text>
                )}
              </PressableScale>
            </Animated.View>
          )}
        />
      )}
    </View>
  );
}

function Level({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useStyles();
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.lvlLabel}>{label}</Text>
      <Text style={[styles.lvlValue, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: 16 },
  titleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 32 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  iconBtn: { flexDirection: "row", alignItems: "center", gap: 6, height: 44, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: c.brandPrimary },
  iconBtnText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 15 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16, gap: 12 },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 20 },
  name: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  levels: { flexDirection: "row", gap: 8 },
  lvlLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
  lvlValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  confRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  confBar: { flex: 1, height: 6, borderRadius: 3, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  confFill: { height: 6, backgroundColor: c.brandPrimary },
  confText: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 14 },
  trig: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 12 },
  muted: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 14, textAlign: "center" },
}));
