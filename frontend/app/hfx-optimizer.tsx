import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, fmt } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Segmented } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type St = { wins: number; losses: number; samples: number; winrate: number; lower_bound: number };
type Cand = { rule: string; label: string; train: St; test: St; strength?: "forte" | "moderada" };
type Row = { pair: string; display: string; best: Cand | null; top: Cand[]; breakeven: number; bars: number };
type Resp = { expiry: number; payout: number; results: Row[] };

export default function HfxOptimizer() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [expiry, setExpiry] = useState<"1" | "3">("1");
  const opt = useMutation({ mutationFn: () => api<Resp>("/hfx/optimize", { method: "POST", body: { expiry: Number(expiry) } }) });
  const winners = opt.data?.results.filter((r) => r.best) ?? [];

  const sendToBot = async () => {
    try {
      const cur = await api<{ bot: any }>("/hfx/bot");
      const setups = { ...(cur.bot.setups ?? {}) };
      winners.forEach((w) => (setups[w.pair.replace(".", "_")] = { rule: w.best!.rule, expiry: opt.data!.expiry }));
      const pairs = Array.from(new Set([...(cur.bot.pairs ?? []), ...winners.map((w) => w.pair)]));
      await api("/hfx/bot", { method: "PUT", body: { ...cur.bot, strategy: "optimized", setups, pairs } });
      qc.invalidateQueries({ queryKey: ["hfx-bot"] });
      toast(`Robô HFX: estratégia otimizada em ${winners.length} par(es)`, "success");
      router.push("/hfx-bot");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="hfx-optimizer-screen">
      <View style={styles.header}>
        <Pressable testID="hfx-opt-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Estratégia Vencedora HFX</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}>
        <Text style={styles.intro}>
          Testa os 7 plugins, todas as combinações de 2 plugins e a confluência em ~7.000 velas reais de 1 minuto por par. Escolhe com os primeiros 70% e confirma nos 30% que não foram usados. Só é «validada» se o acerto ficar acima do mínimo do payout (82% → 54,9%) nas duas partes.
        </Text>
        <Segmented
          options={[
            { value: "1", label: "Expiração 1 min" },
            { value: "3", label: "Expiração 3 min" },
          ]}
          value={expiry}
          onChange={setExpiry}
          testID="hfx-opt-expiry"
        />
        <Button label={opt.isPending ? "A testar estratégias…" : "Encontrar Estratégia"} loading={opt.isPending} onPress={() => opt.mutate()} testID="hfx-opt-run-button" />
        {opt.isError && <Text style={styles.error}>{(opt.error as Error).message}</Text>}
        {opt.data && (
          <>
            <Text style={styles.summary} testID="hfx-opt-summary">
              {winners.length} de {opt.data.results.length} pares com estratégia validada ({opt.data.expiry} min)
            </Text>
            {opt.data.results.map((r, i) => {
              const c = r.best ?? r.top[0];
              return (
                <Animated.View key={r.pair} entering={FadeInDown.delay(i * 40)} style={[styles.card, r.best && styles.cardWin]} testID={`hfx-opt-row-${r.pair}`}>
                  <View style={styles.cardHead}>
                    <Text style={styles.pair}>{r.display}</Text>
                    <View style={[styles.tag, r.best ? styles.tagWin : styles.tagNo]}>
                      <Text style={[styles.tagText, { color: r.best ? colors.success : colors.muted }]}>{r.best ? (r.best.strength === "forte" ? "VALIDADA · FORTE" : "VALIDADA · MODERADA") : "SEM VANTAGEM"}</Text>
                    </View>
                  </View>
                  {c ? (
                    <>
                      <Text style={styles.rule}>{c.label}</Text>
                      <View style={styles.statRow}>
                        <Text style={styles.stat}>
                          Treino {fmt(c.train.winrate, 1)}% ({c.train.samples})
                        </Text>
                        <Text style={[styles.stat, { color: c.test.winrate > r.breakeven ? colors.success : colors.error }]}>
                          Teste {fmt(c.test.winrate, 1)}% ({c.test.samples})
                        </Text>
                      </View>
                      <Text style={styles.muted}>
                        Pior caso no teste (95%): {fmt(c.test.lower_bound, 1)}% · mínimo para lucrar {fmt(r.breakeven, 1)}%
                      </Text>
                    </>
                  ) : (
                    <Text style={styles.muted}>Dados insuficientes</Text>
                  )}
                </Animated.View>
              );
            })}
            {winners.length > 0 ? (
              <Button label={`Usar no Robô HFX (${winners.length} pares)`} onPress={sendToBot} testID="hfx-opt-bot-button" />
            ) : (
              <Text style={styles.warn}>Nenhuma estratégia passou a validação. Não operes estes pares nesta expiração.</Text>
            )}
            <Text style={styles.muted}>
              Resultados passados não garantem resultados futuros. Os dados de 1 minuto gratuitos podem diferir dos preços da tua corretora, e as vantagens em 1–3 minutos tendem a desaparecer. Valida primeiro em conta simulada durante vários dias.
            </Text>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  intro: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  summary: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 18 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 12, gap: 4 },
  cardWin: { borderColor: c.success },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  pair: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  tag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  tagWin: { backgroundColor: c.successSoft },
  tagNo: { backgroundColor: c.surfaceTertiary },
  tagText: { fontFamily: fonts.display, fontSize: 12 },
  rule: { color: c.onSurfaceTertiary, fontFamily: fonts.displaySemi, fontSize: 15 },
  statRow: { flexDirection: "row", gap: 16 },
  stat: { color: c.onSurface, fontFamily: fonts.display, fontSize: 15 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  warn: { color: c.warning, fontFamily: fonts.text, fontSize: 13 },
  error: { color: c.error, fontFamily: fonts.text, fontSize: 13 },
}));
