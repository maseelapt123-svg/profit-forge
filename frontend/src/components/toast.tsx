import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Text } from "react-native";
import Animated, { FadeInUp, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fonts, makeStyles } from "@/src/theme";

type Kind = "success" | "error" | "info";
const ToastCtx = createContext<(msg: string, kind?: Kind) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<{ msg: string; kind: Kind; id: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const show = useCallback((msg: string, kind: Kind = "info") => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ msg, kind, id: Date.now() });
    timer.current = setTimeout(() => setToast(null), 2800);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && (
        <Animated.View
          key={toast.id}
          entering={FadeInUp}
          exiting={FadeOutUp}
          pointerEvents="none"
          style={[styles.toast, styles[toast.kind], { top: insets.top + 8 }]}
          testID="toast"
        >
          <Text style={styles.text}>{toast.msg}</Text>
        </Animated.View>
      )}
    </ToastCtx.Provider>
  );
}

const useStyles = makeStyles((c) => ({
  toast: {
    position: "absolute",
    left: 16,
    right: 16,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    backgroundColor: c.surfaceTertiary,
  },
  success: { borderColor: c.success },
  error: { borderColor: c.error },
  info: { borderColor: c.brandPrimary },
  text: { color: c.onSurface, fontFamily: fonts.text, fontSize: 14 },
}));
