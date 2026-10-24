import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money, pct } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Center, PressableScale, Segmented, haptic } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Pos = {
  position_id: string; symbol: string; display: string; side: "BUY" | "SELL"; qty: number; entry: number; price?: number; exit?: number;
  pnl: number; pnl_pct?: number; decimals: number; stop_loss?: number; take_profit?: number; reason?: string; source?: string; tf?: string;
};
type Portfolio = { balance: number; equity: number; unrealized: number; realized: number; start_balance: number; win_rate: number; positions: Pos[]; history: Pos[] };

export default function PortfolioScreen() {
  const insets = useSafeAreaInsets();
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const styles = useStyles();
  const { colors } = useTheme();
  const { user, signOut } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"open" | "history">("open");
  const [confirmReset, setConfirmReset] = useState(false);
  const q = useQuery({ queryKey: ["portfolio"], queryFn: () => api<Portfolio>("/portfolio"), refetchInterval: 20000 });
  const bot = useQuery({ queryKey: ["bot"], queryFn: () => api<{ bot: { enabled: boolean } }>("/bot") });
  const close = useMutation({
    mutationFn: (id: string) => api<{ pnl: number }>(`/positions/${id}/close`, { method: "POST" }),
    onSuccess: (r) => {
      haptic("heavy");
      toast(`Posição fechada: ${r.pnl >= 0 ? "+" : ""}${money(r.pnl)}`, r.pnl >= 0 ? "success" : "error");
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const reset = useMutation({
    mutationFn: () => api("/portfolio/reset", { method: "POST" }),
    onSuccess: () => {
      setConfirmReset(false);
      toast("Conta simulada reposta para $10.000", "success");
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
  const d = q.data;
  const total = d ? d.equity - d.start_balance : 0;
  const list = tab === "open" ? d?.positions : d?.history;

  return (
    <View style={styles.root} testID="portfolio-screen">
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Portfólio</Text>
          <Text style={styles.subtitle} numberOfLines={1}>
            {user?.email}
          </Text>
        </View>
        <Pressable testID="logout-button" onPress={signOut} style={styles.iconBtn}>
          <Ionicons name="log-out-outline" size={22} color={colors.onSurfaceSecondary} />
        </Pressable>
      </View>
      {q.isLoading ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
        </Center>
      ) : q.isError || !d ? (
        <Center>
          <Text style={styles.muted}>Falha ao carregar portfólio</Text>
          <Button label="Tentar Novamente" onPress={() => q.refetch()} testID="portfolio-retry" />
        </Center>
      ) : (
        <FlatList
          data={list}
          keyExtractor={(i) => i.position_id}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); }} tintColor={colors.brandPrimary} />}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, paddingBottom: bottomChrome + 16 }}
          ListHeaderComponent={
            <View style={{ gap: 12, paddingTop: 16, paddingBottom: 4 }}>
              <View style={styles.hero}>
                <View style={styles.heroTop}>
                  <Text style={styles.heroLabel}>Capital total · Conta simulada</Text>
                  <View style={styles.demoTag}>
                    <Text style={styles.demoText}>DEMO</Text>
                  </View>
                </View>
                <Text style={styles.heroValue} testID="portfolio-equity">
                  {money(d.equity)}
                </Text>
                <Text style={[styles.heroPnl, { color: total >= 0 ? colors.success : colors.error }]} testID="portfolio-total-pnl">
                  {total >= 0 ? "+" : ""}
                  {money(total)} ({pct((total / d.start_balance) * 100)})
                </Text>
                <View style={styles.heroStats}>
                  <Stat label="Saldo" value={money(d.balance)} />
                  <Stat label="Não realizado" value={money(d.unrealized)} color={d.unrealized >= 0 ? colors.success : colors.error} />
                  <Stat label="Acerto" value={`${fmt(d.win_rate, 0)}%`} />
                </View>
              </View>
              <PressableScale testID="open-bot-button" style={styles.botCard} onPress={() => router.push("/bot")}>
                <View style={styles.botIcon}>
                  <Ionicons name="hardware-chip" size={20} color={colors.brandPrimary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.botTitle}>Robô Automático</Text>
                  <Text style={styles.subtitle}>{bot.data?.bot.enabled ? "Ativo · a negociar sozinho" : "Parado · toca para configurar"}</Text>
                </View>
                <View style={[styles.dot, { backgroundColor: bot.data?.bot.enabled ? colors.success : colors.muted }]} />
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </PressableScale>
              <Segmented
                options={[
                  { value: "open", label: `Posições Abertas (${d.positions.length})` },
                  { value: "history", label: "Histórico" },
                ]}
                value={tab}
                onChange={setTab}
                testID="portfolio-tabs"
              />
            </View>
          }
          renderItem={({ item }) => {
            const up = item.pnl >= 0;
            return (
              <View style={styles.pos} testID={`position-${item.position_id}`}>
                <View style={{ flex: 1, gap: 2 }}>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    <Text style={styles.posSym}>{item.display}</Text>
                    <Text style={[styles.side, { color: item.side === "BUY" ? colors.success : colors.error }]}>
                      {item.side === "BUY" ? "LONG" : "SHORT"} · {fmt(item.qty, 4)}
                    </Text>
                    {item.source === "bot" && (
                      <View style={styles.demoTag}>
                        <Text style={styles.demoText}>ROBÔ{item.tf ? ` ${item.tf.toUpperCase()}` : ""}</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.posMeta}>
                    Entrada {fmt(item.entry, item.decimals)} → {fmt((tab === "open" ? item.price : item.exit) ?? 0, item.decimals)}
                    {item.reason ? ` · ${item.reason === "manual" ? "manual" : item.reason === "stop_loss" ? "stop" : "alvo"}` : ""}
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end", gap: 6 }}>
                  <Text style={[styles.posPnl, { color: up ? colors.success : colors.error }]}>
                    {up ? "+" : ""}
                    {money(item.pnl)}
                  </Text>
                  {tab === "open" && (
                    <Pressable
                      testID={`close-position-${item.position_id}`}
                      style={styles.closeBtn}
                      onPress={() => close.mutate(item.position_id)}
                      disabled={close.isPending}
                    >
                      <Text style={styles.closeText}>Fechar</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={{ alignItems: "center", padding: 24, gap: 12 }}>
              <Text style={styles.muted}>{tab === "open" ? "Sem posições abertas." : "Ainda sem operações fechadas."}</Text>
              {tab === "open" && <Button label="Ir para Mercados" onPress={() => router.navigate("/")} testID="go-markets-button" />}
            </View>
          }
          ListFooterComponent={
            <View style={{ paddingTop: 24, gap: 8 }}>
              <Pressable
                testID="reset-account-button"
                onPress={() => {
                  if (confirmReset) reset.mutate();
                  else {
                    setConfirmReset(true);
                    setTimeout(() => setConfirmReset(false), 4000);
                  }
                }}
                style={styles.resetBtn}
              >
                <Ionicons name="refresh" size={16} color={confirmReset ? colors.error : colors.onSurfaceSecondary} />
                <Text style={[styles.resetText, confirmReset && { color: colors.error }]}>
                  {confirmReset ? "Toca de novo para apagar tudo e repor" : "Repor conta simulada"}
                </Text>
              </Pressable>
              <Text style={styles.foot}>Ligação a corretora real chegará numa próxima fase. Nada aqui é aconselhamento financeiro.</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useStyles();
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.heroLabel}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 32 },
  subtitle: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22, backgroundColor: c.surfaceSecondary },
  hero: { backgroundColor: c.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: c.border, padding: 16, gap: 4 },
  heroTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  heroLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  demoTag: { backgroundColor: c.brandSoft, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  demoText: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 12 },
  heroValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 42 },
  heroPnl: { fontFamily: fonts.display, fontSize: 18 },
  heroStats: { flexDirection: "row", marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: c.divider },
  botCard: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12 },
  botIcon: { width: 40, height: 40, borderRadius: 10, backgroundColor: c.brandSoft, alignItems: "center", justifyContent: "center" },
  botTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  statValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  pos: { flexDirection: "row", alignItems: "center", backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 8 },
  posSym: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  side: { fontFamily: fonts.displaySemi, fontSize: 13 },
  posMeta: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  posPnl: { fontFamily: fonts.display, fontSize: 17 },
  closeBtn: { height: 32, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: c.borderStrong, justifyContent: "center" },
  closeText: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13 },
  muted: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 14, textAlign: "center" },
  resetBtn: { flexDirection: "row", alignSelf: "center", alignItems: "center", gap: 6, height: 44, paddingHorizontal: 16 },
  resetText: { color: c.onSurfaceSecondary, fontFamily: fonts.displaySemi, fontSize: 14 },
  foot: { color: c.muted, fontFamily: fonts.text, fontSize: 11, textAlign: "center" },
}));
