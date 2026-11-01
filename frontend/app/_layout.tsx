import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, LogBox, StyleSheet, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { AuthProvider, useAuth } from "@/src/auth";
import { ErrorBoundary } from "@/src/components/error-boundary";
import { ToastProvider } from "@/src/components/toast";
import { queryClient } from "@/src/query-client";
import { colors } from "@/src/theme";

LogBox.ignoreAllLogs(true);

function Gate() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <View style={styles.splash} testID="auth-loading">
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }}>
      <Stack.Protected guard={!!user}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="chart/[symbol]" />
        <Stack.Screen name="plugins" options={{ presentation: "modal" }} />
        <Stack.Screen name="bot" />
        <Stack.Screen name="signals" />
        <Stack.Screen name="tools" />
        <Stack.Screen name="patterns" />
        <Stack.Screen name="calculator" />
        <Stack.Screen name="hfx-bot" />
        <Stack.Screen name="hfx-plugins" />
        <Stack.Screen name="hfx-optimizer" />
        <Stack.Screen name="analysis" />
        <Stack.Screen name="daily" />
        <Stack.Screen name="ai-stats" />
        <Stack.Screen name="results" />
        <Stack.Screen name="ea-guide" />
      </Stack.Protected>
      <Stack.Protected guard={!user}>
        <Stack.Screen name="login" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  const [loaded] = useFonts({
    "Rajdhani-Bold": require("../assets/fonts/Rajdhani-Bold.ttf"),
    "Rajdhani-SemiBold": require("../assets/fonts/Rajdhani-SemiBold.ttf"),
    IBMPlexSans: require("../assets/fonts/IBMPlexSans-Var.ttf"),
  });
  return (
    <GestureHandlerRootView style={styles.root}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <KeyboardProvider>
            <StatusBar style="light" />
            {loaded ? (
              <ToastProvider>
                <AuthProvider>
                  <Gate />
                </AuthProvider>
              </ToastProvider>
            ) : (
              <View style={styles.splash} />
            )}
          </KeyboardProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  splash: { flex: 1, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
});
