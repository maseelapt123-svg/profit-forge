import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, money } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Center, ChipRow, Segmented, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Bot = {
  enabled: boolean; source: "otc" | "real"; pairs: string[]; expiry: number; amount: number; min_winrate: number;
  daily_stop: number; daily_target: number; max_per_hour: number;
  strategy: "auto" | "plugins" | "optimized"; min_votes: number; ai_filter: boolean; setups: Record<string, { rule: string; expiry: number; label?: string }>;
};
type Resp = { bot: Bot; logs: { log_id: string; kind: string; msg: string; created_at: string }[]; today: number; pairs: { pair: string; name: string }[] };

function Step({ label, value, step, min, max, onChange, testID, fmtv }: {
  label: string; value: number; step: number; min: number; max: number; onChange: (v: number) => void; testID: string; fmtv?: (v: number) => string;
}) {
  const styles = useStyles();
  const set = (v: number) => onChange(Math.min(max, Math.max(min, v)));
  return (
    <View style={styles.step}>
      <Text style={styles.stepLabel}>{label}</Text>
      <View style={styles.stepRow}>
        <Pressable testID={`${testID}-minus`} style={styles.stepBtn} onPress={() => set(value - step)}>
          <Text style={styles.stepBtnText}>−</Text>
        </Pressable>
        <Text style={styles.stepValue} testID={`${testID}-value`}>
          {fmtv ? fmtv(value) : value}
        </Text>
        <Pressable testID={`${testID}-plus`} style={styles.stepBtn} onPress={() => set(value + step)}>
          <Text style={styles.stepBtnText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function HfxBot() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["hfx-bot"], queryFn: () => api<Resp>("/hfx/bot"), refetchInterval: 5000 });
  const [cfg, setCfg] = useState<Bot | null>(null);
  useEffect(() => {
    if (q.data && !cfg) setCfg(q.data.bot);
  }, [q.data, cfg]);
  const save = useMutation({
    mutationFn: (b: Bot) => api("/hfx/bot", { method: "PUT", body: b }),
    onSuccess: async (_r, b) => {
      const fresh = await qc.fetchQuery({ queryKey: ["hfx-bot"], queryFn: () => api<Resp>("/hfx/bot") });
      setCfg(fresh.bot);
      toast(b.enabled ? "Robô HFX ativo — entra a cada nova vela com sinal válido" : "Configuração guardada", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const upd = (p: Partial<Bot>) => setCfg((c) => (c ? { ...c, ...p } : c));
  const live = q.data?.bot;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="hfx-bot-screen">
      <View style={styles.header}>
        <Pressable testID="hfx-bot-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Robô HFX</Text>
      </View>
      {!cfg || !q.data ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} />
        </Center>
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}>
          <View style={[styles.hero, live?.enabled && { borderColor: colors.success }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.heroTitle} testID="hfx-bot-status">
                {live?.enabled ? "A OPERAR" : "PARADO"}
              </Text>
              <Text style={[styles.muted, { color: q.data.today >= 0 ? colors.success : colors.error }]} testID="hfx-bot-today">
                Hoje: {q.data.today >= 0 ? "+" : ""}
                {money(q.data.today)}
              </Text>
            </View>
            <Switch
              testID="hfx-bot-enabled-switch"
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
          <Text style={styles.section}>Estratégia</Text>
          <View style={{ paddingHorizontal: 16, gap: 8, marginTop: 8 }}>
            <Segmented
              options={[
                { value: "optimized", label: "Otimizada" },
                { value: "plugins", label: "Confluência" },
                { value: "auto", label: "Auto" },
              ]}
              value={cfg.strategy}
              onChange={(v) => upd({ strategy: v })}
              testID="hfx-bot-strategy"
            />
            <Text style={styles.note}>
              {cfg.strategy === "optimized"
                ? "Usa, em cada par, a estratégia validada no otimizador (só opera os pares com setup)."
                : cfg.strategy === "plugins"
                  ? `Entra quando ${cfg.min_votes}+ plugins ativos concordam na mesma vela.`
                  : "Escolhe em cada vela o plugin com melhor acerto recente."}
            </Text>
            {cfg.strategy === "optimized" && cfg.source === "otc" && (
              <Text style={styles.warnText} testID="hfx-bot-otc-warning">
                Atenção: a estratégia foi validada em forex real. No feed OTC simulado essa vantagem não se transfere — usa «Forex real» (seg–sex).
              </Text>
            )}
            {cfg.strategy === "optimized" && (
              <View style={{ gap: 6 }} testID="hfx-bot-setups">
                {Object.keys(cfg.setups ?? {}).length === 0 && (
                  <Button label="Abrir Otimizador" variant="ghost" onPress={() => router.push("/hfx-optimizer")} testID="hfx-bot-open-optimizer" />
                )}
                {Object.entries(cfg.setups ?? {}).map(([k, v]) => (
                  <View key={k} style={styles.setup} testID={`hfx-bot-setup-${k}`}>
                    <Text style={[styles.logMsg, { flex: 1 }]}>
                      {q.data!.pairs.find((p) => p.pair === k.replace("_", "."))?.name ?? k} · {v.expiry}m · {v.label ?? v.rule}
                    </Text>
                    <Pressable
                      testID={`hfx-bot-setup-remove-${k}`}
                      style={styles.setupX}
                      onPress={() => {
                        const { [k]: _omit, ...rest } = cfg.setups;
                        const next = { ...cfg, setups: rest };
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
          </View>
          <View style={{ paddingHorizontal: 16, gap: 8, marginTop: 12 }}>
            <Segmented
              options={[
                { value: "otc", label: "OTC 24/7" },
                { value: "real", label: "Forex real" },
              ]}
              value={cfg.source}
              onChange={(v) => upd({ source: v })}
              testID="hfx-bot-source"
            />
            <Segmented
              options={[
                { value: "1", label: "Expiração 1 min" },
                { value: "3", label: "Expiração 3 min" },
              ]}
              value={String(cfg.expiry)}
              onChange={(v) => upd({ expiry: Number(v) })}
              testID="hfx-bot-expiry"
            />
          </View>
          <Text style={styles.section}>Pares ({cfg.pairs.length})</Text>
          <ChipRow
            options={q.data.pairs.map((p) => ({ value: p.pair, label: p.name + (cfg.source === "otc" ? " OTC" : "") }))}
            value={cfg.pairs}
            onChange={(v) => upd({ pairs: cfg.pairs.includes(v) ? cfg.pairs.filter((x) => x !== v) : [...cfg.pairs, v] })}
            testID="hfx-bot-pairs"
          />
          <View style={styles.steps}>
            <Step label="Valor/entrada" value={cfg.amount} step={5} min={1} max={1000} onChange={(v) => upd({ amount: v })} testID="hfx-bot-amount" fmtv={(v) => `$${v}`} />
            <Step label="Acerto mínimo" value={cfg.min_winrate} step={1} min={50} max={90} onChange={(v) => upd({ min_winrate: v })} testID="hfx-bot-minwr" fmtv={(v) => `${v}%`} />
          </View>
          <View style={styles.steps}>
            <Step label="Stop diário" value={cfg.daily_stop} step={10} min={10} max={10000} onChange={(v) => upd({ daily_stop: v })} testID="hfx-bot-stop" fmtv={(v) => `$${v}`} />
            <Step label="Meta diária" value={cfg.daily_target} step={10} min={10} max={10000} onChange={(v) => upd({ daily_target: v })} testID="hfx-bot-target" fmtv={(v) => `$${v}`} />
          </View>
          <View style={styles.steps}>
            <Step label="Máx. entradas/hora" value={cfg.max_per_hour} step={1} min={1} max={60} onChange={(v) => upd({ max_per_hour: v })} testID="hfx-bot-maxhour" />
            <Step label="Votos confluência" value={cfg.min_votes} step={1} min={1} max={7} onChange={(v) => upd({ min_votes: v })} testID="hfx-bot-votes" />
          </View>
          <View style={styles.aiRow}>
            <Ionicons name="sparkles" size={20} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.aiTitle}>Filtro IA</Text>
              <Text style={styles.muted}>A IA revê cada sinal (tendência, RSI, volatilidade, estatística) e só deixa entrar se confirmar.</Text>
            </View>
            <Switch
              testID="hfx-bot-ai-filter-switch"
              value={cfg.ai_filter}
              onValueChange={(v) => upd({ ai_filter: v })}
              trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
              thumbColor={colors.onBrandPrimary}
            />
          </View>
          <View style={{ paddingHorizontal: 16, gap: 8 }}>
            <Button label="Guardar Configuração" onPress={() => save.mutate(cfg)} loading={save.isPending} testID="hfx-bot-save-button" />
            <Text style={styles.note}>
              Em cada vela de 1 minuto fechada o robô avalia a estratégia escolhida. Só entra se ela der sinal e o acerto recente for superior ao mínimo definido e ao ponto de equilíbrio do payout. Para sozinho ao atingir o stop ou a meta diária. Valor fixo por entrada, sem martingale.
            </Text>
          </View>
          <View style={{ paddingHorizontal: 16, marginTop: 8 }}>
            <Button label="Ver Análise de Perdas" variant="ghost" onPress={() => router.push({ pathname: "/analysis", params: { scope: "hfx" } })} testID="hfx-bot-open-analysis" />
          </View>
          <Text style={styles.section}>Atividade</Text>
          <View style={{ paddingHorizontal: 16 }} testID="hfx-bot-logs">
            {q.data.logs.length === 0 && <Text style={styles.muted}>Sem atividade ainda.</Text>}
            {q.data.logs.map((l) => (
              <View key={l.log_id} style={styles.log}>
                <Ionicons
                  name={l.kind === "open" ? "arrow-forward-circle" : l.kind === "close" ? "checkmark-circle" : l.kind === "ai" ? "sparkles" : "power"}
                  size={18}
                  color={l.kind === "open" ? colors.brandPrimary : l.kind === "close" ? colors.success : colors.muted}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.logMsg}>{l.msg}</Text>
                  <Text style={styles.muted}>{new Date(l.created_at).toLocaleString("pt-PT")}</Text>
                </View>
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  hero: { margin: 16, flexDirection: "row", alignItems: "center", backgroundColor: c.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: c.border, padding: 16 },
  heroTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 26, letterSpacing: 1 },
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", paddingHorizontal: 16, marginTop: 16 },
  steps: { flexDirection: "row", gap: 8, paddingHorizontal: 16, marginBottom: 8 },
  step: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 8, gap: 4 },
  stepLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11, textAlign: "center" },
  stepRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepBtn: { width: 44, height: 44, borderRadius: 8, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  stepValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 18 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  aiRow: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: 16, marginBottom: 12, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12 },
  aiTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  warnText: { color: c.warning, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  setup: { flexDirection: "row", alignItems: "center", backgroundColor: c.surfaceSecondary, borderRadius: 8, borderWidth: 1, borderColor: c.success, paddingLeft: 12 },
  setupX: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  log: { flexDirection: "row", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.divider, alignItems: "flex-start" },
  logMsg: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
}));
