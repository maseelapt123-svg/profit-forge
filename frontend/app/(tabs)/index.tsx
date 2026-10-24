import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, RefreshControl, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt } from "@/src/api";
import { Sparkline } from "@/src/components/charts";
import { AssetBadge, Button, Center, Pill, PressableScale, Segmented } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { fonts, makeStyles, useTheme } from "@/src/theme";

import { CATEGORIES, Category } from "@/src/markets";

type Quote = { symbol: string; name: string; display: string; price: number; change_pct: number; decimals: number; spark: number[] };

export default function Markets() {
  const [cat, setCat] = useState<Category>("crypto");
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useQuery({ queryKey: ["markets", cat], queryFn: () => api<Quote[]>(`/markets?category=${cat}`), refetchInterval: 30000 });

  return (
    <View style={styles.root} testID="markets-screen">
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <Text style={styles.title}>Mercados</Text>
        <Text style={styles.subtitle}>Preços ao vivo · atualiza a cada 30s</Text>
        <View style={{ marginTop: 12 }}>
          <Segmented options={CATEGORIES} value={cat} onChange={setCat} testID="markets-category" />
        </View>
      </View>
      {q.isLoading ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
        </Center>
      ) : q.isError ? (
        <Center>
          <Text style={styles.muted}>Falha ao carregar mercados</Text>
          <Button label="Tentar Novamente" onPress={() => q.refetch()} testID="markets-retry" />
        </Center>
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(i) => i.symbol}
          contentContainerStyle={{ paddingBottom: bottomChrome + 16 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); }} tintColor={colors.brandPrimary} />}
          renderItem={({ item, index }) => (
            <Animated.View entering={FadeInDown.delay(index * 40)}>
              <PressableScale
                testID={`market-row-${item.symbol}`}
                style={styles.row}
                onPress={() => router.push({ pathname: "/chart/[symbol]", params: { symbol: item.symbol } })}
              >
                <AssetBadge symbol={item.symbol} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.sym}>{item.display}</Text>
                  <Text style={styles.name}>{item.name}</Text>
                </View>
                <Sparkline data={item.spark} />
                <View style={styles.right}>
                  <Text style={styles.price} testID={`market-price-${item.symbol}`}>
                    {fmt(item.price, item.decimals)}
                  </Text>
                  <Pill value={item.change_pct} />
                </View>
              </PressableScale>
            </Animated.View>
          )}
          ListEmptyComponent={<Text style={[styles.muted, { padding: 24 }]}>Nenhum ativo disponível</Text>}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { paddingHorizontal: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: c.border },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 32 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.divider },
  sym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  name: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  right: { alignItems: "flex-end", gap: 4, minWidth: 96 },
  price: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  muted: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 14, textAlign: "center" },
}));
