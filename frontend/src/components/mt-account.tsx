import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, TextInput, View } from "react-native";

import { api, money } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Acc = {
  login: string; server: string; platform: string; state?: string; connection?: string; balance?: number; equity?: number;
  currency?: string; type?: string; broker?: string; positions?: number;
};
type Status = { configured: boolean; account: Acc | null; error: string | null };

/** Connect an MT4/MT5 (demo) account through MetaApi; the bot's trades then appear in the MetaTrader app. */
export function MtAccount({ maxLots, suffix, onMaxLots, onSuffix }: { maxLots: number; suffix: string; onMaxLots: (v: number) => void; onSuffix: (v: string) => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["mt-status"], queryFn: () => api<Status>("/live/mt/status"), refetchInterval: 20000 });
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState("");
  const [platform, setPlatform] = useState("mt4");
  const connect = useMutation({
    mutationFn: () => api("/live/mt/connect", { method: "POST", body: { login: login.trim(), password, server: server.trim(), platform } }),
    onSuccess: () => {
      setPassword("");
      toast("Conta enviada para a MetaApi — a ligar (pode demorar 1–2 min)", "success");
      qc.invalidateQueries({ queryKey: ["mt-status"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const disconnect = useMutation({
    mutationFn: () => api("/live/mt", { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mt-status"] });
      qc.invalidateQueries({ queryKey: ["bot"] });
    },
  });
  const s = q.data;
  const a = s?.account;
  return (
    <View style={styles.card} testID="bot-mt">
      <Text style={styles.title}>MetaTrader (MT4/MT5)</Text>
      <Button label="Robô MT5 (todas as estratégias)" variant="ghost" onPress={() => router.push("/ea-guide")} testID="mt-download-ea" />
      {!s ? null : !s.configured ? (
        <Text style={styles.muted}>Falta o token MetaApi (metaapi.cloud). Adiciona-o para ligar a conta demo.</Text>
      ) : a ? (
        <>
          <Text style={styles.label} testID="mt-account">
            {a.platform?.toUpperCase()} {a.login} · {a.server}
          </Text>
          <Text style={[styles.muted, { color: a.connection === "CONNECTED" ? colors.success : colors.warning }]} testID="mt-connection">
            {a.connection === "CONNECTED" ? "● Ligada" : `● ${a.state ?? "a preparar"} · ${a.connection ?? "a ligar"}`}
            {a.type ? ` · ${a.type.includes("DEMO") ? "Demo" : "Real"}` : ""}
          </Text>
          {a.balance != null && (
            <Text style={styles.muted}>
              Saldo {money(a.balance)} · Capital {money(a.equity ?? a.balance)} {a.currency} · {a.positions ?? 0} posição(ões)
            </Text>
          )}
          {s.error && <Text style={[styles.muted, { color: colors.error }]}>{s.error}</Text>}
          <View style={styles.row}>
            <Text style={[styles.muted, { flex: 1 }]}>Máx. lotes por ordem</Text>
            {[0.01, 0.05, 0.1, 0.5, 1].map((v) => (
              <Text key={v} onPress={() => onMaxLots(v)} style={[styles.chip, v === maxLots && { color: colors.brandPrimary, borderColor: colors.brandPrimary }]} testID={`mt-lots-${v}`}>
                {v}
              </Text>
            ))}
          </View>
          <TextInput
            value={suffix}
            onChangeText={onSuffix}
            placeholder="Sufixo dos símbolos na corretora (ex.: .m) — opcional"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            style={styles.input}
            testID="mt-suffix"
          />
          <Button label="Desligar conta" variant="ghost" onPress={() => disconnect.mutate()} loading={disconnect.isPending} testID="mt-disconnect" />
        </>
      ) : (
        <>
          <Text style={styles.muted}>Usa os dados da conta demo (login, password principal e servidor exatamente como no MetaTrader). A password não é guardada na app.</Text>
          <ChipRow options={[{ value: "mt4", label: "MT4" }, { value: "mt5", label: "MT5" }]} value={platform} onChange={setPlatform} testID="mt-platform" />
          <TextInput value={login} onChangeText={setLogin} placeholder="Login (número da conta)" placeholderTextColor={colors.muted} keyboardType="number-pad" style={styles.input} testID="mt-login" />
          <TextInput value={password} onChangeText={setPassword} placeholder="Password principal" placeholderTextColor={colors.muted} secureTextEntry style={styles.input} testID="mt-password" />
          <TextInput value={server} onChangeText={setServer} placeholder="Servidor (ex.: FOREX.com-Demo 535)" placeholderTextColor={colors.muted} autoCapitalize="none" style={styles.input} testID="mt-server" />
          <Button label="Ligar conta MetaTrader" onPress={() => connect.mutate()} loading={connect.isPending} disabled={!login || !password || !server} testID="mt-connect" />
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { marginHorizontal: 16, marginVertical: 8, backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.brandTertiary, padding: 12, gap: 8 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 16 },
  label: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 14 },
  muted: { color: c.muted, fontFamily: fonts.text, fontSize: 12, lineHeight: 17 },
  input: { height: 48, borderRadius: 10, borderWidth: 1, borderColor: c.border, paddingHorizontal: 12, color: c.onSurface, fontFamily: fonts.text, fontSize: 15, backgroundColor: c.surface },
  row: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  chip: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13, borderWidth: 1, borderColor: c.border, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 10, overflow: "hidden" },
}));
