import { createContext, useContext, useEffect, useState, useCallback } from "react";

/**
 * Mock client-side auth.
 *
 * ⚠ ATENÇÃO: isto é um stub. Qualquer email com `@` + senha com >=6 chars
 * vira "usuário logado" e persiste em localStorage. Antes de produção,
 * substituir por chamada real a /api/auth/login com JWT/cookie.
 */

const STORAGE_KEY = "aurum_auth";
const AuthContext = createContext(null);

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.email === "string") return parsed;
  } catch {
    /* fall through */
  }
  return null;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => loadFromStorage());

  useEffect(() => {
    if (user) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [user]);

  const login = useCallback(async (email, password) => {
    // Mock validation — swap for real API call before production.
    if (!email || !email.includes("@")) {
      throw new Error("Email inválido.");
    }
    if (!password || password.length < 6) {
      throw new Error("Senha precisa ter pelo menos 6 caracteres.");
    }
    const nextUser = {
      email: email.trim().toLowerCase(),
      loggedInAt: new Date().toISOString(),
    };
    setUser(nextUser);
    return nextUser;
  }, []);

  const logout = useCallback(() => {
    setUser(null);
  }, []);

  const value = {
    user,
    login,
    logout,
    isAuthenticated: Boolean(user),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within <AuthProvider>.");
  }
  return ctx;
}
