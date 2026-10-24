import { Ionicons } from "@react-native-vector-icons/ionicons";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { fonts, makeStyles, useTheme } from "@/src/theme";

const BG = "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

export default function Login() {
  const { signIn, signingIn, error } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.root} testID="login-screen">
      <Image source={{ uri: BG }} style={styles.bg} contentFit="cover" />
      <LinearGradient colors={["transparent", colors.surface]} locations={[0, 0.7]} style={styles.bg} />
      <LinearGradient colors={[colors.brandTertiary, "transparent"]} locations={[0, 0.4]} style={[styles.bg, { opacity: 0.5 }]} />
      <View style={[styles.content, { paddingTop: insets.top + 48, paddingBottom: insets.bottom + 24 }]}>
        <Animated.View entering={FadeInDown.duration(600)}>
          <View style={styles.logoRow}>
            <View style={styles.logo}>
              <Ionicons name="pulse" size={26} color={colors.onBrandPrimary} />
            </View>
            <Text style={styles.brand}>SMARTTRADE AI</Text>
          </View>
        </Animated.View>
        <Animated.View entering={FadeInDown.delay(200).duration(600)} style={styles.bottom}>
          <Text style={styles.title}>Smart Money,{"\n"}backtest e IA{"\n"}num só lugar.</Text>
          <Text style={styles.sub}>
            Deteta order blocks, FVG e quebras de estrutura em cripto, forex e ações. Testa estratégias antes de arriscar.
          </Text>
          {error && (
            <Text style={styles.error} testID="login-error">
              {error}
            </Text>
          )}
          <Pressable testID="google-login-button" style={styles.google} onPress={signIn} disabled={signingIn}>
            {signingIn ? (
              <ActivityIndicator color={colors.onSurfaceInverse} />
            ) : (
              <>
                <Ionicons name="logo-google" size={20} color={colors.onSurfaceInverse} />
                <Text style={styles.googleText}>Entrar com Google</Text>
              </>
            )}
          </Pressable>
          <Text style={styles.disclaimer}>Trading envolve risco. Começas com uma conta simulada de $10.000.</Text>
        </Animated.View>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  bg: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  content: { flex: 1, paddingHorizontal: 24, justifyContent: "space-between" },
  logoRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  logo: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  brand: { color: c.onSurface, fontFamily: fonts.display, fontSize: 24, letterSpacing: 2 },
  bottom: { gap: 16 },
  title: { color: c.onSurface, fontFamily: fonts.display, fontSize: 44, lineHeight: 46 },
  sub: { color: c.onSurfaceSecondary, fontFamily: fonts.text, fontSize: 15, lineHeight: 22 },
  error: { color: c.error, fontFamily: fonts.text, fontSize: 14 },
  google: { height: 56, borderRadius: 999, backgroundColor: c.surfaceInverse, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 12, marginTop: 8 },
  googleText: { color: c.onSurfaceInverse, fontFamily: fonts.display, fontSize: 18 },
  disclaimer: { color: c.muted, fontFamily: fonts.text, fontSize: 12, textAlign: "center" },
}));
