import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { api, fmt, pct } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Pair = { symbol: string; display?: string; tf: string; rr: number; min: number; enabled: boolean; test: number | null; test_winrate?: number; test_trades?: number };
type Job = { status: "running" | "done"; current: string | null; step: number; total: number; results: Pair[] };

/** Finds, for each pair of the bot, the timeframe + R:R (1:5 / 1:10) + min confirmations with the best Sniper 20 result. */
export function C20Optimize({ pairs, onDone, kind = "c20" }: { pairs: Pair[]; onDone: () => void; kind?: "c12" | "c20" }) {
  const n20 = kind === "c20" ? 20 : 12;
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<{ job_id: string }>(`/bot/c20-optimize?kind=${kind}`, { method: "POST" }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const job = useQuery({
    queryKey: ["c20-opt", kind, jobId],
    queryFn: () => api<Job>(`/bot/c20-optimize/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "done" ? false : 3000),
  });
  const j = job.data;
  const done = j?.status === "done";
  const n = j?.results.length ?? 0;
  useEffect(() => {
    if (n) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, done]);
  const running = start.isPending || (!!jobId && !done);
  const rows = j?.results.length ? j.results : pairs;
  return (
    <View style={styles.card} testID={`${kind}-optimize`}>
      <Text style={styles.title}>Otimizar pares {kind === "c20" ? "Sniper 20" : "12 Confirmações"}</Text>
      <Text style={styles.muted}>
        Para cada par testa 5m, 15m, 1H, 4H e 1D, {kind === "c20" ? "R:R 1:5 e 1:10 e 14/16/18 ferramentas" : "R:R 1:1,5, 1:2 e 1:3 e 9/10/11 confirmações"} (treino 70% / teste 30%). Guarda logo o melhor de cada par; pares com lucro no teste abaixo do mínimo escolhido (5%, 8% ou 10%) ficam desligados.
      </Text>
      {running && j && (
        <View style={{ gap: 4 }}>
          <View style={styles.barBg}>
            <View style={[styles.bar, { width: `${(j.step / Math.max(1, j.total)) * 100}%` }]} />
          </View>
          <Text style={styles.muted} testID={`${kind}-optimize-progress`}>{j.current ?? "…"} · {j.step}/{j.total}</Text>
        </View>
      )}
      {rows.map((p) => (
        <View key={p.symbol} style={styles.row} testID={`${kind}-pair-${p.symbol}`}>
          <Text style={[styles.label, { flex: 1 }]}>{p.display ?? p.symbol.replace("=X", "")}</Text>
          {p.enabled ? (
            <Text style={[styles.label, { color: colors.success }]}>
              {p.tf.toUpperCase()} · 1:{p.rr} · {p.min}/{n20}{p.test != null ? ` · ${pct(p.test)}` : ""}
              {p.test_winrate != null ? ` · ${fmt(p.test_winrate, 0)}%` : ""}
            </Text>
          ) : (
            <Text style={[styles.label, { color: colors.muted }]}>desligado{p.test != null ? ` (${pct(p.test)})` : ""}</Text>
          )}
        </View>
      ))}
      <Button label={running ? "A otimizar…" : "Otimizar pares"} onPress={() => start.mutate()} loading={running} testID={`${kind}-optimize-button`} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginBottom: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 16, gap: 10 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  barBg: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.brandPrimary },
  row: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 28 },
  label: { color: c.onSurface, fontFamily: fonts.text, fontSize: 13 },
}));
