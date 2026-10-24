import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, money } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Center, ChipRow, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Setup = { symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean };
type Bot = { setups?: Setup[]; mtf: boolean; trend_filter: boolean; enabled: boolean; symbols: string[]; tf: string; strategy: string; risk_pct: number; sl_atr: number; rr: number; max_positions: number; last_run?: string };
type Resp = {
  bot: Bot; logs: { log_id: string; kind: string; msg: string; created_at: string }[];
  stats: { trades: number; pnl: number; wins: number; open: number }; assets: { symbol: string; display: string; category: string }[];
};

const STRATS = [
  { value: "combo", label: "Combo plugins" },
  { value: "smc", label: "Smart Money" },
  { value: "ema_cross", label: "EMA Cross" },
  { value: "rsi", label: "RSI" },
  { value: "macd", label: "MACD" },
  { value: "bollinger", label: "Bollinger" },
];
const TFS = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];

function Step({ label, value, step, min, max, onChange, testID, suffix = "" }: {
  label: string; value: number; step: number; min: number; max: number; onChange: (v: number) => void; testID: string; suffix?: string;
}) {
  const styles = useStyles();
  const set = (v: number) => onChange(Math.round(Math.min(max, Math.max(min, v)) * 10) / 10);
  return (
    <View style={styles.step}>
      <Text style={styles.stepLabel}>{label}</Text>
      <View style={styles.stepRow}>
        <Pressable testID={`${testID}-minus`} style={styles.stepBtn} onPress={() => set(value - step)}>
          <Text style={styles.stepBtnText}>−</Text>
        </Pressable>
        <Text style={styles.stepValue} testID={`${testID}-value`}>
          {value}
          {suffix}
        </Text>
        <Pressable testID={`${testID}-plus`} style={styles.stepBtn} onPress={() => set(value + step)}>
          <Text style={styles.stepBtnText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function BotScreen() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bot"], queryFn: () => api<Resp>("/bot"), refetchInterval: 15000 });
  const [cfg, setCfg] = useState<Bot | null>(null);
  useEffect(() => {
    if (q.data && !cfg) setCfg(q.data.bot);
  }, [q.data, cfg]);

  const save = useMutation({
    mutationFn: (b: Bot) => api("/bot", { method: "PUT", body: b }),
    onSuccess: async (_r, b) => {
      const fresh = await qc.fetchQuery({ queryKey: ["bot"], queryFn: () => api<Resp>("/bot") });
      setCfg(fresh.bot);
      toast(b.enabled ? "Robô ativo — verifica sinais a cada minuto" : "Configuração guardada", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const runNow = useMutation({
    mutationFn: () => api<{ opened: number }>("/bot/run", { method: "POST" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["bot"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      toast(r.opened ? `${r.opened} nova(s) operação(ões) aberta(s)` : "Sem novos sinais na última vela fechada", r.opened ? "success" : "info");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const upd = (patch: Partial<Bot>) => setCfg((c) => (c ? { ...c, ...patch } : c));
  const toggleSym = (s: string) => cfg && upd({ symbols: cfg.symbols.includes(s) ? cfg.symbols.filter((x) => x !== s) : [...cfg.symbols, s] });
  const st = q.data?.stats;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="bot-screen">
      <View style={styles.header}>
        <Pressable testID="bot-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Robô Automático</Text>
      </View>
      {!cfg || !q.data ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} />
        </Center>
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
          <View style={[styles.hero, cfg.enabled && { borderColor: colors.success }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroTitle} testID="bot-status">
                {q.data.bot.enabled ? "A NEGOCIAR" : "PARADO"}
              </Text>
              <Text style={styles.muted}>
                {q.data.bot.last_run ? `Última verificação ${new Date(q.data.bot.last_run).toLocaleTimeString("pt-PT")}` : "Ainda não executou"}
              </Text>
            </View>
            <Switch
              testID="bot-enabled-switch"
              value={cfg.enabled}
              onValueChange={(v) => {
                haptic("medium");
                const next = { ...cfg, enabled: v };
                setCfg(next);
                save.mutate(next);
              }}
              trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
              thumbColor={colors.onBrandPrimary}
            />
          </View>
          {st && (
            <View style={styles.stats}>
              <Stat label="Trades do robô" value={String(st.trades)} />
              <Stat label="Abertas" value={String(st.open)} />
              <Stat label="Acerto" value={st.trades ? `${Math.round((st.wins / st.trades) * 100)}%` : "—"} />
              <Stat label="Resultado" value={money(st.pnl)} color={st.pnl >= 0 ? colors.success : colors.error} />
            </View>
          )}

          <Text style={styles.section}>Estratégia</Text>
          <ChipRow options={STRATS} value={cfg.strategy} onChange={(v) => upd({ strategy: v })} testID="bot-strategy" />
          <Text style={styles.section}>Timeframe</Text>
          <ChipRow options={TFS} value={cfg.tf} onChange={(v) => upd({ tf: v })} testID="bot-tf" />
          <ChipRow
            options={[
              { value: "trend", label: "Filtro de tendência EMA200" },
              { value: "mtf", label: "Confirmar TF superior" },
            ]}
            value={[...(cfg.trend_filter ? ["trend"] : []), ...(cfg.mtf ? ["mtf"] : [])]}
            onChange={(v) => (v === "trend" ? upd({ trend_filter: !cfg.trend_filter }) : upd({ mtf: !cfg.mtf }))}
            testID="bot-trend-filter"
          />
          <Text style={styles.section}>Ativos ({cfg.symbols.length})</Text>
          <ChipRow options={q.data.assets.map((a) => ({ value: a.symbol, label: a.display }))} value={cfg.symbols} onChange={toggleSym} testID="bot-assets" />
          {cfg.setups && cfg.setups.length > 0 && (
            <View style={{ paddingHorizontal: 16, gap: 8, marginBottom: 8 }} testID="bot-setups">
              <Text style={styles.muted}>
                Setups otimizados ({cfg.setups.length}) — cada ativo é operado em vários timeframes com a sua própria configuração:
              </Text>
              {cfg.setups.map((o, idx) => (
                <View key={`${o.symbol}-${o.tf}`} style={styles.override} testID={`bot-setup-${o.symbol}-${o.tf}`}>
                  <Text style={[styles.logMsg, { flex: 1 }]}>
                    {q.data!.assets.find((a) => a.symbol === o.symbol)?.display ?? o.symbol} · {o.tf.toUpperCase()} · {STRATS.find((x) => x.value === o.strategy)?.label} · SL {o.sl_atr}x · R:R {o.rr}
                    {o.mtf ? " · conf. TF superior" : ""}
                  </Text>
                  <Pressable
                    testID={`bot-setup-remove-${o.symbol}-${o.tf}`}
                    style={styles.overrideX}
                    onPress={() => {
                      const next = { ...cfg, setups: cfg.setups!.filter((_, i) => i !== idx) };
                      setCfg(next);
                      save.mutate(next);
                    }}
                  >
                    <Ionicons name="close" size={16} color={colors.onSurfaceSecondary} />
                  </Pressable>
                </View>
              ))}
            </View>
          )}
          <View style={styles.steps}>
            <Step label="Risco/trade" value={cfg.risk_pct} step={0.5} min={0.5} max={5} onChange={(v) => upd({ risk_pct: v })} testID="bot-risk" suffix="%" />
            <Step label="Stop (ATR)" value={cfg.sl_atr} step={0.5} min={0.5} max={5} onChange={(v) => upd({ sl_atr: v })} testID="bot-sl" suffix="x" />
          </View>
          <View style={styles.steps}>
            <Step label="Risco:Retorno" value={cfg.rr} step={0.5} min={0.5} max={6} onChange={(v) => upd({ rr: v })} testID="bot-rr" />
            <Step label="Máx. posições" value={cfg.max_positions} step={1} min={1} max={10} onChange={(v) => upd({ max_positions: v })} testID="bot-max" />
          </View>
          <View style={{ paddingHorizontal: 16, gap: 8 }}>
            <Button label="Guardar Configuração" onPress={() => save.mutate(cfg)} loading={save.isPending} testID="bot-save-button" />
            <Button label="Verificar sinais agora" variant="ghost" onPress={() => runNow.mutate()} loading={runNow.isPending} testID="bot-run-now-button" />
            <Text style={styles.note}>
              O robô abre e fecha posições na conta simulada sempre que a estratégia dá sinal numa vela fechada, com stop, alvo e break-even automáticos. Recomendado: testa a configuração no Backtest primeiro.
            </Text>
          </View>

          <Text style={styles.section}>Atividade</Text>
          <View style={{ paddingHorizontal: 16 }} testID="bot-logs">
            {q.data.logs.length === 0 && <Text style={styles.muted}>Sem atividade ainda.</Text>}
            {q.data.logs.map((l) => (
              <View key={l.log_id} style={styles.log}>
                <Ionicons
                  name={l.kind === "open" ? "arrow-forward-circle" : l.kind === "close" ? "checkmark-circle" : l.kind === "skip" ? "remove-circle" : "power"}
                  size={18}
                  color={l.kind === "open" ? colors.brandPrimary : l.kind === "close" ? colors.success : colors.muted}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.logMsg}>{l.msg}</Text>
                  <Text style={styles.logTime}>{new Date(l.created_at).toLocaleString("pt-PT")}</Text>
                </View>
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.stepLabel}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  hero: { margin: 16, marginBottom: 8, flexDirection: "row", alignItems: "center", backgroundColor: c.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: c.border, padding: 16 },
  heroTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 26, letterSpacing: 1 },
  stats: { flexDirection: "row", gap: 8, paddingHorizontal: 16 },
  stat: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8 },
  statValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", paddingHorizontal: 16, marginTop: 16 },
  steps: { flexDirection: "row", gap: 8, paddingHorizontal: 16, marginBottom: 8 },
  step: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8, gap: 4 },
  stepLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11, textAlign: "center" },
  stepRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepBtn: { width: 36, height: 36, borderRadius: 8, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  stepValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 18 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  override: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surfaceSecondary, borderRadius: 8, borderWidth: 1, borderColor: c.brandTertiary, paddingLeft: 12 },
  overrideX: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  log: { flexDirection: "row", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.divider, alignItems: "flex-start" },
  logMsg: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
  logTime: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
}));
