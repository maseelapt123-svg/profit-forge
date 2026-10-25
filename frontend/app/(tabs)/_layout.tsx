import { Ionicons } from "@react-native-vector-icons/ionicons";
import { Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
import { Platform } from "react-native";

import { haptic } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { colors, fonts } from "@/src/theme";

export default function TabsLayout() {
  if (usesNativeTabs) {
    return (
      <NativeTabs tintColor={colors.brandPrimary}>
        <NativeTabs.Trigger name="index">
          <NativeTabs.Trigger.Icon sf="chart.line.uptrend.xyaxis" />
          <NativeTabs.Trigger.Label>Mercados</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="hfx">
          <NativeTabs.Trigger.Icon sf="timer" />
          <NativeTabs.Trigger.Label>HFX</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="backtest">
          <NativeTabs.Trigger.Icon sf="clock.arrow.circlepath" />
          <NativeTabs.Trigger.Label>Backtest</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="portfolio">
          <NativeTabs.Trigger.Icon sf="briefcase.fill" />
          <NativeTabs.Trigger.Label>Portfólio</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
      </NativeTabs>
    );
  }
  const icon = (name: any) =>
    function TabIcon({ color, size }: { color: string; size: number }) {
      return <Ionicons name={name} color={color} size={size} />;
    };
  return (
    <Tabs
      screenListeners={{ tabPress: () => haptic("light") }}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brandPrimary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          ...(Platform.OS === "web" ? { height: 64 } : {}),
        },
        tabBarItemStyle: { alignSelf: "center" },
        tabBarLabelStyle: { fontFamily: fonts.displaySemi, fontSize: 12 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Mercados", tabBarIcon: icon("stats-chart"), tabBarButtonTestID: "tab-markets" } as any} />
      <Tabs.Screen name="hfx" options={{ title: "HFX", tabBarIcon: icon("timer"), tabBarButtonTestID: "tab-hfx" } as any} />
      <Tabs.Screen name="backtest" options={{ title: "Backtest", tabBarIcon: icon("time"), tabBarButtonTestID: "tab-backtest" } as any} />
      <Tabs.Screen name="portfolio" options={{ title: "Portfólio", tabBarIcon: icon("briefcase"), tabBarButtonTestID: "tab-portfolio" } as any} />
    </Tabs>
  );
}
