import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Text, View } from "react-native";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Setup = { symbol: string; tf: string; strategy: string; rr: number; sl_atr: number; test: number };
type Pair = { symbol: string; display: string; tf: string; min: number; rr: number; test: number };
type Job = {
  job_id?: string; status?: "running" | "done" | "error"; current?: string | null; step?: number; total?: number; error?: string;
  found?: { setups: number; c12: number; c20: number }; spreads?: Record<string, number>;
  results?: { setups: Setup[]; c12: Pair[]; c20: Pair[] };
};

export function MtOptimize() {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["mt-opt"],
    queryFn: () => api<Job>("/bot/mt-optimize/current"),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 3000 : false),
  });
  const start = useMutation({
    mutationFn: () => api("/bot/mt-optimize", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mt-opt"] }),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const j = q.data;
  const running = j?.status === "running";
  const pct = j?.total ? Math.round(((j.step ?? 0) / j.total) * 100) : 0;
  const nSyms = j?.spreads ? Object.keys(j.spreads).length : 0;

  return (
    <View style={styles.card} testID="mt-optimize">
      <Text style={styles.title}>Otimizador MetaTrader · todos os pares</Text>
      <Text style={styles.note}>
        Testa todos os pares da tua corretora de que há histórico (forex, ouro, prata, petróleo, índices, cripto e ações), com o spread real de cada um como custo. Otimiza as estratégias, as 12 Confirmações e o Sniper 20, e rejeita setups em que o spread passa de 20% do stop. No fim, o robô fica só com os pares lucrativos. Demora 30–90 min.
      </Text>
      {running ? (
        <View style={{ gap: 6 }} testID="mt-optimize-progress">
          <View style={styles.bar}>
            <View style={[styles.fill, { width: `${pct}%`, backgroundColor: colors.brandPrimary }]} />
          </View>
          <Text style={styles.note}>
            {pct}% · {j?.current ?? "…"}
          </Text>
          <Text style={styles.note}>
            Encontrados: {j?.found?.setups ?? 0} setups · {j?.found?.c12 ?? 0} 12C · {j?.found?.c20 ?? 0} Sniper 20
          </Text>
        </View>
      ) : (
        <Button label={j?.status ? "Otimizar de novo" : "Otimizar todos os pares no MT5"} onPress={() => start.mutate()} loading={start.isPending} testID="mt-optimize-start" />
      )}
      {j?.status === "error" && <Text style={[styles.note, { color: colors.error }]}>Erro: {j.error}</Text>}
      {j?.status === "done" && j.results && (
        <View style={{ gap: 4 }} testID="mt-optimize-results">
          <Text style={[styles.note, { color: colors.success }]}>
            ✓ {nSyms} pares testados · no robô: {j.results.setups.length} setups, {j.results.c12.length} 12C, {j.results.c20.length} Sniper 20
          </Text>
          {j.results.setups.slice(0, 8).map((s) => (
            <Text key={`${s.symbol}${s.tf}`} style={styles.row}>
              {s.symbol.replace("=X", "").replace("-USD", "")} {s.tf.toUpperCase()} · {s.strategy} · 1:{s.rr} · teste +{s.test}%
            </Text>
          ))}
          {[...j.results.c12.map((p) => ({ ...p, k: "12C" })), ...j.results.c20.map((p) => ({ ...p, k: "20C" }))].slice(0, 8).map((p) => (
            <Text key={`${p.k}${p.symbol}`} style={styles.row}>
              {p.k} {p.display} {p.tf.toUpperCase()} · {p.min} conf. · 1:{p.rr} · teste +{p.test.toFixed(1)}%
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { gap: 8, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, backgroundColor: c.surface },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  row: { color: c.onSurface, fontFamily: fonts.text, fontSize: 12 },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  fill: { height: 8, borderRadius: 4 },
}));
