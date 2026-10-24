// Design tokens for this app (dark-first trading UI). Keys match the "color"
// block of /app/design_guidelines.json. Both schemes use the same dark palette.
import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const dark = {
  surface: "#101113",
  onSurface: "#F4F4F5",
  surfaceSecondary: "#1C1C1E",
  onSurfaceSecondary: "#A1A1AA",
  surfaceTertiary: "#27272A",
  onSurfaceTertiary: "#E4E4E7",
  surfaceInverse: "#FAFAFA",
  onSurfaceInverse: "#101113",
  muted: "#71717A",

  brand: "#EA580C",
  onBrand: "#FFFFFF",
  brandPrimary: "#EA580C",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#C2410C",
  onBrandSecondary: "#FFFFFF",
  brandTertiary: "#7C2D12",
  onBrandTertiary: "#FFEDD5",

  success: "#10B981",
  onSuccess: "#FFFFFF",
  successSoft: "rgba(16,185,129,0.14)",
  warning: "#F59E0B",
  onWarning: "#FFFFFF",
  error: "#EF4444",
  onError: "#FFFFFF",
  errorSoft: "rgba(239,68,68,0.14)",
  info: "#3B82F6",
  onInfo: "#FFFFFF",
  brandSoft: "rgba(234,88,12,0.14)",
  scrim: "rgba(0,0,0,0.6)",

  border: "#27272A",
  borderStrong: "#3F3F46",
  divider: "#27272A",
};

export type ThemeColors = typeof dark;

export const fonts = {
  display: "Rajdhani-Bold",
  displaySemi: "Rajdhani-SemiBold",
  text: "IBMPlexSans",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };
export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };

export const defaultScheme = "dark" satisfies ColorScheme;

export const themes: { light: ThemeColors; dark?: ThemeColors } = { light: dark, dark };

export const colors = dark;

export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

setColorScheme?.("dark");

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const scheme: ColorScheme = (system === "light" || system === "dark") && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? dark };
}

export function makeStyles<T extends StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>>(
  factory: (colors: ThemeColors) => T & StyleSheet.NamedStyles<any>,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}
