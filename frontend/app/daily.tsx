import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import Animated, { FadeIn } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt, money, streamSSE } from "@/src/api";
import { MarkdownLite } from "@/src/components/markdown";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type BotStats = { trades: number; wins: number; winrate: number; pnl: number; ai_rejected: number };
type DayStats = { date: string; hfx: BotStats; bot: BotStats; total_pnl: number; total_trades: number };
type Adj = { scope: "hfx" | "bot"; field: string; label: string; from: string; to: string; reason: string; applied?: boolean };
type Summary = { date: string; text: string; stats: DayStats; created_at: string; adjustments?: Adj[] };

function isoDay(offset: number) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}
function dayLabel(iso: string) {
  if (iso === isoDay(0)) return "Hoje";
  if (iso === isoDay(1)) return "Ontem";
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}
const DAYS = Array.from({ length: 7 }, (_, i) => isoDay(i));

export default function Daily() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [date, setDate] = useState(DAYS[0]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const stats = useQuery({ queryKey: ["daily-stats", date], queryFn: () => api<DayStats>(`/ai/daily-stats?date=${date}`) });
  const list = useQuery({ queryKey: ["daily-summaries"], queryFn: () => api<Summary[]>("/ai/daily-summaries") });
  const saved = list.data?.find((s) => s.date === date);

  useEffect(() => {
    abort.current?.abort();
    setText("");
  }, [date]);
  useEffect(() => () => abort.current?.abort(), []);

  const generate = async () => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setText("");
    setLoading(true);
    try {
      await streamSSE("/ai/daily-summary", { date }, (t) => setText((a) => a + t), ctrl.signal);
      qc.invalidateQueries({ queryKey: ["daily-summaries"] });
    } catch (e: any) {
      if (e?.name !== "AbortError") toast(e.message ?? "Falha no resumo IA", "error");
    } finally {
      setLoading(false);
    }
  };
  const s = stats.data;
  const shown = text || saved?.text || "";
  const hasTrades = !!s && s.total_trades > 0;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="daily-screen">
      <View style={styles.header}>
        <Pressable testID="daily-back-button" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Resumo Diário IA</Text>
      </View>
      <ScrollView
        contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
        refreshControl={
          <RefreshControl
            refreshing={stats.isRefetching || list.isRefetching}
            onRefresh={() => {
              stats.refetch();
              list.refetch();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        <View style={{ marginTop: 12 }}>
          <ChipRow options={DAYS.map((d) => ({ value: d, label: dayLabel(d) }))} value={date} onChange={setDate} testID="daily-day" />
        </View>
        <View style={{ padding: 16, gap: 12 }}>
          {!s ? (
            <ActivityIndicator color={colors.brandPrimary} />
          ) : (
            <View style={styles.stats} testID="daily-stats">
              <Stat label="Resultado" value={money(s.total_pnl)} color={s.total_pnl >= 0 ? colors.success : colors.error} />
              <BotCard name="Robô HFX" b={s.hfx} testID="daily-hfx" />
              <BotCard name="Robô principal" b={s.bot} testID="daily-bot" />
            </View>
          )}
          <View style={styles.aiCard} testID="daily-summary-card">
            <View style={styles.aiHead}>
              <Ionicons name="sparkles" size={18} color={colors.brandPrimary} />
              <Text style={[styles.cardTitle, { flex: 1 }]}>Relatório · {dayLabel(date)}</Text>
            </View>
            {shown ? (
              <Animated.View entering={FadeIn} style={{ gap: 6 }}>
                {!text && saved && <Text style={styles.muted}>Gerado em {new Date(saved.created_at).toLocaleString("pt-PT")}</Text>}
                <MarkdownLite text={shown} testID="daily-summary-text" />
              </Animated.View>
            ) : (
              <Text style={styles.muted}>
                {hasTrades
                  ? "Toca em «Gerar» para a IA analisar os resultados deste dia e sugerir os ajustes para amanhã."
                  : "Os robôs não fecharam operações neste dia — não há nada para resumir."}
              </Text>
            )}
            <Button
              label={shown ? "Gerar de novo" : "Gerar Resumo"}
              onPress={generate}
              loading={loading}
              disabled={!hasTrades}
              testID="daily-generate-button"
            />
          </View>

          {saved && !loading && <Adjustments date={date} items={saved.adjustments ?? []} />}

          <Text style={styles.section}>Histórico</Text>
          {list.isLoading ? (
            <ActivityIndicator color={colors.brandPrimary} />
          ) : !list.data?.length ? (
            <Text style={styles.muted}>Ainda não geraste nenhum resumo.</Text>
          ) : (
            list.data.map((h) => (
              <Pressable key={h.date} style={[styles.hist, h.date === date && { borderColor: colors.brandPrimary }]} onPress={() => setDate(h.date)} testID={`daily-history-${h.date}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.histTitle}>{dayLabel(h.date)} · {h.date}</Text>
                  <Text style={styles.muted}>
                    {h.stats.total_trades} operações · {money(h.stats.total_pnl)}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))
          )}
        </View>
      </ScrollView>
    </View>
  );
}

function Adjustments({ date, items }: { date: string; items: Adj[] }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const pending = items.map((a, i) => (a.applied ? -1 : i)).filter((i) => i >= 0);
  const [sel, setSel] = useState<number[]>(pending);
  useEffect(() => setSel(items.map((a, i) => (a.applied ? -1 : i)).filter((i) => i >= 0)), [items]);
  const apply = useMutation({
    mutationFn: () => api<{ applied: number; skipped: number }>("/ai/daily-summary/apply", { method: "POST", body: { date, ids: sel } }),
    onSuccess: (r) => {
      haptic("medium");
      toast(r.skipped ? `${r.applied} ajuste(s) aplicado(s) · ${r.skipped} já não se aplicava(m)` : `${r.applied} ajuste(s) aplicado(s) aos robôs`, "success");
      qc.invalidateQueries({ queryKey: ["daily-summaries"] });
      qc.invalidateQueries({ queryKey: ["bot"] });
      qc.invalidateQueries({ queryKey: ["hfx-bot"] });
      qc.invalidateQueries({ queryKey: ["plugins"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const toggle = (i: number) => setSel((s) => (s.includes(i) ? s.filter((x) => x !== i) : [...s, i]));
  return (
    <View style={{ gap: 8 }} testID="daily-adjustments">
      <Text style={styles.section}>Ajustes sugeridos para amanhã</Text>
      {items.length === 0 ? (
        <Text style={styles.muted}>A IA não sugeriu alterações de configuração para este dia.</Text>
      ) : (
        <>
          {items.map((a, i) => {
            const on = sel.includes(i);
            return (
              <Pressable
                key={i}
                disabled={a.applied}
                onPress={() => toggle(i)}
                style={[styles.adj, on && { borderColor: colors.brandPrimary }, a.applied && { opacity: 0.6 }]}
                testID={`daily-adj-${i}`}
              >
                <Ionicons
                  name={a.applied ? "checkmark-done-circle" : on ? "checkbox" : "square-outline"}
                  size={22}
                  color={a.applied ? colors.success : on ? colors.brandPrimary : colors.muted}
                />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.histTitle}>
                    {a.scope === "hfx" ? "HFX" : "Principal"} · {a.label}
                  </Text>
                  <Text style={styles.adjChange}>
                    {a.from} → <Text style={{ color: colors.brandPrimary }}>{a.to}</Text>
                  </Text>
                  {!!a.reason && <Text style={styles.muted}>{a.reason}</Text>}
                  {a.applied && <Text style={[styles.muted, { color: colors.success }]}>Aplicado</Text>}
                </View>
              </Pressable>
            );
          })}
          {pending.length > 0 && (
            <Button
              label={`Aplicar ${sel.length} ajuste(s)`}
              onPress={() => apply.mutate()}
              loading={apply.isPending}
              disabled={sel.length === 0}
              testID="daily-apply-button"
            />
          )}
        </>
      )}
    </View>
  );
}

function BotCard({ name, b, testID }: { name: string; b: BotStats; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.stat} testID={testID}>
      <Text style={styles.muted}>{name}</Text>
      {b.trades ? (
        <>
          <Text style={[styles.statValue, { color: b.pnl >= 0 ? colors.success : colors.error }]} numberOfLines={1} adjustsFontSizeToFit>
            {money(b.pnl)}
          </Text>
          <Text style={styles.muted}>
            {b.trades} ops · {fmt(b.winrate, 0)}%{b.ai_rejected ? ` · IA ✕${b.ai_rejected}` : ""}
          </Text>
        </>
      ) : (
        <Text style={styles.statValue}>—</Text>
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
  stat: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8, gap: 2 },
  statValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  aiCard: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 16, gap: 12 },
  aiHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  hist: { flexDirection: "row", alignItems: "center", backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  histTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  adj: { flexDirection: "row", gap: 10, alignItems: "flex-start", backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  adjChange: { color: c.onSurfaceTertiary, fontFamily: fonts.display, fontSize: 15 },
}));
