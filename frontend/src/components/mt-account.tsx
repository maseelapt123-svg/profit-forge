import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, TextInput, View } from "react-native";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, ChipRow } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Acc = {
  login: string; server: string; platform: string; state?: string; connection?: string; balance?: number; equity?: number;
  currency?: string; type?: string; broker?: string; positions?: number;
};
type Status = { configured: boolean; account: Acc | null; error: string | null };
type MetaAcc = { id: string; name: string; login: string; server: string; platform: string; state: string };
type TestOrder = { symbol: string; side: string; volume: number; price: number; position_id: string | null };

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
  const existing = useQuery({ queryKey: ["mt-accounts"], queryFn: () => api<MetaAcc[]>("/live/mt/accounts"), enabled: !!s?.configured && !a });
  const link = useMutation({
    mutationFn: (id: string) => api<{ deploy_error: string | null }>("/live/mt/link", { method: "POST", body: { account_id: id } }),
    onSuccess: (r) => {
      toast(r.deploy_error ?? "Conta ligada — a ligar à corretora (1–2 min)", r.deploy_error ? "error" : "success");
      qc.invalidateQueries({ queryKey: ["mt-status"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const deploy = useMutation({
    mutationFn: () => api("/live/mt/deploy", { method: "POST" }),
    onSuccess: () => {
      toast("A ligar a conta à corretora (1–2 min)", "success");
      qc.invalidateQueries({ queryKey: ["mt-status"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const [lastTest, setLastTest] = useState<TestOrder | null>(null);
  const [testSym, setTestSym] = useState("BTCUSD");
  const test = useMutation({
    mutationFn: (side: "BUY" | "SELL") => api<TestOrder>("/live/mt/test-order", { method: "POST", body: { symbol: testSym, side } }),
    onSuccess: (r) => {
      setLastTest(r);
      toast(`Ordem ${r.side === "BUY" ? "de compra" : "de venda"} ${r.volume} ${r.symbol} executada no MetaTrader`, "success");
      qc.invalidateQueries({ queryKey: ["mt-status"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const closeTest = useMutation({
    mutationFn: (id: string) => api("/live/mt/test-close", { method: "POST", body: { position_id: id } }),
    onSuccess: () => {
      setLastTest(null);
      toast("Posição de teste fechada", "success");
      qc.invalidateQueries({ queryKey: ["mt-status"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
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
              Saldo {a.balance.toFixed(2)} · Capital {(a.equity ?? a.balance).toFixed(2)} {a.currency} · {a.positions ?? 0} posição(ões)
            </Text>
          )}
          {s.error && <Text style={[styles.muted, { color: colors.error }]}>{s.error}</Text>}
          {a.state !== "DEPLOYED" && (
            <>
              <Text style={styles.muted}>A conta está desligada na MetaApi. Liga-a aqui (ou em app.metaapi.cloud → Accounts → Deploy).</Text>
              <Button label="Ligar conta à corretora" onPress={() => deploy.mutate()} loading={deploy.isPending} testID="mt-deploy" />
            </>
          )}
          {a.connection === "CONNECTED" && (
            <View style={styles.testBox} testID="mt-test-box">
              <Text style={styles.label}>Ordem de teste (lote mínimo, stop 0,3% · alvo 1:2)</Text>
              <ChipRow
                options={[{ value: "BTCUSD", label: "BTCUSD (24/7)" }, { value: "EURUSD", label: "EURUSD" }, { value: "XAUUSD", label: "Ouro" }]}
                value={testSym}
                onChange={setTestSym}
                testID="mt-test-symbol"
              />
              <Text style={styles.muted}>Forex e ouro fecham ao fim de semana; cripto negoceia sempre.</Text>
              <View style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Button label="Comprar" onPress={() => test.mutate("BUY")} loading={test.isPending && test.variables === "BUY"} testID="mt-test-buy" />
                </View>
                <View style={{ flex: 1 }}>
                  <Button label="Vender" variant="ghost" onPress={() => test.mutate("SELL")} loading={test.isPending && test.variables === "SELL"} testID="mt-test-sell" />
                </View>
              </View>
              {lastTest && (
                <>
                  <Text style={[styles.muted, { color: colors.success }]} testID="mt-test-result">
                    ✓ {lastTest.side === "BUY" ? "Compra" : "Venda"} {lastTest.volume} {lastTest.symbol} @ {lastTest.price} · posição {lastTest.position_id}
                  </Text>
                  {lastTest.position_id && (
                    <Button label="Fechar posição de teste" variant="ghost" onPress={() => closeTest.mutate(String(lastTest.position_id))} loading={closeTest.isPending} testID="mt-test-close" />
                  )}
                </>
              )}
            </View>
          )}
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
          {!!existing.data?.length && (
            <View style={{ gap: 8 }} testID="mt-existing">
              <Text style={styles.label}>Contas já criadas na tua MetaApi</Text>
              {existing.data.map((x) => (
                <View key={x.id} style={styles.testBox}>
                  <Text style={styles.label}>
                    {x.platform?.toUpperCase()} {x.login} · {x.server}
                  </Text>
                  <Text style={styles.muted}>{x.name} · {x.state === "DEPLOYED" ? "ligada" : "desligada"}</Text>
                  <Button label="Usar esta conta" onPress={() => link.mutate(x.id)} loading={link.isPending && link.variables === x.id} testID={`mt-link-${x.login}`} />
                </View>
              ))}
              <Text style={styles.muted}>Ou adiciona outra conta:</Text>
            </View>
          )}
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
  testBox: { gap: 8, borderRadius: 10, borderWidth: 1, borderColor: c.border, padding: 12, backgroundColor: c.surface },
  chip: { color: c.onSurface, fontFamily: fonts.displaySemi, fontSize: 13, borderWidth: 1, borderColor: c.border, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 10, overflow: "hidden" },
}));
