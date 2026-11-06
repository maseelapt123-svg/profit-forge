import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, money } from "@/src/api";
import { STRATS } from "@/src/strategies";
import { C20Optimize } from "@/src/components/c20-optimize";
import { ConfluencePanel } from "@/src/components/confluence-panel";
import { Confirm12Panel } from "@/src/components/confirm12-panel";
import { LiveAccount } from "@/src/components/live-account";
import { MtAccount } from "@/src/components/mt-account";
import { OptimizeAll } from "@/src/components/optimize-all";
import { useToast } from "@/src/components/toast";
import { Button, Center, ChipRow, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Setup = { symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean };
type Bot = { setups?: Setup[]; mtf: boolean; ai_filter: boolean; conf_votes: number; conf_score: number;
  c12_enabled: boolean; c12_min: number; c12_max_positions: number; c12_tf: string;
  c20_enabled: boolean; c20_min: number; c20_max_positions: number; c20_tf: string; c20_rr: number; c20_ptp_r: number;
  c20_pairs?: { symbol: string; tf: string; rr: number; min: number; enabled: boolean; test: number | null }[];
  c12_pairs?: { symbol: string; tf: string; rr: number; min: number; enabled: boolean; test: number | null }[];
  ptp_enabled: boolean; breakeven_enabled?: boolean; ptp_pct: number; ptp_r: number; live_mode: "paper" | "binance" | "metatrader"; live_max_usd: number; live_until?: string; c_min_return?: number; weekly_reopt?: boolean; last_reopt?: string;
  mt_max_lots: number; mt_suffix: string; trend_filter: boolean; enabled: boolean; symbols: string[]; tf: string; strategy: string; risk_pct: number; sl_atr: number; rr: number; max_positions: number; last_run?: string };
type Resp = {
  bot: Bot; logs: { log_id: string; kind: string; msg: string; created_at: string }[];
  stats: { trades: number; pnl: number; wins: number; open: number }; assets: { symbol: string; display: string; category: string }[];
};

const TFS = [
  { value: "1m", label: "1m" },
  { value: "2m", label: "2m" },
  { value: "3m", label: "3m" },
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
          <OptimizeAll
            onDone={async () => {
              const fresh = await qc.fetchQuery({ queryKey: ["bot"], queryFn: () => api<Resp>("/bot") });
              setCfg(fresh.bot);
            }}
          />

          <Text style={styles.section}>Estratégia</Text>
          <ChipRow options={STRATS} value={cfg.strategy} onChange={(v) => upd({ strategy: v })} testID="bot-strategy" />
          {cfg.strategy === "confluence" && (
            <View testID="bot-confluence">
              <Text style={[styles.note, { paddingHorizontal: 16, marginBottom: 8 }]}>
                Cada plugin ativo vota e vale o seu acerto recente. Só entra quando o mínimo de plugins concorda, nenhum discorda, a média dos pesos atinge a pontuação e o preço está a favor da EMA200.
              </Text>
              <View style={styles.steps}>
                <Step label="Mín. plugins" value={cfg.conf_votes} step={1} min={1} max={10} onChange={(v) => upd({ conf_votes: v })} testID="bot-conf-votes" />
                <Step label="Pontuação mín." value={cfg.conf_score} step={5} min={40} max={90} onChange={(v) => upd({ conf_score: v })} testID="bot-conf-score" suffix="%" />
              </View>
              {cfg.symbols[0] && <ConfluencePanel symbol={cfg.symbols[0]} tf={cfg.tf} votes={cfg.conf_votes} score={cfg.conf_score} />}
            </View>
          )}
          <View style={styles.c12Card} testID="bot-c12">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.c12Title}>12 Confirmações · entradas extra</Text>
                <Text style={styles.note}>Corre à parte da estratégia principal, sem limite de posições. Só entra quando o mínimo de confirmações concorda.</Text>
              </View>
              <Switch
                testID="bot-c12-switch"
                value={cfg.c12_enabled}
                onValueChange={(v) => upd({ c12_enabled: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
          </View>
          {cfg.c12_enabled && (
            <>
              <Text style={[styles.note, { paddingHorizontal: 16, marginBottom: 4 }]}>Timeframe das entradas 12C (recomendado 1H ou superior)</Text>
              <ChipRow options={TFS.filter((t) => !["1m", "2m", "3m"].includes(t.value))} value={cfg.c12_tf} onChange={(v) => upd({ c12_tf: v })} testID="bot-c12-tf" />
              <View style={styles.steps}>
                <Step label="Mín. confirmações" value={cfg.c12_min} step={1} min={6} max={12} onChange={(v) => upd({ c12_min: v })} testID="bot-c12-min" suffix="/12" />
              </View>
              {cfg.symbols[0] && <Confirm12Panel symbol={cfg.symbols[0]} tf={cfg.c12_tf} min={cfg.c12_min} />}
              <C20Optimize
                kind="c12"
                pairs={cfg.c12_pairs ?? []}
                onDone={async () => {
                  const fresh = await qc.fetchQuery({ queryKey: ["bot"], queryFn: () => api<Resp>("/bot") });
                  setCfg((c) => (c ? { ...c, c12_pairs: fresh.bot.c12_pairs } : fresh.bot));
                }}
              />
            </>
          )}
          <View style={styles.c12Card} testID="bot-c20">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.c12Title}>Sniper 20 · confluência de 20 ferramentas</Text>
                <Text style={styles.note}>Estratégia independente: só entra com muitas das 20 ferramentas alinhadas e procura alvos grandes (R:R 1:5 ou 1:10). Acerta menos vezes, mas cada ganho vale 5–10x o risco.</Text>
              </View>
              <Switch
                testID="bot-c20-switch"
                value={cfg.c20_enabled}
                onValueChange={(v) => upd({ c20_enabled: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
          </View>
          {cfg.c20_enabled && (
            <>
              <Text style={[styles.note, { paddingHorizontal: 16, marginBottom: 4 }]}>Risco:Retorno</Text>
              <ChipRow options={[{ value: "5", label: "1:5" }, { value: "10", label: "1:10" }]} value={String(cfg.c20_rr)} onChange={(v) => upd({ c20_rr: Number(v) })} testID="bot-c20-rr" />
              <Text style={[styles.note, { paddingHorizontal: 16, marginBottom: 4 }]}>Timeframe Sniper 20</Text>
              <ChipRow options={TFS.filter((t) => !["1m", "2m", "3m"].includes(t.value))} value={cfg.c20_tf} onChange={(v) => upd({ c20_tf: v })} testID="bot-c20-tf" />
              <View style={styles.steps}>
                <Step label="Mín. ferramentas" value={cfg.c20_min} step={1} min={10} max={20} onChange={(v) => upd({ c20_min: v })} testID="bot-c20-min" suffix="/20" />
              </View>
              {cfg.symbols[0] && <Confirm12Panel symbol={cfg.symbols[0]} tf={cfg.c20_tf} min={cfg.c20_min} set="c20" />}
              <C20Optimize
                pairs={cfg.c20_pairs ?? []}
                onDone={async () => {
                  const fresh = await qc.fetchQuery({ queryKey: ["bot"], queryFn: () => api<Resp>("/bot") });
                  setCfg((c) => (c ? { ...c, c20_pairs: fresh.bot.c20_pairs } : fresh.bot));
                }}
              />
            </>
          )}
          <View style={styles.c12Card} testID="bot-copt">
            <Text style={styles.c12Title}>Critério para entrar no robô</Text>
            <Text style={styles.note}>Um setup ou par só entra se, no período de teste, tiver lucro acima do mínimo OU acerto acima de 55% com lucro mínimo de 6%. Entre os aprovados fica o mais lucrativo com menor drawdown. Ao mudar, os pares 12C/20C são refiltrados (grava com «Guardar»).</Text>
            <ChipRow
              options={[{ value: "5", label: "> 5%" }, { value: "8", label: "> 8%" }, { value: "10", label: "> 10%" }]}
              value={String(cfg.c_min_return ?? 10)}
              onChange={(v) => upd({ c_min_return: Number(v) })}
              testID="bot-c-min-return"
            />
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12, marginTop: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.c12Title}>Reotimizar todos os domingos</Text>
                <Text style={styles.note}>Ao domingo (a partir das 02:00 UTC) o robô volta a otimizar sozinho os pares 12C e Sniper 20 com os dados mais recentes.</Text>
              </View>
              <Switch
                testID="bot-weekly-reopt"
                value={cfg.weekly_reopt ?? true}
                onValueChange={(v) => upd({ weekly_reopt: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
            {!!cfg.last_reopt && <Text style={styles.note}>Última reotimização: {new Date(cfg.last_reopt).toLocaleDateString("pt-PT")}</Text>}
          </View>
          <Text style={[styles.note, { paddingHorizontal: 16, marginTop: 8, marginBottom: 4 }]}>Onde o robô executa as ordens</Text>
          <ChipRow
            options={[{ value: "paper", label: "Simulada" }, { value: "metatrader", label: "MetaTrader" }, { value: "binance", label: "Binance" }]}
            value={cfg.live_mode ?? "paper"}
            onChange={(v) => upd({ live_mode: v as Bot["live_mode"] })}
            testID="bot-exec-mode"
          />
          {cfg.live_mode === "metatrader" && (
            <>
              {q.data?.bot?.live_until && (
                <Text style={[styles.note, { paddingHorizontal: 16 }]} testID="bot-live-until">
                  Teste em conta MetaTrader até {new Date(q.data.bot.live_until).toLocaleDateString("pt-PT")} — depois volta sozinho à conta simulada.
                </Text>
              )}
              <MtAccount
                maxLots={cfg.mt_max_lots ?? 0.1}
                suffix={cfg.mt_suffix ?? ""}
                onMaxLots={(v) => upd({ mt_max_lots: v })}
                onSuffix={(v) => upd({ mt_suffix: v })}
              />
            </>
          )}
          {cfg.live_mode === "binance" && (
            <LiveAccount
              mode={cfg.live_mode ?? "paper"}
              maxUsd={cfg.live_max_usd ?? 50}
              onMode={(m) => upd({ live_mode: m })}
              onMax={(v) => upd({ live_max_usd: v })}
            />
          )}
          <View style={styles.c12Card} testID="bot-be">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.c12Title}>Break-even automático</Text>
                <Text style={styles.note}>Ao chegar a +1R, mete o stop no preço de entrada.</Text>
              </View>
              <Switch
                testID="bot-be-switch"
                value={cfg.breakeven_enabled ?? true}
                onValueChange={(v) => upd({ breakeven_enabled: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
          </View>
          <View style={styles.c12Card} testID="bot-ptp">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.c12Title}>Take profit parcial</Text>
                <Text style={styles.note}>Fecha parte da posição no primeiro alvo e deixa o resto correr até ao alvo final (com o break-even ligado, o stop passa também para a entrada).</Text>
              </View>
              <Switch
                testID="bot-ptp-switch"
                value={cfg.ptp_enabled}
                onValueChange={(v) => upd({ ptp_enabled: v })}
                trackColor={{ true: colors.success, false: colors.surfaceTertiary }}
                thumbColor={colors.onBrandPrimary}
              />
            </View>
          </View>
          {cfg.ptp_enabled && (
            <View style={styles.steps}>
              <Step label="% a fechar" value={cfg.ptp_pct} step={10} min={10} max={90} onChange={(v) => upd({ ptp_pct: v })} testID="bot-ptp-pct" suffix="%" />
              <Step label="Alvo parcial" value={cfg.ptp_r} step={0.5} min={0.5} max={5} onChange={(v) => upd({ ptp_r: v })} testID="bot-ptp-r" suffix="R" />
              {cfg.c20_enabled && (
                <Step label="Parcial Sniper" value={cfg.c20_ptp_r} step={0.5} min={0.5} max={5} onChange={(v) => upd({ c20_ptp_r: v })} testID="bot-c20-ptp-r" suffix="R" />
              )}
            </View>
          )}
          <Text style={styles.section}>Timeframe</Text>
          <ChipRow options={TFS} value={cfg.tf} onChange={(v) => upd({ tf: v })} testID="bot-tf" />
          <ChipRow
            options={[
              { value: "trend", label: "Filtro de tendência EMA200" },
              { value: "mtf", label: "Confirmar TF superior" },
              { value: "ai", label: "✨ Filtro IA" },
            ]}
            value={[...(cfg.trend_filter ? ["trend"] : []), ...(cfg.mtf ? ["mtf"] : []), ...(cfg.ai_filter ? ["ai"] : [])]}
            onChange={(v) => (v === "trend" ? upd({ trend_filter: !cfg.trend_filter }) : v === "mtf" ? upd({ mtf: !cfg.mtf }) : upd({ ai_filter: !cfg.ai_filter }))}
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
          </View>
          <View style={{ paddingHorizontal: 16, gap: 8 }}>
            <Button label="Guardar Configuração" onPress={() => save.mutate(cfg)} loading={save.isPending} testID="bot-save-button" />
            <Button label="Verificar sinais agora" variant="ghost" onPress={() => runNow.mutate()} loading={runNow.isPending} testID="bot-run-now-button" />
            <Text style={styles.note}>
              O robô abre e fecha posições na conta simulada sempre que a estratégia dá sinal numa vela fechada, com stop, alvo e break-even automáticos. Recomendado: testa a configuração no Backtest primeiro.
            </Text>
          </View>

          <View style={{ paddingHorizontal: 16, marginTop: 8 }}>
            <Button label="Ver Análise de Perdas" variant="ghost" onPress={() => router.push({ pathname: "/analysis", params: { scope: "bot" } })} testID="bot-open-analysis" />
            <Button label="Resultados por dia" variant="ghost" onPress={() => router.push({ pathname: "/results", params: { scope: "bot" } })} testID="bot-open-results" />
            <Button label="Resumo Diário IA" variant="ghost" onPress={() => router.push("/daily")} testID="bot-open-daily" />
            <Button label="Desempenho do Filtro IA" variant="ghost" onPress={() => router.push({ pathname: "/ai-stats", params: { scope: "bot" } })} testID="bot-open-ai-stats" />
          </View>
          <Text style={styles.section}>Atividade</Text>
          <View style={{ paddingHorizontal: 16 }} testID="bot-logs">
            {q.data.logs.length === 0 && <Text style={styles.muted}>Sem atividade ainda.</Text>}
            {q.data.logs.map((l) => (
              <View key={l.log_id} style={styles.log}>
                <Ionicons
                  name={l.kind === "open" ? "arrow-forward-circle" : l.kind === "close" ? "checkmark-circle" : l.kind === "skip" ? "remove-circle" : l.kind === "ai" ? "sparkles" : "power"}
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
  stepBtn: { width: 44, height: 44, borderRadius: 8, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  stepValue: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 18 },
  c12Card: { marginHorizontal: 16, marginVertical: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12 },
  c12Title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16, marginBottom: 2 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  override: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surfaceSecondary, borderRadius: 8, borderWidth: 1, borderColor: c.brandTertiary, paddingLeft: 12 },
  overrideX: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  log: { flexDirection: "row", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.divider, alignItems: "flex-start" },
  logMsg: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 13 },
  logTime: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
}));
