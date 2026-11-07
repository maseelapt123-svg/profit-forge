import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api, fmt } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow, haptic } from "@/src/components/ui";
import { STRATS } from "@/src/strategies";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Res = { symbol: string; display: string; tf: string; strategy: string; rr: number; test: number; wr: number; dd: number; trades: number; train: number; score: number };
type Job = { job_id: string; status: "running" | "done"; category: string; tfs: string[]; current: string | null; step: number; total: number; results: Res[]; error?: string };

const CATS = [
  { value: "forex", label: "Forex" },
  { value: "crypto", label: "Cripto" },
  { value: "indices", label: "Índices" },
  { value: "stocks", label: "Ações" },
];
const TFS = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];
const stratLabel = (v: string) => STRATS.find((x) => x.value === v)?.label ?? v;

export function MarketScan() {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const qc = useQueryClient();
  const [cat, setCat] = useState("forex");
  const [tfs, setTfs] = useState<string[]>(["1h", "4h"]);
  const [sel, setSel] = useState<string[]>([]);
  const cur = useQuery({
    queryKey: ["scan"],
    queryFn: () => api<{ job: Job | null }>("/scan/current"),
    refetchInterval: (q) => (q.state.data?.job?.status === "running" ? 3000 : false),
  });
  const j = cur.data?.job;
  const running = j?.status === "running";
  useEffect(() => setSel([]), [j?.job_id]);
  useEffect(() => {  // chips show the settings of the last scan
    if (j) {
      setCat(j.category);
      setTfs(j.tfs);
    }
  }, [j?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useMutation({
    mutationFn: () => api<{ job_id: string }>("/scan", { method: "POST", body: { category: cat, tfs } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scan"] }),
    onError: (e: Error) => toast(e.message, "error"),
  });
  const add = useMutation({
    mutationFn: () => api<{ added: number; total: number }>("/bot2/add", { method: "POST", body: { job_id: j!.job_id, keys: sel } }),
    onSuccess: (r) => {
      haptic("medium");
      toast(`${r.added} setup(s) adicionados — ${r.total} no Robô 2`, "success");
      qc.invalidateQueries({ queryKey: ["bot2"] });
      setSel([]);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const key = (r: Res) => `${r.symbol}|${r.tf}`;
  const toggle = (k: string) => setSel((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  const toggleTf = (t: string) => setTfs((s) => (s.includes(t) ? s.filter((x) => x !== t) : [...s, t]));

  return (
    <View style={{ gap: 8 }} testID="scan-panel">
      <Text style={styles.note}>
        Testa todas as estratégias em todos os pares do mercado (treino 70% / teste 30%) e mostra o setup mais lucrativo de cada par. Só aparecem
        setups com acerto acima de 55% e lucro mínimo de 6%, ou lucro acima de 25%. Ficam ordenados por lucro face ao drawdown.
      </Text>
      <Text style={styles.section}>Mercado</Text>
      <ChipRow options={CATS} value={cat} onChange={setCat} testID="scan-cat" />
      <Text style={styles.section}>Timeframes</Text>
      <ChipRow options={TFS} value={tfs} onChange={toggleTf} testID="scan-tfs" />
      <View style={{ paddingHorizontal: 16, gap: 8 }}>
        <Button
          label={running ? "A procurar…" : "Procurar os mais lucrativos"}
          onPress={() => start.mutate()}
          loading={start.isPending || running}
          disabled={!tfs.length || running}
          testID="scan-start"
        />
        <Button label="Abrir Robô 2" variant="ghost" onPress={() => router.push("/bot2")} testID="scan-open-bot2" />
      </View>
      {running && j && (
        <Text style={[styles.note, { paddingHorizontal: 16 }]} testID="scan-progress">
          {j.current ?? "…"} · {j.step}/{j.total} · podes sair do ecrã, continua no servidor
        </Text>
      )}
      {j?.error && <Text style={[styles.note, { paddingHorizontal: 16, color: colors.error }]}>{j.error}</Text>}
      {j && (j.results.length > 0 || j.status === "done") && (
        <>
          <Text style={styles.section}>
            {CATS.find((c) => c.value === j.category)?.label} · {j.results.length} aprovado(s)
          </Text>
          {j.status === "done" && !j.results.length && (
            <Text style={[styles.note, { paddingHorizontal: 16 }]} testID="scan-empty">Nenhum par passou a regra nestes timeframes.</Text>
          )}
          {j.results.map((r, i) => {
            const on = sel.includes(key(r));
            return (
              <Pressable key={key(r)} onPress={() => toggle(key(r))} style={[styles.row, on && { borderColor: colors.brandPrimary }]} testID={`scan-row-${i}`}>
                <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.brandPrimary : colors.muted} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.rowTitle}>
                    {i === 0 ? "🏆 " : ""}{r.display} {r.tf.toUpperCase()} · {stratLabel(r.strategy)} · 1:{r.rr}
                  </Text>
                  <Text style={styles.sub}>
                    Teste <Text style={{ color: r.test >= 0 ? colors.success : colors.error }}>{r.test >= 0 ? "+" : ""}{fmt(r.test, 1)}%</Text> · acerto {fmt(r.wr, 0)}% · DD {fmt(r.dd, 1)}% · {r.trades} trades · treino {fmt(r.train, 1)}%
                  </Text>
                </View>
              </Pressable>
            );
          })}
          {j.results.length > 0 && (
            <View style={{ paddingHorizontal: 16, flexDirection: "row", gap: 8 }}>
              <Button
                label={sel.length === j.results.length ? "Limpar" : "Marcar todos"}
                variant="ghost"
                onPress={() => setSel(sel.length === j.results.length ? [] : j.results.map(key))}
                testID="scan-select-all"
                style={{ flex: 1 }}
              />
              <Button label={`Adicionar (${sel.length})`} onPress={() => add.mutate()} loading={add.isPending} disabled={!sel.length} testID="scan-add" style={{ flex: 1.4 }} />
            </View>
          )}
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  section: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 13, letterSpacing: 1, textTransform: "uppercase", marginTop: 8, paddingHorizontal: 16 },
  note: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17, paddingHorizontal: 16 },
  sub: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 16, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, minHeight: 56 },
  rowTitle: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
}));
