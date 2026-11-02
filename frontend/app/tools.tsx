import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PressableScale } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const TOOLS = [
  { route: "/results", icon: "bar-chart", title: "Resultados dos robôs", desc: "Lucro por dia, total e média diária dos robôs" },
  { route: "/daily", icon: "newspaper", title: "Resumo Diário IA", desc: "Resultados do dia de cada robô e ajustes para amanhã" },
  { route: "/analysis", icon: "medkit", title: "Análise de Perdas", desc: "Explica porque perdeste e corrige o robô automaticamente" },
  { route: "/signals", icon: "flash", title: "Sinais", desc: "Consenso dos plugins com confirmação do timeframe superior" },
  { route: "/patterns", icon: "scan", title: "Scanner de Padrões", desc: "Engolfo, martelo, doji, pin bar e inside bar em todos os ativos" },
  { route: "/calculator", icon: "calculator", title: "Calculadora de Posição", desc: "Quanto comprar consoante o capital, risco e stop" },
  { route: "/plugins", icon: "extension-puzzle", title: "Plugins de Estratégia", desc: "Ativa e ajusta SMC, RSI, EMA, MACD e Bollinger" },
  { route: "/mt-panel", icon: "pulse", title: "Painel MT5", desc: "Posições abertas e lucro em tempo real da conta MetaTrader" },
  { route: "/ea-guide", icon: "logo-windows", title: "Robô para MetaTrader 5", desc: "Descarrega o EA e instala no MT5 em 4 passos (.mq5 → .ex5)" },
  { route: "/bot", icon: "hardware-chip", title: "Robô Automático", desc: "Opera sozinho em vários timeframes otimizados" },
  { route: "/hfx-optimizer", icon: "trophy", title: "Estratégia Vencedora HFX", desc: "Encontra e valida a melhor combinação de plugins por par" },
  { route: "/hfx-plugins", icon: "options", title: "Plugins HFX", desc: "7 plugins de 1–3 min: BB+RSI, RSI(2), Estocástico, Pin bar…" },
  { route: "/hfx-bot", icon: "timer", title: "Robô HFX", desc: "Entradas automáticas de 1 e 3 minutos" },
] as const;

export default function Tools() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="tools-screen">
      <View style={styles.header}>
        <Pressable testID="tools-back-button" onPress={() => router.back()} style={styles.back}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Ferramentas</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}>
        <Text style={styles.hint}>No gráfico de cada ativo tens também EMA 20/50, VWAP, suportes/resistências, Fibonacci e RSI.</Text>
        {TOOLS.map((t, i) => (
          <Animated.View key={t.route} entering={FadeInDown.delay(i * 50)}>
            <PressableScale testID={`tool-${t.route.slice(1)}`} style={styles.card} onPress={() => router.push(t.route as any)}>
              <View style={styles.icon}>
                <Ionicons name={t.icon as any} size={22} color={colors.brandPrimary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle}>{t.title}</Text>
                <Text style={styles.cardDesc}>{t.desc}</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </PressableScale>
          </Animated.View>
        ))}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: c.border },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  hint: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16 },
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandSoft, alignItems: "center", justifyContent: "center" },
  cardTitle: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  cardDesc: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
}));
