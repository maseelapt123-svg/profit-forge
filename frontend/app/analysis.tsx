import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Switch, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money, streamSSE } from "@/src/api";
import { MarkdownLite } from "@/src/components/markdown";
import { useToast } from "@/src/components/toast";
import { Button, Center, Segmented } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Problem = { kind: string; label: string; n: number; winrate: number; text: string; pnl?: number; pf?: number };
type Resp = {
  trades: number; winrate: number; losses: number; breakeven?: number; pnl?: number; problems: Problem[];
  recent_losses: any[]; fixes: Record<string, any>; auto_fix: boolean;
};

const RULE_NAMES: Record<string, string> = {
  bb_rsi: "BB+RSI", rsi2: "RSI(2)", stoch: "Estocástico", ema_mom: "Momentum EMA", engolfo: "Engolfo",
  pinbar: "Pin bar", streak: "Sequência", confluence: "Confluência",
};
const REASONS: Record<string, string> = { stop_loss: "stop", take_profit: "alvo", signal: "sinal contrário", manual: "manual" };
function prettyKey(k: string): string {
  const [sym, rest = ""] = k.split("|");
  const s = sym.replace("=X", "").replace("-USD", "/USD");
  const pairName = s.length === 6 ? `${s.slice(0, 3)}/${s.slice(3)}` : s;
  const r = rest.split("+").map((x) => RULE_NAMES[x] ?? x.toUpperCase()).join(" + ");
  return `${pairName} ${r}`.trim();
}

function fixList(scope: "hfx" | "bot", f: Record<string, any>): string[] {
  const out: string[] = [];
  if (f.hours?.length) out.push(`Horas bloqueadas: ${f.hours.map((h: number) => `${h}h`).join(", ")} (UTC)`);
  if (scope === "hfx") {
    if (f.pair_rules?.length) out.push(`Em quarentena (24h): ${f.pair_rules.map(prettyKey).join(", ")}`);
    if (f.trend_align) out.push("Só entra a favor da tendência");
    if (f.skip_low_vol) out.push("Ignora velas de volatilidade baixa");
    if (f.skip_high_vol) out.push("Ignora velas de volatilidade extrema");
  } else {
    if (f.paused?.length) out.push(`Setups em quarentena: ${f.paused.map(prettyKey).join(", ")}`);
    if (f.force_mtf) out.push("Confirmação do timeframe superior obrigatória");
    if (f.widen_stop) out.push("Stop 0,5x ATR mais largo");
  }
  return out;
}

export default function Analysis() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ scope?: string }>();
  const [scope, setScope] = useState<"hfx" | "bot">(params.scope === "bot" ? "bot" : "hfx");
  const path = scope === "hfx" ? "/hfx/analysis?scope=bot" : "/bot/analysis";
  const base = scope === "hfx" ? "/hfx/analysis" : "/bot/analysis";
  const q = useQuery({ queryKey: ["analysis", scope], queryFn: () => api<Resp>(path), refetchInterval: 15000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["analysis", scope] });
  const apply = useMutation({
    mutationFn: () => api(`${base}/apply`, { method: "POST" }),
    onSuccess: () => {
      toast("Correções aplicadas ao robô", "success");
      refresh();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const reset = useMutation({
    mutationFn: () => api(`${base}/reset`, { method: "POST" }),
    onSuccess: () => {
      toast("Correções removidas", "info");
      refresh();
    },
  });
  const auto = useMutation({
    mutationFn: (enabled: boolean) => api("/analysis/auto-fix", { method: "PUT", body: { scope, enabled } }),
    onSuccess: refresh,
  });
  const d = q.data;
  const fixes = d ? fixList(scope, d.fixes) : [];

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="analysis-screen">
      <View style={styles.header}>
        <Pressable testID="analysis-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Análise de Perdas</Text>
      </View>
      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <Segmented
          options={[
            { value: "hfx", label: "HFX" },
            { value: "bot", label: "Robô principal" },
          ]}
          value={scope}
          onChange={setScope}
          testID="analysis-scope"
        />
      </View>
      {q.isLoading || !d ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} />
        </Center>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={refresh} tintColor={colors.brandPrimary} />}
        >
          <View style={styles.stats}>
            <Stat label="Operações" value={String(d.trades)} />
            <Stat label="Perdas" value={String(d.losses)} color={colors.error} />
            <Stat label="Acerto" value={d.trades ? `${fmt(d.winrate, 0)}%` : "—"} />
            {d.breakeven !== undefined ? <Stat label="Mínimo" value={`${fmt(d.breakeven, 1)}%`} /> : <Stat label="Resultado" value={money(d.pnl ?? 0)} color={(d.pnl ?? 0) >= 0 ? colors.success : colors.error} />}
          </View>
          <View style={styles.autoRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.autoTitle}>Correção automática</Text>
              <Text style={styles.muted}>
                {scope === "hfx" ? "Analisa as perdas do robô HFX (últimas 24h) a cada 10 min e ajusta-o sozinho" : "Analisa as perdas do robô (últimos 14 dias) e ajusta-o sozinho"}
              </Text>
            </View>
            <Switch
              testID="analysis-auto-fix-switch"
              value={d.auto_fix}
              onValueChange={(v) => auto.mutate(v)}
              trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
              thumbColor={colors.onBrandPrimary}
            />
          </View>

          <Text style={styles.section}>Diagnóstico</Text>
          {d.trades < 6 ? (
            <Text style={styles.muted} testID="analysis-not-enough">
              Ainda há poucas operações fechadas ({d.trades}). A análise começa a partir de 6 operações por padrão.
            </Text>
          ) : d.problems.length === 0 ? (
            <Text style={[styles.muted, { color: colors.success }]} testID="analysis-no-problems">
              Nenhum padrão de perda abaixo do mínimo encontrado. Continua a monitorizar.
            </Text>
          ) : (
            d.problems.map((p, i) => (
              <Animated.View key={i} entering={FadeInDown.delay(i * 40)} style={styles.problem} testID={`analysis-problem-${i}`}>
                <View style={styles.probHead}>
                  <Ionicons name="alert-circle" size={18} color={colors.error} />
                  <Text style={styles.probMeta}>
                    {p.n} operações · {fmt(p.winrate, 0)}% acerto{p.pf !== undefined && p.kind === "setup" ? ` · PF ${fmt(p.pf, 2)}` : ""}
                  </Text>
                </View>
                <Text style={styles.probText}>{p.text}</Text>
              </Animated.View>
            ))
          )}

          <Text style={styles.section}>Correções ativas no robô</Text>
          {fixes.length ? (
            fixes.map((f, i) => (
              <View key={i} style={styles.fix} testID={`analysis-fix-${i}`}>
                <Ionicons name="shield-checkmark" size={16} color={colors.success} />
                <Text style={styles.fixText}>{f}</Text>
              </View>
            ))
          ) : (
            <Text style={styles.muted}>Nenhuma correção ativa.</Text>
          )}
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Button label="Corrigir Agora" onPress={() => apply.mutate()} loading={apply.isPending} style={{ flex: 1.4 }} testID="analysis-apply-button" />
            <Button label="Limpar" variant="ghost" onPress={() => reset.mutate()} loading={reset.isPending} style={{ flex: 1 }} testID="analysis-reset-button" />
          </View>

          <AiReview scope={scope} enough={d.trades >= 3} />

          {!!d.recent_losses.length && <Text style={styles.section}>Últimas perdas</Text>}
          {d.recent_losses.map((l, i) => (
            <View key={i} style={styles.loss}>
              <Text style={styles.lossTitle}>
                {l.display} {scope === "hfx" ? `${l.direction === "CALL" ? "SOBE" : "DESCE"} ${l.expiry}m · ${l.rule}` : `${l.tf?.toUpperCase() ?? ""} ${l.side === "BUY" ? "LONG" : "SHORT"} · ${REASONS[l.reason] ?? l.reason ?? ""}`}
              </Text>
              <Text style={styles.muted}>
                {l.ctx
                  ? scope === "hfx"
                    ? `${l.ctx.aligned ? "a favor" : "contra"} a tendência · RSI ${l.ctx.rsi} · volatilidade ${l.ctx.vol_pct}% · ${l.ctx.hour}h UTC`
                    : `${l.ctx.htf_aligned === false ? "contra" : l.ctx.htf_aligned ? "a favor do" : "sem"} TF superior · ${l.ctx.hour}h UTC`
                  : "sem contexto"}{" "}
                · {money(l.profit ?? l.pnl)}
              </Text>
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

function AiReview({ scope, enough }: { scope: "hfx" | "bot"; enough: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const last = useQuery({ queryKey: ["ai-review", scope], queryFn: () => api<{ text: string; created_at: string | null }>(`/ai/loss-review?scope=${scope}`) });
  useEffect(() => {
    abort.current?.abort();
    setText("");
  }, [scope]);
  useEffect(() => () => abort.current?.abort(), []);
  const run = async () => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setText("");
    setLoading(true);
    try {
      await streamSSE("/ai/loss-review", { scope }, (t) => setText((a) => a + t), ctrl.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") toast(e.message ?? "Falha na análise IA", "error");
    } finally {
      setLoading(false);
    }
  };
  const shown = text || last.data?.text || "";
  return (
    <View style={styles.aiCard} testID="ai-review-card">
      <View style={styles.aiHead}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flex: 1 }}>
          <Ionicons name="sparkles" size={18} color={colors.brandPrimary} />
          <Text style={styles.autoTitle}>Coach IA</Text>
        </View>
        <Pressable testID="ai-review-button" onPress={run} disabled={loading || !enough} style={[styles.aiBtn, !enough && { opacity: 0.5 }]}>
          {loading ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Text style={styles.aiBtnText}>{shown ? "Reanalisar" : "Explicar perdas"}</Text>}
        </Pressable>
      </View>
      {shown ? (
        <>
          {!text && last.data?.created_at && <Text style={styles.muted}>Última análise: {new Date(last.data.created_at).toLocaleString("pt-PT")}</Text>}
          <MarkdownLite text={shown} testID="ai-review-text" />
        </>
      ) : (
        <Text style={styles.muted}>
          {enough
            ? "A IA lê as perdas e a configuração do robô, explica porque está a perder e diz exatamente o que mudar."
            : "O Coach IA fica disponível a partir de 3 operações fechadas."}
        </Text>
      )}
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.muted}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  stats: { flexDirection: "row", gap: 8 },
  stat: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8 },
  statValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  autoRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12 },
  aiCard: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16, gap: 10 },
  aiHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  aiBtn: { height: 36, minWidth: 110, paddingHorizontal: 14, borderRadius: 999, backgroundColor: c.brandSoft, alignItems: "center", justifyContent: "center" },
  aiBtnText: { color: c.brandPrimary, fontFamily: fonts.displaySemi, fontSize: 14 },
  autoTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  problem: { backgroundColor: c.errorSoft, borderRadius: 12, borderWidth: 1, borderColor: c.error, padding: 12, gap: 6 },
  probHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  probMeta: { color: c.error, fontFamily: fonts.displaySemi, fontSize: 13 },
  probText: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  fix: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.successSoft, borderRadius: 8, padding: 10 },
  fixText: { flex: 1, color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
  loss: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.divider, gap: 2 },
  lossTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
}));
