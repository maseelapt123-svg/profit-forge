import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Center, haptic } from "@/src/components/ui";
import { STRATS } from "@/src/strategies";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Setup = { symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean; test?: number; wr?: number };
type Cfg = { enabled: boolean; risk_pct: number; setups: Setup[]; last_run?: string | null };
type Resp = {
  bot: Cfg; mt: boolean; logs: { log_id: string; kind: string; msg: string; created_at: string }[];
  stats: { trades: number; pnl: number; wins: number; open: number };
  positions: { position_id: string; display: string; side: string; entry: number; tf: string }[];
};

const disp = (s: string) => s.replace("=X", "").replace("-USD", "/USD");
const stratLabel = (v: string) => STRATS.find((x) => x.value === v)?.label ?? v;

export default function Bot2Screen() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bot2"], queryFn: () => api<Resp>("/bot2"), refetchInterval: 15000 });
  const [cfg, setCfg] = useState<Cfg | null>(null);
  useEffect(() => {
    if (q.data) setCfg((c) => c ?? q.data.bot);
  }, [q.data]);
  // setups added/replaced from the scan while this screen is open
  const srvSetups = JSON.stringify(q.data?.bot.setups ?? []);
  useEffect(() => {
    if (q.data && cfg && !save.isPending) setCfg((c) => (c ? { ...c, setups: q.data.bot.setups } : c));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srvSetups]);

  const save = useMutation({
    mutationFn: (b: Cfg) => api("/bot2", { method: "PUT", body: b }),
    onSuccess: (_r, b) => {
      haptic("medium");
      qc.invalidateQueries({ queryKey: ["bot2"] });
      toast(b.enabled ? "Robô 2 ativo — verifica sinais a cada minuto" : "Robô 2 guardado", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const runNow = useMutation({
    mutationFn: () => api<{ opened: number }>("/bot2/run", { method: "POST" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["bot2"] });
      toast(r.opened ? `${r.opened} operação(ões) aberta(s)` : "Sem novos sinais na última vela fechada", r.opened ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const upd = (p: Partial<Cfg>) => setCfg((c) => (c ? { ...c, ...p } : c));
  const st = q.data?.stats;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="bot2-screen">
      <View style={styles.header}>
        <Pressable testID="bot2-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/simulate"))} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Robô 2</Text>
      </View>
      {!cfg || !q.data ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} />
        </Center>
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 24, gap: 8 }}>
          <View style={[styles.card, cfg.enabled && { borderColor: colors.success }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle} testID="bot2-status">{cfg.enabled ? "Ativo" : "Parado"}</Text>
                <Text style={styles.note} testID="bot2-where">
                  {q.data.mt ? "Envia ordens para o MetaTrader" : "Conta simulada"} · independente do robô principal
                </Text>
              </View>
              <Switch
                testID="bot2-enabled-switch"
                value={cfg.enabled}
                onValueChange={(v) => upd({ enabled: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
            {st && (
              <Text style={styles.note} testID="bot2-stats">
                {st.trades} trades fechados · {st.trades ? fmt((st.wins / st.trades) * 100, 0) : 0}% acerto · {money(st.pnl)} · {st.open} aberta(s)
              </Text>
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Risco por trade</Text>
            <View style={styles.stepRow}>
              <Pressable testID="bot2-risk-minus" style={styles.stepBtn} onPress={() => upd({ risk_pct: Math.max(0.1, Math.round((cfg.risk_pct - 0.1) * 10) / 10) })}>
                <Ionicons name="remove" size={18} color={colors.onSurface} />
              </Pressable>
              <Text style={styles.stepValue} testID="bot2-risk-value">{cfg.risk_pct}%</Text>
              <Pressable testID="bot2-risk-plus" style={styles.stepBtn} onPress={() => upd({ risk_pct: Math.min(5, Math.round((cfg.risk_pct + 0.1) * 10) / 10) })}>
                <Ionicons name="add" size={18} color={colors.onSurface} />
              </Pressable>
            </View>
          </View>

          <Text style={styles.section}>Setups ({cfg.setups.length})</Text>
          {!cfg.setups.length && (
            <Text style={[styles.note, { paddingHorizontal: 16 }]} testID="bot2-empty">
              Ainda sem setups. Vai a Simular → Vários pares, procura os mais lucrativos e adiciona-os aqui.
            </Text>
          )}
          {cfg.setups.map((s) => (
            <View key={`${s.symbol}|${s.tf}`} style={styles.row} testID={`bot2-setup-${s.symbol}-${s.tf}`}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.rowTitle}>{disp(s.symbol)} {s.tf.toUpperCase()} · {stratLabel(s.strategy)}</Text>
                <Text style={styles.note}>
                  1:{s.rr} · SL {s.sl_atr}×ATR{s.test != null ? ` · teste ${s.test >= 0 ? "+" : ""}${fmt(s.test, 1)}% · acerto ${fmt(s.wr ?? 0, 0)}%` : ""}
                </Text>
              </View>
              <Pressable
                hitSlop={8}
                style={styles.remove}
                onPress={() => upd({ setups: cfg.setups.filter((x) => !(x.symbol === s.symbol && x.tf === s.tf)) })}
                testID={`bot2-remove-${s.symbol}-${s.tf}`}
              >
                <Ionicons name="trash-outline" size={20} color={colors.error} />
              </Pressable>
            </View>
          ))}
          <View style={{ paddingHorizontal: 16, gap: 8, marginTop: 4 }}>
            <Button label="Guardar" onPress={() => save.mutate(cfg)} loading={save.isPending} testID="bot2-save" />
            <Button label="Verificar sinais agora" variant="ghost" onPress={() => runNow.mutate()} loading={runNow.isPending} disabled={!q.data.bot.setups.length} testID="bot2-run" />
            <Button label="Simular estes setups" variant="ghost" onPress={() => router.push({ pathname: "/simulate", params: { mode: "b2" } })} disabled={!q.data.bot.setups.length} testID="bot2-simulate" />
          </View>

          {q.data.positions.length > 0 && <Text style={styles.section}>Posições abertas</Text>}
          {q.data.positions.map((p) => (
            <View key={p.position_id} style={styles.row}>
              <Text style={[styles.rowTitle, { color: p.side === "BUY" ? colors.success : colors.error }]}>{p.side === "BUY" ? "COMPRA" : "VENDA"}</Text>
              <Text style={[styles.note, { flex: 1 }]}>{p.display} {p.tf?.toUpperCase()} @ {p.entry}</Text>
            </View>
          ))}

          <Text style={styles.section}>Atividade</Text>
          {q.data.logs.map((l) => (
            <Text key={l.log_id} style={[styles.note, { paddingHorizontal: 16 }]}>
              {new Date(l.created_at).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · {l.msg}
            </Text>
          ))}
          <Text style={[styles.note, { paddingHorizontal: 16, marginTop: 8 }]}>
            Usa a mesma conta simulada do robô principal. Para enviar este robô ao MetaTrader escolhe «Robô 2» ou «Os dois» em Robô Automático → MetaTrader.
          </Text>
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 8, paddingVertical: 8 },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8, paddingHorizontal: 16 },
  card: { marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 8 },
  cardTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 16 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  stepRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  rowTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  remove: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
}));
