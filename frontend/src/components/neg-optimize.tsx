import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Text, View } from "react-native";

import { api, fmt, pct } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, haptic } from "@/src/components/ui";
import { STRATS } from "@/src/strategies";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Item = { kind: string; symbol: string; tf: string; strategy: string; sl_atr: number; rr: number; trend_filter: boolean; mtf: boolean; min: number };
type Prop = {
  kind: string; label: string; old_strategy: string;
  best: { strategy?: string; tf: string; rr: number; min?: number; sl_atr?: number; test: number; winrate: number } | null;
};
type Job = { status: "running" | "done"; current: string | null; step: number; total: number; applied: boolean; results: Prop[] };
const lbl = (v: string) => STRATS.find((x) => x.value === v)?.label ?? v;

/** Re-optimises the strategies that were negative in the simulation and lets the user apply the fixes to the bot. */
export function NegOptimize({ items, onApplied }: { items: Item[]; onApplied: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<{ job_id: string }>("/simulate/optimize-negatives", { method: "POST", body: { items } }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const job = useQuery({
    queryKey: ["negopt", jobId],
    queryFn: () => api<Job>(`/simulate/optimize-negatives/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "done" ? false : 3000),
  });
  const apply = useMutation({
    mutationFn: () => api<{ replaced: number; removed: number }>(`/simulate/optimize-negatives/${jobId}/apply`, { method: "POST" }),
    onSuccess: (r) => {
      haptic("medium");
      toast(`${r.replaced} otimizado(s) e ${r.removed} retirado(s) no robô`, "success");
      qc.invalidateQueries({ queryKey: ["bot"] });
      job.refetch();
      onApplied();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const j = job.data;
  const running = start.isPending || (!!jobId && j?.status !== "done");
  return (
    <View style={styles.card} testID="sim-negopt">
      <Text style={styles.title}>Otimizar os negativos</Text>
      <Text style={styles.muted}>
        Procura a melhor estratégia (setups) ou o melhor TF/R:R (Sniper 20) para cada um dos {items.length} negativos. Só são propostos setups com lucro acima de 10% ou acerto acima de 55% com lucro mínimo de 6% no teste (o mais lucrativo com menor drawdown); os outros são retirados.
      </Text>
      {running && j && <Text style={styles.muted} testID="sim-negopt-progress">{j.current ?? "…"} · {j.step}/{j.total}</Text>}
      {j?.results.map((r, i) => (
        <View key={i} style={styles.row} testID={`sim-negopt-row-${i}`}>
          <Text style={[styles.label, { flex: 1 }]} numberOfLines={2}>
            {r.label} · {r.kind === "c20" ? "Sniper 20" : lbl(r.old_strategy)}
          </Text>
          {r.best ? (
            <Text style={[styles.label, { color: colors.success }]} numberOfLines={2}>
              → {r.kind === "c20" ? `${r.best.tf.toUpperCase()} 1:${r.best.rr} ${r.best.min}/20` : lbl(r.best.strategy ?? "")} · {pct(r.best.test)} · {fmt(r.best.winrate, 0)}%
            </Text>
          ) : (
            <Text style={[styles.label, { color: colors.error }]}>→ retirar</Text>
          )}
        </View>
      ))}
      {j?.status === "done" ? (
        <Button
          label={j.applied ? "Aplicado ao robô ✓" : "Aplicar ao robô"}
          onPress={() => apply.mutate()}
          loading={apply.isPending}
          disabled={j.applied}
          testID="sim-negopt-apply"
        />
      ) : (
        <Button label={running ? "A otimizar…" : `Otimizar negativos (${items.length})`} onPress={() => start.mutate()} loading={running} disabled={!items.length} testID="sim-negopt-start" />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12, gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 32 },
  label: { color: c.onSurface, fontFamily: fonts.text, fontSize: 12 },
}));
