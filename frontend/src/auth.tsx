import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";

import { TOKEN_KEY, api, clearStoredToken, setToken, setUnauthorizedHandler } from "@/src/api";
import { storage } from "@/src/utils/storage";

WebBrowser.maybeCompleteAuthSession();

export type User = { user_id: string; email: string; name?: string; picture?: string };
type Ctx = {
  user: User | null;
  loading: boolean;
  signingIn: boolean;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<Ctx>(null as any);
export const useAuth = () => useContext(AuthContext);

const extractSessionId = (url?: string | null) => {
  if (!url) return null;
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const used = useRef(new Set<string>());

  const exchange = useCallback(async (sessionId: string) => {
    if (used.current.has(sessionId)) return false;
    used.current.add(sessionId);
    try {
      const res = await api<{ session_token: string; user: User }>("/auth/session", {
        method: "POST",
        body: { session_id: sessionId },
      });
      setToken(res.session_token);
      await storage.secureSet(TOKEN_KEY, res.session_token);
      setUser(res.user);
      setError(null);
      return true;
    } catch {
      setError("Falha na autenticação. Tenta novamente.");
      return false;
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    let sub: { remove: () => void } | undefined;
    (async () => {
      // 1) session_id in URL first
      let sid: string | null = null;
      if (Platform.OS === "web" && typeof window !== "undefined") {
        sid = extractSessionId(window.location.href);
        if (sid) {
          const ok = await exchange(sid);
          if (ok) {
            const clean = window.location.href.replace(/([?#&])session_id=[^&#]+&?/, "$1").replace(/[?#&]$/, "");
            window.history.replaceState(window.history.state, "", clean);
          }
        }
      } else {
        sid = extractSessionId(await Linking.getInitialURL());
        if (sid) await exchange(sid);
        sub = Linking.addEventListener("url", ({ url }) => {
          const s = extractSessionId(url);
          if (s) exchange(s);
        });
      }
      // 2) existing token
      if (!sid) {
        const t = await storage.secureGet(TOKEN_KEY, null);
        if (t) {
          setToken(t as string);
          try {
            setUser(await api<User>("/auth/me"));
          } catch {
            await clearStoredToken();
            setUser(null);
          }
        }
      }
      setLoading(false);
    })();
    return () => sub?.remove();
  }, [exchange]);

  const signIn = useCallback(async () => {
    setError(null);
    const redirectUrl = Platform.OS === "web" ? window.location.origin + "/" : Linking.createURL("");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    if (Platform.OS === "web") {
      window.location.href = authUrl;
      return;
    }
    setSigningIn(true);
    let captured: string | null = null;
    const sub = Linking.addEventListener("url", ({ url }) => {
      captured = url;
    });
    try {
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
      const url = (result.type === "success" ? result.url : null) ?? captured ?? (await Linking.getInitialURL());
      const sid = extractSessionId(url);
      if (sid) await exchange(sid);
    } catch {
      setError("Falha na autenticação. Tenta novamente.");
    } finally {
      sub.remove();
      setSigningIn(false);
    }
  }, [exchange]);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {}
    await clearStoredToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signingIn, error, signIn, signOut }}>{children}</AuthContext.Provider>
  );
}
