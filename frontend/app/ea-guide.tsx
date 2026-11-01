import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Linking, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, BASE } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const STEPS = [
  { icon: "download", title: "Descarrega o ficheiro .mq5", desc: "Toca no botão abaixo (no computador Windows onde tens o MetaTrader 5). O ficheiro já leva os teus setups otimizados." },
  { icon: "folder-open", title: "Coloca na pasta Experts", desc: "No MT5: Ficheiro → Abrir pasta de dados → MQL5 → Experts. Copia o SmartTradeAll.mq5 para lá." },
  { icon: "construct", title: "Compila para .ex5 (F7)", desc: "Abre o ficheiro no MetaEditor (tecla F4 no MT5) e carrega em Compilar (F7). O .ex5 é criado automaticamente na mesma pasta." },
  { icon: "play", title: "Arrasta para o gráfico", desc: "No Navegador do MT5 → Expert Advisors, arrasta o SmartTradeAll para UM gráfico qualquer, ativa 'Permitir Algo Trading' e o botão Algo Trading. Ele opera sozinho todos os pares e timeframes da lista." },
] as const;

type EaSetup = { kind: number; mt_symbol: string; label: string; rr: number; sl_atr: number; mtf: boolean; htf: string | null };

export default function EaGuide() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const q = useQuery({ queryKey: ["ea-all"], queryFn: () => api<{ count: number; setups: EaSetup[] }>("/ea/all") });
  const dl = useMutation({
    mutationFn: (script: boolean) => api<{ path: string }>(`/ea/all/link${script ? "?script=1" : ""}`, { method: "POST" }),
    onSuccess: (r) => Linking.openURL(`${BASE}${r.path}`),
    onError: (e: Error) => toast(e.message, "error"),
  });
  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="ea-guide-screen">
      <View style={styles.header}>
        <Pressable testID="ea-guide-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Robô no MetaTrader 5</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}>
        <View style={styles.note}>
          <Ionicons name="information-circle" size={20} color={colors.brandPrimary} />
          <Text style={styles.noteText}>
            O ficheiro .ex5 só pode ser gerado pelo compilador oficial da MetaQuotes (MetaEditor). É gratuito, já vem com o MT5 e demora 1 segundo — por isso entregamos o código-fonte .mq5 pronto a compilar.
          </Text>
        </View>
        {STEPS.map((s, i) => (
          <View key={s.title} style={styles.card} testID={`ea-step-${i + 1}`}>
            <View style={styles.num}>
              <Text style={styles.numText}>{i + 1}</Text>
            </View>
            <View style={{ flex: 1, gap: 4 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Ionicons name={s.icon as any} size={16} color={colors.brandPrimary} />
                <Text style={styles.cardTitle}>{s.title}</Text>
              </View>
              <Text style={styles.cardDesc}>{s.desc}</Text>
            </View>
          </View>
        ))}
        <Text style={styles.section}>O que o robô vai operar</Text>
        {q.isLoading ? (
          <ActivityIndicator color={colors.brandPrimary} />
        ) : !q.data?.count ? (
          <Text style={styles.hint} testID="ea-empty">Ainda não há setups. Otimiza o robô primeiro (Otimizar tudo, 12 Confirmações ou Sniper 20).</Text>
        ) : (
          <View style={styles.list} testID="ea-setups">
            {q.data.setups.map((s, i) => (
              <View key={i} style={styles.setup}>
                <Text style={[styles.badge, { color: s.kind === 0 ? colors.brandPrimary : s.kind === 1 ? colors.success : colors.warning }]}>
                  {s.kind === 0 ? "Estratégia" : s.kind === 1 ? "12C" : "Sniper 20"}
                </Text>
                <Text style={styles.setupText} numberOfLines={1}>
                  {s.mt_symbol} · {s.label}
                </Text>
                <Text style={styles.setupMeta}>1:{s.rr} · SL {s.sl_atr}×ATR{s.mtf && s.htf ? ` · ${s.htf.toUpperCase()}` : ""}</Text>
              </View>
            ))}
          </View>
        )}
        <Button
          label={`Descarregar robô com ${q.data?.count ?? 0} setups (.mq5)`}
          onPress={() => dl.mutate(false)}
          loading={dl.isPending && dl.variables === false}
          disabled={!q.data?.count}
          testID="ea-download"
        />
        <View style={styles.scriptCard} testID="ea-script-card">
          <Text style={styles.cardTitle}>Script: abrir ordens com sinal agora</Text>
          <Text style={styles.cardDesc}>
            SmartTradeNow.mq5 corre uma vez: analisa todos os setups acima, mostra a lista de ordens com sinal (últimas 3 velas) e só abre depois de confirmares, com o teu risco, stop e alvo. Instala-se em MQL5 → Scripts (compila com F7) e arrasta-se para qualquer gráfico. Abre ordens a sério: se for conta real, o aviso indica «CONTA REAL».
          </Text>
          <Button
            label="Descarregar script (.mq5)"
            variant="ghost"
            onPress={() => dl.mutate(true)}
            loading={dl.isPending && dl.variables === true}
            disabled={!q.data?.count}
            testID="ea-download-script"
          />
        </View>
        <Text style={styles.hint}>
          Inclui todas as estratégias (Smart Money, RSI, EMA, MACD, Bollinger, Supertrend, Ichimoku, VWAP…), 12 Confirmações e Sniper 20, cada uma no timeframe, R:R, stop e nº de confirmações otimizados, filtro do TF superior, TP parcial, break-even e limite de posições. Os pares otimizados de 12C e Sniper 20 entram sempre (mesmo se desligados no robô da app); podes desligá-los no MT5 em EnableC12 / EnableC20. Se reotimizares na app, descarrega de novo. Se os símbolos da corretora tiverem sufixo (ex.: EURUSD.m), indica-o em SymbolSuffix. Testa sempre primeiro numa conta demo (ou no Strategy Tester do MT5).
        </Text>
        <Pressable onPress={() => Linking.openURL(`${BASE}/ea/SmartTrade12C.mq5`)} testID="ea-download-12c" style={{ paddingVertical: 12 }}>
          <Text style={[styles.hint, { color: colors.brandPrimary }]}>Versão simples (só 12 Confirmações, gráfico atual) →</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 22 },
  note: { flexDirection: "row", gap: 8, backgroundColor: c.brandSoft, borderRadius: 12, padding: 12 },
  noteText: { flex: 1, color: c.onSurface, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  card: { flexDirection: "row", gap: 12, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16 },
  num: { width: 32, height: 32, borderRadius: 16, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  numText: { color: c.surface, fontFamily: fonts.display, fontSize: 16 },
  cardTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  cardDesc: { color: c.muted, fontFamily: fonts.text, fontSize: 13, lineHeight: 18 },
  section: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18, marginTop: 8 },
  scriptCard: { gap: 6, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16 },
  list: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, paddingVertical: 4 },
  setup: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingVertical: 10 },
  badge: { fontFamily: fonts.displaySemi, fontSize: 11, width: 62 },
  setupText: { flex: 1, color: c.onSurface, fontFamily: fonts.text, fontSize: 13 },
  setupMeta: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
  hint: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 12, lineHeight: 18 },
}));
