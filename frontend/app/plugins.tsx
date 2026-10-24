import { Ionicons } from "@react-native-vector-icons/ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Switch, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Center, haptic } from "@/src/components/ui";
import { fonts, makeStyles, useTheme } from "@/src/theme";

type Cfg = Record<string, Record<string, any>>;
type Meta = Record<string, { label: string; desc: string; params: Record<string, string> }>;

export default function Plugins() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plugins"], queryFn: () => api<{ plugins: Cfg; meta: Meta }>("/plugins") });
  const [cfg, setCfg] = useState<Cfg | null>(null);
  useEffect(() => {
    if (q.data && !cfg) setCfg(q.data.plugins);
  }, [q.data, cfg]);
  const save = useMutation({
    mutationFn: () => api("/plugins", { method: "PUT", body: { plugins: cfg } }),
    onSuccess: () => {
      toast("Configurações guardadas", "success");
      qc.invalidateQueries({ queryKey: ["plugins"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
      router.back();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const update = (k: string, p: string, v: any) => setCfg((c) => (c ? { ...c, [k]: { ...c[k], [p]: v } } : c));

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="plugins-screen">
      <View style={styles.header}>
        <Text style={styles.title}>Plugins de Estratégia</Text>
        <Pressable testID="plugins-close-button" onPress={() => router.back()} style={styles.close}>
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </Pressable>
      </View>
      {!cfg || !q.data ? (
        <Center>
          <ActivityIndicator color={colors.brandPrimary} />
        </Center>
      ) : (
        <KeyboardAwareScrollView bottomOffset={100} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 120 }}>
          <Text style={styles.intro}>Ativa os plugins que geram sinais. A estratégia «Combo» do backtest usa os plugins ativos com filtro de tendência EMA200.</Text>
          {Object.entries(q.data.meta).map(([key, meta]) => {
            const c = cfg[key];
            return (
              <View key={key} style={[styles.card, c.enabled && styles.cardOn]} testID={`plugin-${key}`}>
                <View style={styles.row}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.label}>{meta.label}</Text>
                    <Text style={styles.desc}>{meta.desc}</Text>
                  </View>
                  <Switch
                    testID={`plugin-toggle-${key}`}
                    value={!!c.enabled}
                    onValueChange={(v) => {
                      haptic("light");
                      update(key, "enabled", v);
                    }}
                    trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
                    thumbColor={colors.onBrandPrimary}
                  />
                </View>
                {c.enabled && (
                  <View style={styles.params}>
                    {Object.entries(meta.params).map(([p, plabel]) => (
                      <View key={p} style={styles.param}>
                        <Text style={styles.paramLabel}>{plabel}</Text>
                        <TextInput
                          testID={`plugin-param-${key}-${p}`}
                          style={styles.input}
                          keyboardType="decimal-pad"
                          value={String(c[p] ?? "")}
                          onChangeText={(t) => update(key, p, t.replace(",", "."))}
                          placeholderTextColor={colors.muted}
                        />
                      </View>
                    ))}
                  </View>
                )}
              </View>
            );
          })}
        </KeyboardAwareScrollView>
      )}
      <KeyboardStickyView offset={{ opened: insets.bottom }}>
        <View style={[styles.sticky, { paddingBottom: insets.bottom + 12 }]}>
          <Button label="Guardar Configurações" onPress={() => save.mutate()} loading={save.isPending} disabled={!cfg} testID="plugins-save-button" />
        </View>
      </KeyboardStickyView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.border },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24 },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22, backgroundColor: c.surfaceSecondary },
  intro: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 13, lineHeight: 19 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: 12, borderWidth: 1, borderColor: c.border, padding: 16, gap: 12 },
  cardOn: { borderColor: c.brandSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  label: { color: c.onSurface, fontFamily: fonts.display, fontSize: 18 },
  desc: { color: c.muted, fontFamily: fonts.text, fontSize: 12 },
  params: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  param: { flexGrow: 1, flexBasis: "30%", gap: 4 },
  paramLabel: { color: c.muted, fontFamily: fonts.text, fontSize: 11 },
  input: { height: 44, borderRadius: 8, backgroundColor: c.surfaceTertiary, color: c.onSurfaceTertiary, paddingHorizontal: 12, fontFamily: fonts.display, fontSize: 16, borderWidth: 1, borderColor: c.borderStrong },
  sticky: { paddingHorizontal: 16, paddingTop: 12, backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.border },
}));
