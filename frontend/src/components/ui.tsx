import * as Haptics from "expo-haptics";
import React from "react";
import { ActivityIndicator, Platform, Pressable, ScrollView, Text, View, ViewStyle } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from "react-native-reanimated";

import { fonts, makeStyles, useTheme } from "@/src/theme";

export const haptic = (kind: "light" | "medium" | "heavy" = "light") => {
  if (Platform.OS === "web") return;
  const map = { light: Haptics.ImpactFeedbackStyle.Light, medium: Haptics.ImpactFeedbackStyle.Medium, heavy: Haptics.ImpactFeedbackStyle.Heavy };
  Haptics.impactAsync(map[kind]).catch(() => {});
};

const APressable = Animated.createAnimatedComponent(Pressable);

export function PressableScale({ children, style, onPress, disabled, testID }: {
  children: React.ReactNode; style?: any; onPress?: () => void; disabled?: boolean; testID?: string;
}) {
  const s = useSharedValue(1);
  const a = useAnimatedStyle(() => ({ transform: [{ scale: s.value }] }));
  return (
    <APressable
      testID={testID}
      disabled={disabled}
      onPressIn={() => (s.value = withSpring(0.97, { damping: 20 }))}
      onPressOut={() => (s.value = withSpring(1, { damping: 20 }))}
      onPress={onPress}
      style={[style, a, disabled && { opacity: 0.5 }]}
    >
      {children}
    </APressable>
  );
}

export function Button({ label, onPress, variant = "primary", loading, disabled, testID, style }: {
  label: string; onPress: () => void; variant?: "primary" | "buy" | "sell" | "ghost"; loading?: boolean; disabled?: boolean; testID?: string; style?: ViewStyle;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const bg = { primary: colors.brandPrimary, buy: colors.success, sell: colors.error, ghost: colors.surfaceTertiary }[variant];
  return (
    <PressableScale
      testID={testID}
      disabled={disabled || loading}
      onPress={() => {
        haptic("medium");
        onPress();
      }}
      style={[styles.btn, { backgroundColor: bg }, style]}
    >
      {loading ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.btnText}>{label}</Text>}
    </PressableScale>
  );
}

export function Segmented<T extends string>({ options, value, onChange, testID }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; testID?: string;
}) {
  const styles = useStyles();
  return (
    <View style={styles.seg} testID={testID}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            testID={`${testID}-${o.value}`}
            onPress={() => {
              haptic("light");
              onChange(o.value);
            }}
            style={[styles.segItem, active && styles.segActive]}
          >
            <Text style={[styles.segText, active && styles.segTextActive]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function ChipRow<T extends string>({ options, value, onChange, testID }: {
  options: { value: T; label: string }[]; value: T | T[]; onChange: (v: T) => void; testID?: string;
}) {
  const styles = useStyles();
  const isActive = (v: T) => (Array.isArray(value) ? value.includes(v) : value === v);
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.chipRow}
      contentContainerStyle={styles.chipRowContent}
      testID={testID}
    >
      {options.map((o) => (
        <Pressable
          key={o.value}
          testID={`${testID}-${o.value}`}
          onPress={() => {
            haptic("light");
            onChange(o.value);
          }}
          style={[styles.chip, isActive(o.value) && styles.chipActive]}
        >
          <Text style={[styles.chipText, isActive(o.value) && styles.chipTextActive]}>{o.label}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

export function Pill({ value, testID }: { value: number; testID?: string }) {
  const styles = useStyles();
  const up = value >= 0;
  return (
    <View style={[styles.pill, up ? styles.pillUp : styles.pillDown]} testID={testID}>
      <Text style={[styles.pillText, up ? styles.up : styles.down]}>
        {up ? "+" : ""}
        {value.toFixed(2)}%
      </Text>
    </View>
  );
}

export function SideBadge({ dir }: { dir: "BUY" | "SELL" | "NEUTRAL" }) {
  const styles = useStyles();
  const label = { BUY: "COMPRA", SELL: "VENDA", NEUTRAL: "NEUTRO" }[dir];
  const st = dir === "BUY" ? styles.pillUp : dir === "SELL" ? styles.pillDown : styles.pillNeutral;
  const tx = dir === "BUY" ? styles.up : dir === "SELL" ? styles.down : styles.neutral;
  return (
    <View style={[styles.pill, st]}>
      <Text style={[styles.pillText, tx]}>{label}</Text>
    </View>
  );
}

export function AssetBadge({ symbol }: { symbol: string }) {
  const styles = useStyles();
  const t = symbol.replace("-USD", "").replace("=X", "").replace("=F", "").slice(0, 3);
  return (
    <View style={styles.badge}>
      <Text style={styles.badgeText}>{t}</Text>
    </View>
  );
}

export function Center({ children }: { children: React.ReactNode }) {
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 12 }}>{children}</View>;
}

const useStyles = makeStyles((c) => ({
  btn: { height: 56, borderRadius: 999, alignItems: "center", justifyContent: "center", paddingHorizontal: 24 },
  btnText: { color: c.onBrandPrimary, fontFamily: fonts.display, fontSize: 18, letterSpacing: 0.5 },
  seg: { flexDirection: "row", backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 4, borderWidth: 1, borderColor: c.border },
  segItem: { flex: 1, height: 36, alignItems: "center", justifyContent: "center", borderRadius: 8 },
  segActive: { backgroundColor: c.surfaceTertiary },
  segText: { color: c.muted, fontFamily: fonts.displaySemi, fontSize: 15 },
  segTextActive: { color: c.onSurface },
  chipRow: { flexGrow: 0, height: 56 },
  chipRowContent: { gap: 8, paddingHorizontal: 16, alignItems: "center" },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: c.borderStrong, justifyContent: "center", backgroundColor: c.surfaceSecondary },
  chipActive: { borderColor: c.brandPrimary, backgroundColor: c.brandSoft },
  chipText: { color: c.onSurfaceSecondary, fontFamily: fonts.displaySemi, fontSize: 14 },
  chipTextActive: { color: c.brandPrimary },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  pillUp: { backgroundColor: c.successSoft },
  pillDown: { backgroundColor: c.errorSoft },
  pillNeutral: { backgroundColor: c.surfaceTertiary },
  pillText: { fontFamily: fonts.display, fontSize: 13 },
  up: { color: c.success },
  down: { color: c.error },
  neutral: { color: c.onSurfaceSecondary },
  badge: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.borderStrong },
  badgeText: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 13 },
}));
