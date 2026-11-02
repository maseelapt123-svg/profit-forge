import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Pos = {
  id: string; symbol: string; side: "BUY" | "SELL"; volume: number; open_price: number; price: number;
  sl: number | null; tp: number | null; profit: number; swap: number; commission: number; time: string; bot: boolean;
};
type Panel = {
  account: { login: string; server: string; currency: string; balance: number; equity: number; margin: number; free_margin: number; margin_level: number | null; type: string };
  positions: Pos[];
  total_profit: number;
};

export default function MtPanel() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<string | null>(null);
  useEffect(() => {
    if (!confirm) return;
    const t = setTimeout(() => setConfirm(null), 4000); // a stray tap later must not close a real position
    return () => clearTimeout(t);
  }, [confirm]);
  const q = useQuery({ queryKey: ["mt-panel"], queryFn: () => api<Panel>("/live/mt/positions"), refetchInterval: 5000 });
  const close = useMutation({
    mutationFn: (id: string) => api("/live/mt/test-close", { method: "POST", body: { position_id: id } }),
    onSuccess: () => {
      setConfirm(null);
      toast("Posição fechada no MetaTrader", "success");
      qc.invalidateQueries({ queryKey: ["mt-panel"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const col = (v: number) => (v > 0 ? colors.success : v < 0 ? colors.error : colors.muted);
  const a = q.data?.account;
  const cur = a?.currency ?? "";
  const f2 = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="mt-panel-screen">
      <View style={styles.header}>
        <Pressable testID="mt-panel-back" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Painel MT5</Text>
          {a && <Text style={styles.sub}>{a.login} · {a.server} · {a.type === "ACCOUNT_TRADE_MODE_DEMO" ? "demo" : "REAL"}</Text>}
        </View>
        <View style={styles.live}>
          <View style={[styles.dot, { backgroundColor: q.isError ? colors.error : colors.success }]} />
          <Text style={styles.sub}>{q.isError ? "sem ligação" : "ao vivo"}</Text>
        </View>
      </View>
      {q.isLoading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : q.isError ? (
        <Text style={[styles.empty, { color: colors.error }]} testID="mt-panel-error">{(q.error as Error).message}</Text>
      ) : (
        <FlatList
          data={q.data?.positions ?? []}
          keyExtractor={(p) => p.id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24 }}
          refreshControl={<RefreshControl refreshing={q.isFetching && !q.isLoading} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            <View style={{ gap: 10 }}>
              <View style={styles.hero} testID="mt-panel-summary">
                <Text style={styles.label}>Lucro aberto</Text>
                <Text style={[styles.big, { color: col(q.data!.total_profit) }]} testID="mt-panel-total">
                  {q.data!.total_profit >= 0 ? "+" : ""}{f2(q.data!.total_profit)} {cur}
                </Text>
                <View style={styles.grid}>
                  <Stat label="Saldo" value={`${f2(a!.balance)} ${cur}`} />
                  <Stat label="Capital" value={`${f2(a!.equity)} ${cur}`} />
                  <Stat label="Margem livre" value={`${f2(a!.free_margin)} ${cur}`} />
                  <Stat label="Nível margem" value={a!.margin_level ? `${a!.margin_level.toFixed(0)}%` : "—"} />
                </View>
              </View>
              <Text style={styles.section}>Posições abertas ({q.data!.positions.length})</Text>
            </View>
          }
          ListEmptyComponent={<Text style={styles.empty} testID="mt-panel-empty">Sem posições abertas na conta MetaTrader.</Text>}
          renderItem={({ item: p }) => {
            const net = p.profit + p.swap + p.commission;
            return (
              <View style={styles.card} testID={`mt-pos-${p.id}`}>
                <View style={styles.rowBetween}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <Text style={[styles.side, { color: p.side === "BUY" ? colors.success : colors.error }]}>{p.side === "BUY" ? "COMPRA" : "VENDA"}</Text>
                    <Text style={styles.sym}>{p.symbol}</Text>
                    <Text style={styles.sub}>{p.volume} lote</Text>
                  </View>
                  <Text style={[styles.pnl, { color: col(net) }]}>{net >= 0 ? "+" : ""}{net.toFixed(2)} {cur}</Text>
                </View>
                <Text style={styles.sub}>
                  Entrada {p.open_price} · Agora {p.price} · SL {p.sl ?? "—"} · TP {p.tp ?? "—"}
                </Text>
                <View style={styles.rowBetween}>
                  <Text style={styles.sub}>{p.bot ? "Robô SmartTrade" : "Manual"} · {new Date(p.time).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</Text>
                  <Pressable
                    testID={`mt-pos-close-${p.id}`}
                    onPress={() => (confirm === p.id ? close.mutate(p.id) : setConfirm(p.id))}
                    style={[styles.closeBtn, confirm === p.id && { backgroundColor: colors.error, borderColor: colors.error }]}
                  >
                    {close.isPending && close.variables === p.id ? (
                      <ActivityIndicator size="small" color={colors.onBrandPrimary} />
                    ) : (
                      <Text style={[styles.closeText, confirm === p.id && { color: colors.onBrandPrimary }]}>{confirm === p.id ? "Confirmar" : "Fechar"}</Text>
                    )}
                  </Pressable>
                </View>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.statVal}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  sub: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  live: { flexDirection: "row", alignItems: "center", gap: 6, paddingRight: 8 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  hero: { backgroundColor: c.surfaceSecondary, borderRadius: 16, borderWidth: 1, borderColor: c.border, padding: 16, gap: 4 },
  label: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  big: { fontFamily: fonts.display, fontSize: 32 },
  grid: { flexDirection: "row", flexWrap: "wrap", marginTop: 8, rowGap: 10 },
  stat: { width: "50%", gap: 2 },
  statVal: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 15 },
  section: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18, marginTop: 8 },
  empty: { color: c.muted, fontFamily: fonts.text, fontSize: 14, textAlign: "center", padding: 24 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 6 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  side: { fontFamily: fonts.displaySemi, fontSize: 12 },
  sym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  pnl: { fontFamily: fonts.display, fontSize: 16 },
  closeBtn: { minHeight: 44, minWidth: 96, paddingHorizontal: 12, borderRadius: 8, borderWidth: 1, borderColor: c.border, alignItems: "center", justifyContent: "center" },
  closeText: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13 },
}));
