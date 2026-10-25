import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt } from "@/src/api";
import { Button, Center, ChipRow, PressableScale, Segmented } from "@/src/components/ui";
import { CATEGORIES, Category } from "@/src/markets";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Row = {
  symbol: string; display: string; name: string; price: number; decimals: number; trend: string;
  patterns: { pattern: string; label: string; dir: number; bars_ago: number }[];
};
const TFS = [
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];

export default function Patterns() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [cat, setCat] = useState<Category>("crypto");
  const [tf, setTf] = useState("1h");
  const q = useQuery({ queryKey: ["patterns", cat, tf], queryFn: () => api<Row[]>(`/patterns?category=${cat}&tf=${tf}`), refetchInterval: 60000 });

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="patterns-screen">
      <View style={styles.header}>
        <Pressable testID="patterns-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Scanner de Padrões</Text>
      </View>
      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <Segmented options={CATEGORIES} value={cat} onChange={setCat} testID="patterns-category" />
      </View>
      <ChipRow options={TFS} value={tf} onChange={setTf} testID="patterns-tf" />
      {q.isLoading ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
        </Center>
      ) : q.isError ? (
        <Center>
          <Text style={styles.muted}>Falha ao analisar padrões</Text>
          <Button label="Tentar Novamente" onPress={() => q.refetch()} testID="patterns-retry" />
        </Center>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(i) => i.symbol}
          contentContainerStyle={{ padding: 16, paddingTop: 4, gap: 8, paddingBottom: insets.bottom + 16 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); }} tintColor={colors.brandPrimary} />}
          renderItem={({ item }) => (
            <PressableScale
              testID={`pattern-row-${item.symbol}`}
              style={styles.card}
              onPress={() => router.push({ pathname: "/chart/[symbol]", params: { symbol: item.symbol, tf } })}
            >
              <View style={styles.cardHead}>
                <Text style={styles.sym}>{item.display}</Text>
                <Text style={styles.muted}>
                  {fmt(item.price, item.decimals)} · tendência {item.trend}
                </Text>
              </View>
              {item.patterns.length ? (
                <View style={styles.tags}>
                  {item.patterns.map((p, i) => (
                    <View key={i} style={[styles.tag, p.dir > 0 ? styles.tagUp : p.dir < 0 ? styles.tagDown : styles.tagN]}>
                      <Text style={[styles.tagText, { color: p.dir > 0 ? colors.success : p.dir < 0 ? colors.error : colors.onSurfaceSecondary }]}>
                        {p.label} · {p.bars_ago === 1 ? "última vela" : `há ${p.bars_ago} velas`}
                      </Text>
                    </View>
                  ))}
                </View>
              ) : (
                <Text style={styles.muted}>Sem padrões nas últimas 3 velas fechadas</Text>
              )}
            </PressableScale>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 8 },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  tag: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  tagUp: { backgroundColor: c.successSoft },
  tagDown: { backgroundColor: c.errorSoft },
  tagN: { backgroundColor: c.surfaceTertiary },
  tagText: { fontFamily: fonts.displaySemi, fontSize: 13 },
}));
