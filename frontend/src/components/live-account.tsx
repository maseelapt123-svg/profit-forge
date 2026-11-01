import { useQuery } from "@tanstack/react-query";
import { Alert, Platform, Switch, Text, View } from "react-native";

import { api } from "@/src/api";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Status = { configured: boolean; env: "testnet" | "live"; balances: { asset: string; free: string; locked: string }[]; error: string | null };

function confirm(msg: string, ok: () => void) {
  if (Platform.OS === "web") {
    if (window.confirm(msg)) ok();
    return;
  }
  Alert.alert("Conta real", msg, [{ text: "Cancelar", style: "cancel" }, { text: "Ativar", style: "destructive", onPress: ok }]);
}

/** Real-account execution through Binance Spot (testnet first). Only crypto BUY entries are sent. */
export function LiveAccount({ mode, maxUsd, onMode, onMax }: { mode: string; maxUsd: number; onMode: (m: "paper" | "binance") => void; onMax: (v: number) => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["live-status"], queryFn: () => api<Status>("/live/status"), refetchInterval: 60000 });
  const s = q.data;
  const on = mode === "binance";
  const envLabel = s?.env === "live" ? "REAL" : "TESTNET";
  return (
    <View style={styles.card} testID="bot-live">
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Conta real · Binance</Text>
          <Text style={styles.muted}>
            As compras de cripto do robô são enviadas para a Binance (Spot). Vendas a descoberto, forex e ações continuam na conta simulada.
          </Text>
        </View>
        <Switch
          testID="bot-live-switch"
          value={on}
          disabled={!s?.configured}
          onValueChange={(v) =>
            v ? confirm(`Ativar ordens reais na Binance (${envLabel})? Cada compra usa no máximo ${maxUsd} USDT.`, () => onMode("binance")) : onMode("paper")
          }
          trackColor={{ true: colors.error, false: colors.surfaceTertiary }}
          thumbColor={colors.onBrandPrimary}
        />
      </View>
      {!s ? null : !s.configured ? (
        <Text style={styles.muted}>Ainda sem chaves da Binance. Adiciona-as para ligar a conta.</Text>
      ) : (
        <>
          <Text style={[styles.badge, { color: s.env === "live" ? colors.error : colors.warning }]} testID="bot-live-env">
            {s.env === "live" ? "● Conta REAL — dinheiro real" : "● Testnet — dinheiro de teste"}
          </Text>
          {s.error ? (
            <Text style={[styles.muted, { color: colors.error }]}>Erro Binance: {s.error}</Text>
          ) : (
            <Text style={styles.muted} testID="bot-live-balances">
              Saldo: {s.balances.filter((b) => ["USDT", "BTC", "ETH", "BNB", "SOL"].includes(b.asset)).map((b) => `${Number(b.free).toLocaleString("pt-PT", { maximumFractionDigits: 6 })} ${b.asset}`).join(" · ") || "—"}
            </Text>
          )}
          <View style={styles.row}>
            <Text style={[styles.muted, { flex: 1 }]}>Máximo por ordem</Text>
            {[10, 25, 50, 100, 250].map((v) => (
              <Text key={v} onPress={() => onMax(v)} style={[styles.chip, v === maxUsd && { color: colors.brandPrimary, borderColor: colors.brandPrimary }]} testID={`bot-live-max-${v}`}>
                {v}$
              </Text>
            ))}
          </View>
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginVertical: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.error, padding: 12, gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16, marginBottom: 2 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  badge: { fontFamily: fonts.displaySemi, fontSize: 13 },
  row: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  chip: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13, borderWidth: 1, borderColor: c.border, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 10, overflow: "hidden" },
}));
