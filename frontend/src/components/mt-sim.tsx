import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Text, View } from "react-native";

import { api, fmt } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type St = { trades: number; wins: number; winrate: number; pnl: number; pct: number; final: number; max_dd: number };
type Row = { bot: "bot" | "bot2"; label: string; kind: string; strategy: string; error?: string; spread?: number; digits?: number; stats?: St; skip: Record<string, number> };
type Tr = { bot: string; label: string; dir: string; opened: string; vol: number; widen: number; pnl: number; reason: string; risk_pct: number };
type Job = {
  status: "running" | "done"; current: string | null; step: number; steps: number; error?: string; capital?: number; currency?: string; days: number;
  rows: Row[]; total?: { all: St; bot: St; bot2: St }; skipped?: { spread: number; risk: number; rr: number }; widened?: number; trades?: Tr[];
};

const DAYS = [
  { value: "7", label: "7 dias" },
  { value: "14", label: "14 dias" },
  { value: "30", label: "30 dias" },
];
const BOTS = [
  { value: "all", label: "Os dois" },
  { value: "bot", label: "Robô 1" },
  { value: "bot2", label: "Robô 2" },
];
const REASON: Record<string, string> = { SL: "stop", TP: "alvo", Sinal: "sinal contrário", Aberta: "ainda aberta" };

export function MtSim() {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [days, setDays] = useState("30");
  const [view, setView] = useState<"all" | "bot" | "bot2">("all");
  const [jobId, setJobId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["mtsim", jobId],
    queryFn: () => api<Job>(`/simulate/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (x) => (x.state.data?.status === "done" ? false : 2500),
  });
  const start = useMutation({
    mutationFn: () => api<{ job_id: string }>("/mt/simulate", { method: "POST", body: { days: Number(days) } }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const j = q.data;
  const running = start.isPending || (!!jobId && j?.status !== "done");
  const cur = j?.currency ?? "";
  const m = (v: number) => `${v >= 0 ? "+" : ""}${fmt(v, 2)} ${cur}`;
  const t = j?.total?.[view];
  const rows = (j?.rows ?? []).filter((r) => view === "all" || r.bot === view);

  return (
    <View style={{ gap: 8 }} testID="mt-sim">
      <Text style={styles.note}>
        Repete os sinais do Robô 1 e do Robô 2 como se tivessem entrado na tua conta MetaTrader: começa com o saldo real e usa o spread atual de cada
        par na corretora, o lote mínimo e o passo de lote, o risco máximo de 2% e o alargamento do stop quando o spread é alto. Compra ao ask, fecha
        ao bid, sem take profit parcial nem break-even, e com juros compostos.
      </Text>
      <Text style={styles.section}>Período</Text>
      <ChipRow options={DAYS} value={days} onChange={setDays} testID="mtsim-days" />
      <View style={{ paddingHorizontal: 16 }}>
        <Button label={running ? "A simular…" : "Simular no MetaTrader"} onPress={() => start.mutate()} loading={running} disabled={running} testID="mtsim-run" />
      </View>
      {running && j && (
        <Text style={styles.note} testID="mtsim-progress">
          {j.current ?? "…"} · {j.step}/{j.steps || "?"} · demora alguns minutos
        </Text>
      )}
      {j?.error && <Text style={[styles.note, { color: colors.error }]} testID="mtsim-error">{j.error}</Text>}
      {j?.status === "done" && j.total && t && (
        <>
          <ChipRow options={BOTS} value={view} onChange={(v) => setView(v as typeof view)} testID="mtsim-view" />
          <View style={styles.card} testID="mtsim-total">
            <Text style={styles.cardLabel}>
              {view === "all" ? "Robô 1 + Robô 2" : view === "bot" ? "Robô 1" : "Robô 2"} · {j.days} dias · saldo inicial {fmt(j.capital ?? 0, 2)} {cur}
            </Text>
            <Text style={[styles.big, { color: t.pnl >= 0 ? colors.success : colors.error }]} testID="mtsim-pnl">
              {m(t.pnl)} ({t.pct >= 0 ? "+" : ""}{fmt(t.pct, 1)}%)
            </Text>
            <Text style={styles.sub}>
              {t.trades} trades · {fmt(t.winrate, 0)}% acerto · drawdown máx. {fmt(t.max_dd, 1)}% · saldo final {fmt(t.final, 2)} {cur}
            </Text>
            {view === "all" && (
              <Text style={styles.sub} testID="mtsim-split">
                Robô 1: {m(j.total.bot.pnl)} ({j.total.bot.trades} trades) · Robô 2: {m(j.total.bot2.pnl)} ({j.total.bot2.trades} trades)
              </Text>
            )}
            {j.skipped && (
              <Text style={styles.sub} testID="mtsim-skipped">
                Não entrariam: {j.skipped.spread} por spread demasiado alto · {j.skipped.risk} por o lote mínimo passar 2% de risco · {j.skipped.rr} sem alvo rentável. {j.widened ?? 0} entraram com stop alargado.
              </Text>
            )}
          </View>
          <Text style={styles.section}>Por setup</Text>
          {rows.map((r, i) => (
            <View key={`${r.bot}-${r.label}-${r.strategy}-${i}`} style={styles.row} testID={`mtsim-row-${i}`}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.rowTitle}>
                  {r.bot === "bot2" ? "R2" : "R1"} · {r.label} · {r.kind === "c12" ? "12C" : r.kind === "c20" ? "Sniper 20" : r.strategy}
                </Text>
                <Text style={styles.sub}>
                  {r.error
                    ? r.error
                    : `${r.stats?.trades ?? 0} trades · ${fmt(r.stats?.winrate ?? 0, 0)}% acerto · spread ${r.spread?.toFixed(r.digits ?? 5)}${
                        Object.keys(r.skip).length ? ` · recusados ${Object.values(r.skip).reduce((a, b) => a + b, 0)}` : ""
                      }`}
                </Text>
              </View>
              {!r.error && r.stats && (
                <Text style={[styles.rowPnl, { color: r.stats.pnl >= 0 ? colors.success : colors.error }]}>{m(r.stats.pnl)}</Text>
              )}
            </View>
          ))}
          <Text style={styles.section}>Últimas entradas simuladas</Text>
          {(j.trades ?? []).filter((x) => view === "all" || x.bot === view).slice(0, 30).map((x, i) => (
            <Text key={`${x.opened}-${x.label}-${i}`} style={styles.note}>
              {new Date(x.opened).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · {x.bot === "bot2" ? "R2" : "R1"} {x.label}{" "}
              {x.dir === "BUY" ? "COMPRA" : "VENDA"} {x.vol} lote · risco {fmt(x.risk_pct, 1)}%{x.widen > 1 ? ` · stop ${fmt(x.widen, 1)}×` : ""} · {REASON[x.reason] ?? x.reason}{" "}
              <Text style={{ color: x.pnl >= 0 ? colors.success : colors.error }}>{m(x.pnl)}</Text>
            </Text>
          ))}
          <Text style={[styles.note, { marginTop: 8 }]}>
            Usa o spread de agora (à noite e ao fim de semana é maior) e não conta com comissões nem com o limite de margem com muitas posições abertas ao mesmo tempo. Os resultados passados não garantem os futuros.
          </Text>
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8, paddingHorizontal: 16 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17, paddingHorizontal: 16 },
  card: { marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 6 },
  cardLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  big: { fontFamily: fonts.display, fontSize: 26 },
  sub: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  rowTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  rowPnl: { fontFamily: fonts.displaySemi, fontSize: 14 },
}));
