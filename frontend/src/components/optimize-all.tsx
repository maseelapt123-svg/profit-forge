import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api, fmt, pct } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, haptic } from "@/src/components/ui";
import { STRATS } from "@/src/strategies";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type M = { return_pct: number; win_rate: number; total_trades: number };
type Row = { symbol: string; display: string; tf: string; best: { strategy: string; sl_atr: number; rr: number; train: M; test: M } };
type Job = { status: "running" | "done"; current: string | null; step: number; total: number; applied: number; results: Row[] };

const key = (r: Row) => `${r.symbol}|${r.tf}`;

/** One tap: walk-forward optimise every asset × timeframe of the main bot, then pick which validated setups go to the bot. */
export function OptimizeAll({ onDone }: { onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [jobId, setJobId] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [removed, setRemoved] = useState<string[]>([]);
  useEffect(() => {
    // reopen the last optimisation (it keeps running on the server even if the app is closed)
    api<{ job_id: string | null }>("/bot/optimize-all/current")
      .then((r) => r.job_id && setJobId((cur) => cur ?? r.job_id))
      .catch(() => {});
  }, []);
  const start = useMutation({
    mutationFn: () => api<{ job_id: string }>("/bot/optimize-all", { method: "POST" }),
    onSuccess: (r) => {
      setPicked([]);
      setRemoved([]);
      setJobId(r.job_id);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const job = useQuery({
    queryKey: ["bot-opt-all", jobId],
    queryFn: () => api<Job>(`/bot/optimize-all/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "done" ? false : 3000),
  });
  const j = job.data;
  const done = j?.status === "done";
  const nResults = j?.results.length ?? 0;
  useEffect(() => {
    // every qualifying setup is added to the bot by the server as soon as it is found
    setPicked((j?.results ?? []).map(key).filter((k) => !removed.includes(k)));
    if (nResults) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nResults]);
  const sawRunning = useRef(false);
  if (j?.status === "running") sawRunning.current = true;
  useEffect(() => {
    if (done && sawRunning.current) toast(`Otimização concluída · ${nResults} setup(s) no robô`, nResults ? "success" : "info");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);
  const apply = useMutation({
    mutationFn: (keys: string[]) =>
      api<{ applied: number; total: number }>(`/bot/optimize-all/${jobId}/apply`, { method: "POST", body: { keys, replace: true } }),
    onSuccess: (r) => {
      haptic("light");
      toast(`${r.total} setup(s) ativos no robô`, "success");
      onDone();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const running = start.isPending || (!!jobId && !done);
  const rows = j?.results ?? [];
  const toggle = (k: string) => {
    const next = picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k];
    setPicked(next);
    setRemoved(rows.map(key).filter((x) => !next.includes(x)));
    apply.mutate(next);
  };
  return (
    <View style={styles.card} testID="bot-optimize-all">
      <Text style={styles.title}>Otimizar tudo</Text>
      <Text style={styles.muted}>
        Testa todas as estratégias e plugins em todos os timeframes (1m a 1D) de cada ativo do robô, com treino 70% / teste 30%. Começa do zero: remove os setups antigos e adiciona logo ao robô cada setup com lucro acima de 6% no teste — vários timeframes por ativo. Continua no servidor mesmo que feches a app ou o servidor reinicie.
      </Text>
      {running && j && (
        <View style={{ gap: 4 }}>
          <View style={styles.barBg}>
            <View style={[styles.bar, { width: `${(j.step / Math.max(1, j.total)) * 100}%` }]} />
          </View>
          <Text style={styles.muted} testID="bot-optimize-all-progress">
            {j.current ?? "…"} · {j.step}/{j.total} testes · {rows.length} setup(s) validado(s)
          </Text>
        </View>
      )}
      {rows.map((r) => {
        const k = key(r);
        const on = picked.includes(k);
        return (
          <Pressable key={k} onPress={() => toggle(k)} disabled={!done || apply.isPending} style={styles.row} testID={`bot-optimize-all-row-${k}`}>
            <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.brandPrimary : colors.muted} />
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>
                {r.display} · {r.tf.toUpperCase()} · {STRATS.find((x) => x.value === r.best.strategy)?.label ?? r.best.strategy}
              </Text>
              <Text style={styles.muted}>
                SL {r.best.sl_atr}x · R:R {r.best.rr} · acerto {fmt(r.best.test.win_rate, 0)}% · {r.best.test.total_trades} ops
              </Text>
            </View>
            <Text style={[styles.ret, { color: r.best.test.return_pct >= 0 ? colors.success : colors.error }]}>{pct(r.best.test.return_pct)}</Text>
          </Pressable>
        );
      })}
      {done && rows.length === 0 && <Text style={styles.muted}>Nenhum setup teve lucro acima de 6% no período de teste.</Text>}
      {done && rows.length > 0 && <Text style={styles.muted}>Todos os setups acima foram adicionados ao robô. Desmarca para remover.</Text>}
      <Button
        label={running ? "A otimizar…" : done ? "Otimizar de novo" : "Otimizar tudo"}
        variant={done ? "ghost" : "primary"}
        onPress={() => start.mutate()}
        loading={running}
        testID="bot-optimize-all-button"
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginBottom: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 16, gap: 10 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 17 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  barBg: { height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.brandPrimary },
  row: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 48 },
  label: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13 },
  ret: { fontFamily: fonts.display, fontSize: 14, minWidth: 56, textAlign: "right" },
}));
