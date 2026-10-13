import { useEffect, useMemo, useRef, useState } from "react";
import {
  AppState,
  ActivityIndicator,
  Alert,
  Image,
  Linking,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import { StatusBar } from "expo-status-bar";
import { api, apiHost, ApiError, Loan, Notification, User } from "./src/api";

const TOKEN_KEY = "credifresh_access_token";
const CLIENT_LINK_REQUIRED = "Tu cuenta aún no está vinculada a un perfil de cliente";
const colors = {
  ink: "#0D1B4C",
  deep: "#0D1B4C",
  teal: "#174BFF",
  green: "#21C56E",
  mint: "#E9F7EF",
  canvas: "#F5F7FA",
  muted: "#68728B",
  border: "#E5E7EB",
  white: "#ffffff",
  amber: "#986008",
};

function currency(value: number | string | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function dateLabel(value: string, includeTime = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  const options: Intl.DateTimeFormatOptions = includeTime
    ? { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Bogota" }
    : { day: "numeric", month: "long", year: "numeric", timeZone: "America/Bogota" };
  return new Intl.DateTimeFormat("es-CO", options).format(date);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    SOLICITADO: "En revisión",
    APROBADO: "Oferta aprobada",
    RECHAZADO: "No aprobado",
    DESEMBOLSADO: "Desembolsado",
    PAGADO: "Pagado",
  };
  return labels[status] || status;
}

function rateLabel(rate: number | string) {
  const value = Number(rate);
  return value > 0 ? `${value.toLocaleString("es-CO")} % mensual` : "Pendiente de asignación";
}

function installmentBalance(installment: Loan["cuotas"][number]) {
  return Math.max(0, Number(installment.monto_cuota) - Number(installment.monto_pagado));
}

function loanBalance(loan: Loan) {
  return loan.cuotas.reduce((balance, installment) => balance + installmentBalance(installment), 0);
}

function nextInstallment(loan: Loan) {
  return loan.cuotas
    .filter((installment) => installmentBalance(installment) > 0)
    .sort((a, b) => new Date(a.fecha_vencimiento).getTime() - new Date(b.fecha_vencimiento).getTime())[0];
}

function daysUntilDue(value: string) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return null;
  const todayParts = new Intl.DateTimeFormat("en", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(new Date());
  const today = Object.fromEntries(todayParts.map((part) => [part.type, Number(part.value)]));
  const todayUtc = Date.UTC(today.year, today.month - 1, today.day);
  const dueUtc = Date.UTC(year, month - 1, day);
  return Math.round((dueUtc - todayUtc) / 86_400_000);
}

function installmentStatusLabel(installment: Loan["cuotas"][number]) {
  if (installmentBalance(installment) <= 0) return "Pagada";
  const days = daysUntilDue(installment.fecha_vencimiento);
  if (days == null) return "Pendiente";
  if (days < 0) return `Vencida hace ${Math.abs(days)} ${Math.abs(days) === 1 ? "día" : "días"}`;
  if (days === 0) return "Vence hoy";
  if (days === 1) return "Vence mañana";
  if (days <= 7) return `Vence en ${days} días`;
  return "Pendiente";
}

function overdueBalance(loan: Loan) {
  return loan.cuotas.reduce((balance, installment) => {
    const days = daysUntilDue(installment.fecha_vencimiento);
    return days != null && days < 0 ? balance + installmentBalance(installment) : balance;
  }, 0);
}

function overdueInstallmentCount(loan: Loan) {
  return loan.cuotas.filter((installment) => {
    const days = daysUntilDue(installment.fecha_vencimiento);
    return days != null && days < 0 && installmentBalance(installment) > 0;
  }).length;
}

export default function App() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [notificationError, setNotificationError] = useState("");
  const [notificationBusyId, setNotificationBusyId] = useState<number | null>(null);
  const [markingAllNotifications, setMarkingAllNotifications] = useState(false);
  const [showAllNotifications, setShowAllNotifications] = useState(false);
  const [selectedLoanId, setSelectedLoanId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [confirmPassword, setConfirmPassword] = useState("");
  const emailRef = useRef<TextInput>(null);
  const passwordRef = useRef<TextInput>(null);
  const confirmPasswordRef = useRef<TextInput>(null);
  const [authMode, setAuthMode] = useState<"login" | "register" | "forgot" | "reset">("login");
  const [resetToken, setResetToken] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [editingContact, setEditingContact] = useState(false);
  const [needsLink, setNeedsLink] = useState(false);
  const [clientId, setClientId] = useState<number | null>(null);
  const [financialProfileReady, setFinancialProfileReady] = useState(false);
  const [editingFinancialProfile, setEditingFinancialProfile] = useState(false);
  const [income, setIncome] = useState("");
  const [expenses, setExpenses] = useState("");
  const [obligations, setObligations] = useState("");
  const [incomeType, setIncomeType] = useState("");
  const [economicActivity, setEconomicActivity] = useState("");
  const [requestedAmount, setRequestedAmount] = useState("500000");
  const [requestedTerm, setRequestedTerm] = useState("6");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [apiConnection, setApiConnection] = useState<"unknown" | "checking" | "connected" | "offline">("unknown");
  const [apiConnectionMessage, setApiConnectionMessage] = useState("");
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [pendingSessionToken, setPendingSessionToken] = useState<string | null>(null);

  const selectedLoan = useMemo(
    () => loans.find((item) => item.credito.id === selectedLoanId) || null,
    [loans, selectedLoanId],
  );
  const emailIsValid = /^[\w.-]+@[\w.-]+\.\w+$/.test(email.trim());
  const unreadNotificationCount = useMemo(
    () => notifications.filter((notification) => !notification.leida).length,
    [notifications],
  );
  const visibleNotifications = showAllNotifications ? notifications : notifications.slice(0, 5);

  useEffect(() => {
    const openResetLink = (url: string | null) => {
      if (!url || !url.includes("reset-password")) return;
      const match = url.match(/[?&]token=([^&]+)/);
      if (!match) return;
      setResetToken(decodeURIComponent(match[1]));
      setPassword("");
      setConfirmPassword("");
      setAuthMode("reset");
      setError("");
    };
    void Linking.getInitialURL().then(openResetLink);
    const subscription = Linking.addEventListener("url", ({ url }) => openResetLink(url));
    return () => subscription.remove();
  }, []);

  async function checkApiConnection() {
    if (checkingConnection) return;
    setCheckingConnection(true);
    setApiConnection("checking");
    setApiConnectionMessage("");
    try {
      const health = await api.health();
      if (health.status === "healthy") {
        setApiConnection("connected");
        setApiConnectionMessage("El API está activo y respondiendo.");
      } else {
        setApiConnection("offline");
        setApiConnectionMessage("El API respondió, pero no informó estado saludable.");
      }
    } catch (cause) {
      setApiConnection("offline");
      setApiConnectionMessage(cause instanceof Error ? cause.message : "No pudimos contactar el API.");
    } finally {
      setCheckingConnection(false);
    }
  }

  async function loadNotifications(accessToken: string) {
    try {
      setNotifications(await api.myNotifications(accessToken));
      setNotificationError("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) throw cause;
      setNotificationError("No pudimos cargar tus avisos. Puedes intentarlo de nuevo al actualizar.");
    }
  }

  async function loadAccount(accessToken: string) {
    const account = await api.me(accessToken);
    setApiConnection("connected");
    setApiConnectionMessage("El API está activo y respondiendo.");
    if (account.rol !== "CLIENTE") {
      throw new Error("Esta app es para clientes. Inicia sesión con una cuenta de cliente.");
    }
    setUser(account);
    await loadNotifications(accessToken);
    try {
      const profile = await api.myProfile(accessToken);
      setClientId(profile.id);
      setPhone(profile.telefono || "");
      setAddress(profile.direccion || "");
      setEditingContact(!profile.direccion);
      setNeedsLink(false);
      try {
        const financialProfile = await api.financialProfile(accessToken, profile.id);
        setIncome(String(financialProfile.ingresos_mensuales));
        setExpenses(String(financialProfile.gastos_mensuales));
        setObligations(String(financialProfile.otras_obligaciones));
        setIncomeType(financialProfile.tipo_ingresos);
        setEconomicActivity(financialProfile.actividad_economica);
        setFinancialProfileReady(true);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) setFinancialProfileReady(false);
        else throw cause;
      }
      setLoans(await api.myLoans(accessToken));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403 && cause.message === CLIENT_LINK_REQUIRED) {
        setNeedsLink(true);
        setClientId(null);
        setFinancialProfileReady(false);
        setLoans([]);
        setSelectedLoanId(null);
        return;
      }
      throw cause;
    }
  }

  async function handleExpiredSession(cause: unknown) {
    if (!(cause instanceof ApiError) || cause.status !== 401) return false;
    await signOut();
    setError("Tu sesión venció. Inicia sesión nuevamente.");
    return true;
  }

  useEffect(() => {
    let active = true;
    SecureStore.getItemAsync(TOKEN_KEY)
      .then(async (savedToken) => {
        if (!savedToken) return;
        try {
          await loadAccount(savedToken);
          if (active) setToken(savedToken);
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 401) {
            await SecureStore.deleteItemAsync(TOKEN_KEY);
            if (active) setError("Tu sesión venció. Inicia sesión nuevamente.");
          } else if (active) {
            setPendingSessionToken(savedToken);
            setError(cause instanceof Error ? cause.message : "No pudimos recuperar tu sesión. Intenta de nuevo.");
          }
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    let requestInFlight = false;
    const syncAccount = async () => {
      if (!active || requestInFlight) return;
      requestInFlight = true;
      try {
        const [latestNotifications, latestLoans] = await Promise.all([
          api.myNotifications(token),
          api.myLoans(token),
        ]);
        if (active) {
          setNotifications(latestNotifications);
          setLoans(latestLoans);
          setApiConnection("connected");
          setApiConnectionMessage("El API está activo y respondiendo.");
          setNotificationError("");
        }
      } catch (cause) {
        if (active) {
          if (cause instanceof ApiError && cause.status === 401) {
            await handleExpiredSession(cause);
            return;
          }
          if (!(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500) {
            setApiConnection("offline");
            setApiConnectionMessage(cause instanceof Error ? cause.message : "No pudimos contactar el API.");
          } else {
            setApiConnection("connected");
          }
          setNotificationError("No pudimos sincronizar tus créditos y avisos. Desliza hacia abajo para volver a intentarlo.");
        }
      } finally {
        requestInFlight = false;
      }
    };
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void syncAccount();
    });
    const interval = setInterval(() => {
      if (AppState.currentState === "active") void syncAccount();
    }, 60_000);
    return () => {
      active = false;
      subscription.remove();
      clearInterval(interval);
    };
  }, [token]);

  async function signIn() {
    if (!emailIsValid) {
      setError("Escribe un correo electrónico válido.");
      return;
    }
    if (password.length < 6) {
      setError("La contraseña debe tener al menos 6 caracteres.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.login(email.trim(), password);
      setApiConnection("connected");
      await loadAccount(result.access_token);
      await SecureStore.setItemAsync(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setPendingSessionToken(null);
      setPassword("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status !== 0) setApiConnection("connected");
      else if (cause instanceof ApiError) setApiConnection("offline");
      setError(cause instanceof Error ? cause.message : "No se pudo iniciar sesión.");
    } finally {
      setBusy(false);
    }
  }

  async function retrySavedSession() {
    if (!pendingSessionToken) return;
    setBusy(true);
    setError("");
    try {
      await loadAccount(pendingSessionToken);
      setToken(pendingSessionToken);
      setPendingSessionToken(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        await SecureStore.deleteItemAsync(TOKEN_KEY);
        setPendingSessionToken(null);
        setError("Tu sesión venció. Inicia sesión nuevamente.");
      } else {
        setError(cause instanceof Error ? cause.message : "No pudimos recuperar tu sesión. Intenta de nuevo.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function signUp() {
    if (!emailIsValid) {
      setError("Escribe un correo electrónico válido.");
      return;
    }
    if (password.length < 6) {
      setError("La contraseña debe tener al menos 6 caracteres.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.register(email.trim(), password);
      const result = await api.login(email.trim(), password);
      await loadAccount(result.access_token);
      await SecureStore.setItemAsync(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setPendingSessionToken(null);
      setPassword("");
      setConfirmPassword("");
      setAuthMode("login");
      Alert.alert(
        "Cuenta creada",
        "Tu acceso quedó creado. El equipo de CrediFresh debe verificar y vincular tu perfil antes de que puedas consultar o solicitar créditos.",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo crear la cuenta.");
    } finally {
      setBusy(false);
    }
  }

  async function requestPasswordReset() {
    if (!emailIsValid) { setError("Escribe el correo de tu cuenta."); return; }
    setBusy(true); setError("");
    try {
      const result = await api.requestPasswordReset(email.trim());
      Alert.alert("Revisa tu correo", result.mensaje);
      setAuthMode("login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo solicitar el enlace de recuperación.");
    } finally { setBusy(false); }
  }

  async function completePasswordReset() {
    if (!resetToken) { setError("El enlace no contiene un token válido. Solicita uno nuevo."); return; }
    if (password.length < 8) { setError("La nueva contraseña debe tener al menos 8 caracteres."); return; }
    if (password !== confirmPassword) { setError("Las contraseñas no coinciden."); return; }
    setBusy(true); setError("");
    try {
      const result = await api.resetPassword(resetToken, password);
      setResetToken(""); setPassword(""); setConfirmPassword(""); setAuthMode("login");
      Alert.alert("Contraseña actualizada", result.mensaje);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo actualizar la contraseña.");
    } finally { setBusy(false); }
  }

  async function saveContact() {
    if (!token || !/^\+?\d{7,20}$/.test(phone.trim()) || address.trim().length < 5) { setError("Escribe un teléfono válido (solo números, opcionalmente con +) y tu dirección completa."); return; }
    setBusy(true); setError("");
    try {
      await api.updateMyContact(token, { telefono: phone.trim(), direccion: address.trim() });
      setEditingContact(false);
      Alert.alert("Datos guardados", "Tu teléfono y dirección quedaron asociados a tu perfil de cliente.");
    } catch (cause) {
      if (await handleExpiredSession(cause)) return;
      setError(cause instanceof Error ? cause.message : "No se pudieron guardar tus datos de contacto.");
    } finally { setBusy(false); }
  }

  async function signOut() {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setLoans([]);
    setNotifications([]);
    setNotificationError("");
    setNotificationBusyId(null);
    setShowAllNotifications(false);
    setSelectedLoanId(null);
    setNeedsLink(false);
    setClientId(null);
    setFinancialProfileReady(false);
    setEditingFinancialProfile(false);
    setIncome("");
    setExpenses("");
    setObligations("");
    setIncomeType("");
    setEconomicActivity("");
    setPendingSessionToken(null);
    setPassword("");
    setConfirmPassword("");
    setShowPassword(false);
    setError("");
    setAuthMode("login");
  }

  function confirmSignOut() {
    Alert.alert("Cerrar sesión", "¿Quieres salir de tu cuenta de CrediFresh?", [
      { text: "Cancelar", style: "cancel" },
      { text: "Cerrar sesión", style: "destructive", onPress: () => void signOut() },
    ]);
  }

  async function refresh() {
    if (!token || busy) return;
    setBusy(true);
    setRefreshing(true);
    setError("");
    try {
      await loadAccount(token);
    } catch (cause) {
      if (!(await handleExpiredSession(cause))) setError(cause instanceof Error ? cause.message : "No se pudo actualizar.");
    } finally {
      setBusy(false);
      setRefreshing(false);
    }
  }

  async function openNotification(notification: Notification) {
    if (!token) return;
    if (!notification.leida) {
      setNotificationBusyId(notification.id);
      try {
        const updated = await api.markNotificationRead(token, notification.id);
        setNotifications((current) => current.map((item) => item.id === updated.id ? updated : item));
      } catch (cause) {
        if (await handleExpiredSession(cause)) return;
        setError(cause instanceof Error ? cause.message : "No se pudo actualizar el aviso.");
      } finally {
        setNotificationBusyId(null);
      }
    }
    if (notification.credito_id != null && loans.some((loan) => loan.credito.id === notification.credito_id)) {
      try {
        setLoans(await api.myLoans(token));
      } catch (cause) {
        if (await handleExpiredSession(cause)) return;
        setError(cause instanceof Error ? cause.message : "No se pudo actualizar el crédito relacionado.");
      }
      setSelectedLoanId(notification.credito_id);
    }
  }

  async function markAllNotificationsRead() {
    if (!token || markingAllNotifications || unreadNotificationCount === 0) return;
    setMarkingAllNotifications(true);
    try {
      const updated = await api.markAllNotificationsRead(token);
      const updatedIds = new Set(updated.map((notification) => notification.id));
      setNotifications((current) => current.map((notification) =>
        updatedIds.has(notification.id) ? { ...notification, leida: true } : notification,
      ));
    } catch (cause) {
      if (await handleExpiredSession(cause)) return;
      setError(cause instanceof Error ? cause.message : "No se pudieron marcar los avisos como leídos.");
    } finally {
      setMarkingAllNotifications(false);
    }
  }

  async function saveFinancialProfile() {
    if (!token || !clientId) return;
    const numericValues = [income, expenses, obligations].map(Number);
    if (numericValues.some((value) => !Number.isFinite(value)) || numericValues[0] <= 0 || numericValues[1] < 0 || numericValues[2] < 0) {
      setError("Revisa los ingresos, gastos y obligaciones. Los ingresos deben ser mayores que cero.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const profileData = {
        ingresos_mensuales: numericValues[0],
        gastos_mensuales: numericValues[1],
        otras_obligaciones: numericValues[2],
        tipo_ingresos: incomeType.trim(),
        actividad_economica: economicActivity.trim(),
      };
      if (financialProfileReady) {
        await api.updateFinancialProfile(token, clientId, profileData);
      } else {
        await api.saveFinancialProfile(token, clientId, profileData);
      }
      setFinancialProfileReady(true);
      setEditingFinancialProfile(false);
      Alert.alert(
        financialProfileReady ? "Perfil actualizado" : "Perfil guardado",
        financialProfileReady
          ? "Los cambios se tendrán en cuenta en futuras evaluaciones. No modifican decisiones de créditos anteriores."
          : "Ya puedes enviar una solicitud. El administrador asignará la tasa mensual antes de evaluarla.",
      );
    } catch (cause) {
      if (await handleExpiredSession(cause)) return;
      setError(cause instanceof Error ? cause.message : "No se pudo guardar tu perfil financiero.");
    } finally {
      setBusy(false);
    }
  }

  async function submitLoanRequest() {
    if (!token) return;
    if (!/^\+?\d{7,20}$/.test(phone.trim()) || address.trim().length < 5) {
      setError("Completa y guarda tu teléfono y dirección en Datos de contacto antes de solicitar el crédito.");
      setEditingContact(true);
      return;
    }
    const amount = Number(requestedAmount);
    const term = Number(requestedTerm);
    if (!Number.isInteger(amount) || amount < 500000 || amount > 1500000 || !Number.isInteger(term) || term < 1 || term > 12) {
      setError("El monto debe estar entre $500.000 y $1.500.000 COP y el plazo entre 1 y 12 meses.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.requestLoan(token, { monto: amount, plazo_meses: term });
      await loadAccount(token);
      Alert.alert("Solicitud recibida", `Registramos la solicitud #${result.credito.id}. El administrador asignará la tasa y luego evaluará tu perfil.`);
    } catch (cause) {
      if (await handleExpiredSession(cause)) return;
      setError(cause instanceof Error ? cause.message : "No se pudo enviar la solicitud.");
    } finally {
      setBusy(false);
    }
  }

  function confirmAcceptance(loan: Loan) {
    const evaluation = loan.evaluacion;
    const total = loan.total_estimado;
    if (!evaluation || total == null || !token) {
      setError("No encontramos las condiciones completas de esta oferta. Actualiza los datos e inténtalo de nuevo.");
      return;
    }
    Alert.alert(
      "Aceptar condiciones",
      `Monto: ${currency(loan.credito.monto)}\nPlazo: ${loan.credito.plazo_meses} meses\nCuota estimada: ${currency(evaluation.cuota_mensual)}\nTotal estimado: ${currency(total)}\n\nAceptar no significa que el dinero ya haya sido transferido.`,
      [
        { text: "Revisar después", style: "cancel" },
        {
          text: "Confirmar aceptación",
          onPress: () => void accept(loan, Number(total)),
        },
      ],
    );
  }

  async function accept(loan: Loan, total: number) {
    if (!token || !loan.evaluacion) return;
    setBusy(true);
    setError("");
    try {
      await api.acceptOffer(token, loan.credito.id, {
        acepta: true,
        monto: Number(loan.credito.monto),
        plazo_meses: loan.credito.plazo_meses,
        tasa_interes: Number(loan.credito.tasa_interes),
        cuota_mensual: Number(loan.evaluacion.cuota_mensual),
        total_estimado: total,
      });
      await loadAccount(token);
      Alert.alert("Aceptación registrada", "Tu oferta quedó aceptada. El desembolso todavía no está habilitado.");
    } catch (cause) {
      if (await handleExpiredSession(cause)) return;
      setError(cause instanceof Error ? cause.message : "No se pudo registrar la aceptación.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" color={colors.teal} /></View>;
  }

  if (!token || !user) {
    return (
      <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <StatusBar style="dark" />
        <ScrollView contentContainerStyle={styles.loginWrap} keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}>
          <View style={styles.brandLockup}>
            <Image source={require("./assets/icon.png")} style={styles.brandMark} accessibilityLabel="Logo de CrediFresh" />
            <View><Text style={styles.brandName}><Text style={styles.brandNameNavy}>Credi</Text><Text style={styles.brandNameGreen}>Fresh</Text></Text><Text style={styles.brandTagline}>Impulsando tus oportunidades</Text></View>
          </View>
          <Text style={styles.eyebrow}>CREDIFRESH · CLIENTES</Text>
          <Text style={styles.title}>{authMode === "login" ? <>Tu crédito,{"\n"}más cerca.</> : authMode === "register" ? "Crea tu acceso" : authMode === "forgot" ? "Recupera tu acceso" : "Nueva contraseña"}</Text>
          <Text style={styles.subtitle}>{authMode === "login" ? "Consulta tus solicitudes y revisa tus ofertas desde tu iPhone." : authMode === "register" ? "Regístrate con tu correo. El equipo de CrediFresh verificará y vinculará tu perfil antes de habilitar las solicitudes." : authMode === "forgot" ? "Te enviaremos un enlace seguro para que puedas crear una nueva contraseña." : "Elige una contraseña nueva para volver a ingresar a CrediFresh."}</Text>
          <View style={styles.card}>
            {authMode !== "reset" ? <><Text style={styles.fieldLabel}>Correo electrónico</Text>
            <TextInput
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              placeholder="nombre@correo.com"
              placeholderTextColor="#91a19d"
              value={email}
              onChangeText={(value) => { setEmail(value); setError(""); }}
              style={styles.input}
              ref={emailRef}
              textContentType="emailAddress"
              returnKeyType="next"
              onSubmitEditing={() => authMode === "forgot" ? void requestPasswordReset() : passwordRef.current?.focus()}
              accessibilityLabel="Correo electrónico"
            />
            {email.length > 0 && !emailIsValid ? <Text style={styles.validationHint}>Ingresa un correo con formato nombre@correo.com.</Text> : null}</> : <Text style={styles.bodyText}>El enlace es temporal y solo puede utilizarse una vez.</Text>}
            {authMode !== "forgot" ? <><View style={[styles.passwordLabelRow, styles.secondLabel]}>
              <Text style={styles.fieldLabel}>{authMode === "reset" ? "Nueva contraseña" : "Contraseña"}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                onPress={() => setShowPassword((visible) => !visible)}
                hitSlop={8}
              >
                <Text style={styles.passwordToggle}>{showPassword ? "Ocultar" : "Mostrar"}</Text>
              </Pressable>
            </View>
            <TextInput
              autoCapitalize="none"
              autoComplete={authMode === "reset" ? "new-password" : "password"}
              textContentType={authMode === "reset" ? "newPassword" : "password"}
              secureTextEntry={!showPassword}
              placeholder={authMode === "reset" ? "Mínimo 8 caracteres" : "Tu contraseña"}
              placeholderTextColor="#91a19d"
              value={password}
              onChangeText={(value) => { setPassword(value); setError(""); }}
              style={styles.input}
              ref={passwordRef}
              returnKeyType={authMode === "login" ? "go" : "next"}
              onSubmitEditing={() => authMode === "login" ? void signIn() : authMode === "reset" ? confirmPasswordRef.current?.focus() : void signUp()}
              accessibilityLabel="Contraseña"
            />
            {authMode === "register" || authMode === "reset" ? <>
              <View style={[styles.passwordLabelRow, styles.secondLabel]}>
                <Text style={styles.fieldLabel}>Confirmar contraseña</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                  onPress={() => setShowPassword((visible) => !visible)}
                  hitSlop={8}
                >
                  <Text style={styles.passwordToggle}>{showPassword ? "Ocultar" : "Mostrar"}</Text>
                </Pressable>
              </View>
              <TextInput
                autoCapitalize="none"
                autoComplete="new-password"
                textContentType="newPassword"
                secureTextEntry={!showPassword}
                placeholder="Repite tu contraseña"
                placeholderTextColor="#91a19d"
                value={confirmPassword}
                onChangeText={(value) => { setConfirmPassword(value); setError(""); }}
                style={styles.input}
                accessibilityLabel="Confirmar contraseña"
                returnKeyType="done"
                onSubmitEditing={() => authMode === "reset" ? void completePasswordReset() : void signUp()}
                ref={confirmPasswordRef}
              />
              {confirmPassword.length > 0 && password !== confirmPassword ? <Text style={styles.validationHint}>Las contraseñas no coinciden.</Text> : null}
            </> : null}</> : null}
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <PrimaryButton
              title={busy ? "Un momento…" : authMode === "login" ? "Iniciar sesión" : authMode === "register" ? "Crear cuenta" : authMode === "forgot" ? "Enviar enlace" : "Guardar contraseña nueva"}
              onPress={() => void (authMode === "login" ? signIn() : authMode === "register" ? signUp() : authMode === "forgot" ? requestPasswordReset() : completePasswordReset())}
              disabled={busy || (authMode !== "reset" && !emailIsValid) || ((authMode === "login" || authMode === "register" || authMode === "reset") && password.length < (authMode === "reset" ? 8 : 6)) || ((authMode === "register" || authMode === "reset") && (confirmPassword.length < (authMode === "reset" ? 8 : 6) || password !== confirmPassword))}
            />
            {authMode === "login" ? <Pressable onPress={() => { setAuthMode("forgot"); setError(""); }} style={styles.authSwitch}><Text style={styles.authSwitchText}>¿Olvidaste tu contraseña?</Text></Pressable> : null}
            {authMode === "reset" ? <Pressable onPress={() => { setAuthMode("forgot"); setResetToken(""); setError(""); }} style={styles.authSwitch}><Text style={styles.authSwitchText}>Solicitar un enlace nuevo</Text></Pressable> : null}
            {pendingSessionToken ? <Pressable accessibilityRole="button" onPress={() => void retrySavedSession()} disabled={busy} style={styles.authSwitch}><Text style={styles.authSwitchText}>{busy ? "Conectando…" : "Reintentar conexión con mi sesión"}</Text></Pressable> : null}
          </View>
          {authMode === "login" || authMode === "register" ? <Pressable onPress={() => { setAuthMode(authMode === "login" ? "register" : "login"); setError(""); }} style={styles.authSwitch}>
            <Text style={styles.authSwitchText}>{authMode === "login" ? "¿No tienes acceso? Crear cuenta" : "¿Ya tienes una cuenta? Iniciar sesión"}</Text>
          </Pressable> : <Pressable onPress={() => { setAuthMode("login"); setResetToken(""); setError(""); }} style={styles.authSwitch}><Text style={styles.authSwitchText}>Volver a iniciar sesión</Text></Pressable>}
          <Text style={styles.hint}>Para entrar necesitas una cuenta cliente vinculada a tu perfil de CrediFresh.</Text>
          {apiHost.includes("localhost") ? <Text style={styles.warning}>Para probar en iPhone, configura la dirección local de tu computador en EXPO_PUBLIC_API_BASE_URL.</Text> : null}
          <View style={styles.connectionPanel}>
            <View style={styles.connectionHeading}>
              <View style={[styles.connectionDot, apiConnection === "connected" && styles.connectionDotOnline, apiConnection === "offline" && styles.connectionDotOffline]} />
              <Text style={styles.connectionTitle}>{apiConnection === "checking" ? "Comprobando servicio…" : apiConnection === "connected" ? "Servicio conectado" : apiConnection === "offline" ? "Sin conexión con el API" : "Estado del servicio sin comprobar"}</Text>
            </View>
            {apiConnectionMessage ? <Text style={apiConnection === "offline" ? styles.connectionError : styles.connectionMessage}>{apiConnectionMessage}</Text> : null}
            <Text style={styles.connectionHost}>Servidor: {apiHost}</Text>
            <Pressable accessibilityRole="button" onPress={() => void checkApiConnection()} disabled={checkingConnection} style={styles.connectionButton}>
              <Text style={styles.connectionButtonText}>{checkingConnection ? "Comprobando…" : "Comprobar conexión"}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <StatusBar style="dark" />
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void refresh()} tintColor={colors.teal} colors={[colors.teal]} />}
      >
        <View style={styles.topLine}>
          <View><Text style={styles.eyebrow}>CREDIFRESH</Text><Text style={styles.topTitle}>{selectedLoan ? `Crédito #${selectedLoan.credito.id}` : "Mi espacio"}</Text></View>
          {selectedLoan ? <Pressable onPress={() => setSelectedLoanId(null)}><Text style={styles.textButton}>Volver</Text></Pressable> : <Pressable onPress={confirmSignOut}><Text style={styles.textButton}>Salir</Text></Pressable>}
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Comprobar conexión con el servicio" onPress={() => void checkApiConnection()} disabled={checkingConnection} style={styles.connectionInline}>
          <View style={[styles.connectionDot, apiConnection === "connected" && styles.connectionDotOnline, apiConnection === "offline" && styles.connectionDotOffline]} />
          <Text style={styles.connectionInlineText}>{checkingConnection ? "Comprobando conexión…" : apiConnection === "connected" ? "API conectada · tocar para comprobar" : apiConnection === "offline" ? "API sin conexión · tocar para reintentar" : "Comprobar conexión con CrediFresh"}</Text>
        </Pressable>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {needsLink ? (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Verificación pendiente</Text>
            <Text style={styles.bodyText}>Tu cuenta está activa, pero todavía no está vinculada a un perfil de cliente. El equipo de CrediFresh debe verificar tus datos y vincular el perfil desde el portal antes de habilitar tus créditos.</Text>
            <PrimaryButton title={busy ? "Consultando…" : "Ya me vincularon · Actualizar"} onPress={() => void refresh()} disabled={busy} />
          </View>
        ) : selectedLoan ? (
          <LoanDetail loan={selectedLoan} busy={busy} onAccept={() => confirmAcceptance(selectedLoan)} />
        ) : (
          <>
            <View style={styles.welcome}>
              <Text style={styles.greeting}>Hola,</Text>
              <Text style={styles.name}>{user.email}</Text>
              <Text style={styles.subtitle}>Aquí puedes seguir el estado de tus solicitudes.</Text>
            </View>
            <View style={styles.summaryCard}>
              <Text style={styles.summaryLabel}>Mis solicitudes</Text>
              <Text style={styles.summaryNumber}>{loans.length}</Text>
              <Text style={styles.summaryFoot}>Créditos asociados a tu cuenta</Text>
            </View>
            <View style={styles.card}>
              <View style={styles.loanRow}><Text style={styles.sectionTitle}>Datos de contacto</Text>{!editingContact ? <Pressable onPress={() => setEditingContact(true)} accessibilityRole="button"><Text style={styles.textButton}>Editar</Text></Pressable> : null}</View>
              <Text style={styles.bodyText}>Tu teléfono y dirección se guardan una vez en tu perfil y quedan asociados a tus solicitudes.</Text>
              {editingContact ? <>
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Teléfono</Text>
                <TextInput value={phone} onChangeText={setPhone} keyboardType="phone-pad" style={styles.input} placeholder="Ej. 3001234567" placeholderTextColor="#91a19d" />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Dirección de residencia</Text>
                <TextInput value={address} onChangeText={setAddress} style={styles.input} placeholder="Calle, carrera, número y ciudad" placeholderTextColor="#91a19d" autoComplete="street-address" />
                <PrimaryButton title={busy ? "Guardando…" : "Guardar datos de contacto"} onPress={() => void saveContact()} disabled={busy || !/^\+?\d{7,20}$/.test(phone.trim()) || address.trim().length < 5} />
              </> : <View style={{ marginTop: 12 }}><Text style={styles.bodyText}>Teléfono: {phone || "Pendiente"}</Text><Text style={[styles.bodyText, { marginTop: 5 }]}>Dirección: {address || "Pendiente"}</Text></View>}
            </View>
            <View style={styles.notificationsSection}>
              <View style={styles.notificationHeader}>
                <Text style={styles.sectionTitle}>Avisos</Text>
                <View style={styles.notificationHeaderActions}>
                  {unreadNotificationCount > 0 ? <Text style={styles.unreadBadge}>{unreadNotificationCount} sin leer</Text> : null}
                  {unreadNotificationCount > 0 ? (
                    <Pressable onPress={() => void markAllNotificationsRead()} disabled={markingAllNotifications || notificationBusyId != null} accessibilityRole="button">
                      <Text style={[styles.markAllRead, (markingAllNotifications || notificationBusyId != null) && styles.buttonDim]}>{markingAllNotifications ? "Guardando…" : "Leer todos"}</Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
              {notificationError ? <Text style={styles.validationHint}>{notificationError}</Text> : null}
              {notifications.length === 0 ? (
                <View style={styles.notificationEmpty}><Text style={styles.bodyText}>Te avisaremos aquí cuando cambie el estado de tus solicitudes.</Text></View>
              ) : visibleNotifications.map((notification) => (
                <Pressable
                  key={notification.id}
                  onPress={() => void openNotification(notification)}
                  accessibilityRole="button"
                  accessibilityLabel={`${notification.leida ? "Aviso leído" : "Aviso nuevo"}: ${notification.titulo}`}
                  disabled={markingAllNotifications}
                  style={[styles.notificationCard, !notification.leida && styles.notificationUnread]}
                >
                  <View style={styles.loanRow}>
                    <Text style={styles.notificationTitle}>{notification.titulo}</Text>
                    {!notification.leida ? <Text style={styles.newLabel}>Nuevo</Text> : null}
                  </View>
                  <Text style={styles.notificationMessage}>{notification.mensaje}</Text>
                  <View style={styles.loanRow}>
                    <Text style={styles.notificationDate}>{dateLabel(notification.fecha_creacion, true)}</Text>
                    {notification.credito_id != null && loans.some((loan) => loan.credito.id === notification.credito_id)
                      ? <Text style={styles.notificationAction}>{notificationBusyId === notification.id ? "Abriendo…" : `Ver crédito #${notification.credito_id} →`}</Text>
                      : null}
                  </View>
                </Pressable>
              ))}
              {notifications.length > 5 ? (
                <Pressable onPress={() => setShowAllNotifications((showing) => !showing)} style={styles.showNotificationsButton}>
                  <Text style={styles.textButton}>{showAllNotifications ? "Mostrar menos" : `Ver todos (${notifications.length})`}</Text>
                </Pressable>
              ) : null}
            </View>
            {!financialProfileReady || editingFinancialProfile ? (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>{financialProfileReady ? "Actualiza tu perfil financiero" : "Completa tu perfil financiero"}</Text>
                <Text style={styles.bodyText}>{financialProfileReady ? "Revisa tus datos. Los cambios aplican a futuras evaluaciones y no cambian decisiones anteriores." : "Estos datos se usan para evaluar tu capacidad de pago. Solo el equipo de CrediFresh puede verlos."}</Text>
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Ingresos mensuales (COP)</Text>
                <TextInput value={income} onChangeText={setIncome} keyboardType="numeric" style={styles.input} placeholder="Ej. 2500000" placeholderTextColor="#91a19d" />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Gastos mensuales (COP)</Text>
                <TextInput value={expenses} onChangeText={setExpenses} keyboardType="numeric" style={styles.input} placeholder="Ej. 1200000" placeholderTextColor="#91a19d" />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Otras obligaciones mensuales (COP)</Text>
                <TextInput value={obligations} onChangeText={setObligations} keyboardType="numeric" style={styles.input} placeholder="Ej. 200000" placeholderTextColor="#91a19d" />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Tipo de ingresos</Text>
                <TextInput value={incomeType} onChangeText={setIncomeType} style={styles.input} placeholder="Ej. salario, independiente" placeholderTextColor="#91a19d" />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Actividad económica</Text>
                <TextInput value={economicActivity} onChangeText={setEconomicActivity} style={styles.input} placeholder="Ej. comercio" placeholderTextColor="#91a19d" />
                <PrimaryButton title={busy ? "Guardando…" : financialProfileReady ? "Actualizar perfil financiero" : "Guardar perfil financiero"} onPress={() => void saveFinancialProfile()} disabled={busy || incomeType.trim().length < 2 || economicActivity.trim().length < 2} />
                {financialProfileReady ? <Pressable onPress={() => { setEditingFinancialProfile(false); setError(""); }} disabled={busy} style={styles.authSwitch}><Text style={styles.authSwitchText}>Cancelar</Text></Pressable> : null}
              </View>
            ) : (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>Solicitar un crédito</Text>
                <Text style={styles.bodyText}>Elige monto y plazo. El administrador asignará la tasa mensual antes de evaluar la solicitud.</Text>
                <Pressable onPress={() => { setEditingFinancialProfile(true); setError(""); }} style={styles.profileEditLink} accessibilityRole="button"><Text style={styles.textButton}>Revisar perfil financiero</Text></Pressable>
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Monto (COP)</Text>
                <TextInput value={requestedAmount} onChangeText={setRequestedAmount} keyboardType="numeric" style={styles.input} />
                <Text style={[styles.fieldLabel, styles.secondLabel]}>Plazo en meses (1 a 12)</Text>
                <TextInput value={requestedTerm} onChangeText={setRequestedTerm} keyboardType="numeric" style={styles.input} />
                <PrimaryButton title={busy ? "Enviando…" : "Enviar solicitud"} onPress={() => void submitLoanRequest()} disabled={busy || !/^\+?\d{7,20}$/.test(phone.trim()) || address.trim().length < 5} />
              </View>
            )}
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Mis créditos</Text>
              <Pressable onPress={() => void refresh()} disabled={busy}><Text style={styles.textButton}>{busy ? "Actualizando…" : "Actualizar"}</Text></Pressable>
            </View>
            {loans.length === 0 ? (
              <View style={styles.card}><Text style={styles.emptyTitle}>Aún no tienes solicitudes</Text><Text style={styles.bodyText}>Cuando se registre una solicitud vinculada a tu cuenta, aparecerá aquí.</Text></View>
            ) : loans.map((loan) => (
              <Pressable key={loan.credito.id} style={styles.loanCard} onPress={() => setSelectedLoanId(loan.credito.id)}>
                <View style={styles.loanRow}><Text style={styles.loanId}>Crédito #{loan.credito.id}</Text><StatusPill status={loan.credito.estado} /></View>
                <Text style={styles.loanAmount}>{currency(loan.credito.monto)}</Text>
                <Text style={styles.bodyText}>{loan.credito.plazo_meses} meses · {rateLabel(loan.credito.tasa_interes)}</Text>
                {loan.cuotas.length > 0 ? (
                  <View style={styles.loanRepaymentSummary}>
                    <InfoRow label="Saldo pendiente" value={currency(loanBalance(loan))} />
                    {nextInstallment(loan) ? <InfoRow label="Próximo vencimiento" value={dateLabel(nextInstallment(loan)!.fecha_vencimiento)} /> : null}
                    {overdueBalance(loan) > 0 ? <InfoRow label="Saldo vencido" value={currency(overdueBalance(loan))} /> : null}
                  </View>
                ) : null}
                <Text style={styles.link}>Ver detalle →</Text>
              </Pressable>
            ))}
            <Text style={styles.footerNote}>El desembolso y los pagos siguen deshabilitados mientras se configura la integración bancaria.</Text>
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function LoanDetail({ loan, busy, onAccept }: { loan: Loan; busy: boolean; onAccept: () => void }) {
  const approved = loan.credito.estado === "APROBADO";
  const accepted = Boolean(loan.aceptacion);
  return (
    <View>
      <View style={styles.detailHero}>
        <StatusPill status={loan.credito.estado} />
        <Text style={styles.detailAmount}>{currency(loan.credito.monto)}</Text>
        <Text style={styles.bodyText}>Solicitud de crédito #{loan.credito.id}</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Condiciones</Text>
        <InfoRow label="Monto solicitado" value={currency(loan.credito.monto)} />
        <InfoRow label="Plazo" value={`${loan.credito.plazo_meses} meses`} />
        <InfoRow label="Tasa mensual" value={rateLabel(loan.credito.tasa_interes)} />
        {loan.evaluacion?.cuota_mensual != null ? <InfoRow label="Cuota estimada" value={currency(loan.evaluacion.cuota_mensual)} /> : null}
        {loan.total_estimado != null ? <InfoRow label="Total estimado" value={currency(loan.total_estimado)} /> : null}
      </View>
      {accepted ? (
        <View style={styles.notice}><Text style={styles.noticeTitle}>Condiciones aceptadas</Text><Text style={styles.bodyText}>El crédito sigue pendiente de desembolso. Aceptar las condiciones no significa que el dinero haya sido transferido.</Text></View>
      ) : loan.credito.estado === "RECHAZADO" ? (
        <View style={styles.notice}><Text style={styles.noticeTitle}>Solicitud rechazada</Text><Text style={styles.bodyText}>{loan.evaluacion?.motivos?.trim() || "Esta solicitud no cumplió los criterios actuales de evaluación."}</Text></View>
      ) : approved ? (
        <View style={styles.card}><Text style={styles.sectionTitle}>Tu oferta está lista</Text><Text style={styles.bodyText}>Lee las condiciones y confirma si deseas aceptarlas.</Text><PrimaryButton title="Revisar y aceptar oferta" onPress={onAccept} disabled={busy || !loan.evaluacion || loan.total_estimado == null} /></View>
      ) : (
        <View style={styles.card}><Text style={styles.bodyText}>Te notificaremos cuando cambie el estado de tu solicitud.</Text></View>
      )}
      {loan.cuotas.length > 0 ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Plan de cuotas</Text>
          <InfoRow label="Saldo pendiente" value={currency(loanBalance(loan))} />
          {nextInstallment(loan) ? <InfoRow label="Próximo vencimiento" value={dateLabel(nextInstallment(loan)!.fecha_vencimiento)} /> : <Text style={styles.bodyText}>No tienes cuotas pendientes.</Text>}
          {overdueInstallmentCount(loan) > 0 ? <InfoRow label={`Cuotas vencidas (${overdueInstallmentCount(loan)})`} value={currency(overdueBalance(loan))} /> : null}
          {loan.cuotas.map((installment) => (
            <View key={installment.numero_cuota} style={[styles.installmentItem, installmentBalance(installment) > 0 && daysUntilDue(installment.fecha_vencimiento) != null && daysUntilDue(installment.fecha_vencimiento)! < 0 && styles.installmentOverdue]}>
              <View style={styles.loanRow}>
                <Text style={styles.loanId}>Cuota {installment.numero_cuota}</Text>
                <Text style={[styles.installmentState, installmentBalance(installment) <= 0 && styles.installmentPaid, installmentBalance(installment) > 0 && daysUntilDue(installment.fecha_vencimiento) != null && daysUntilDue(installment.fecha_vencimiento)! < 0 && styles.installmentOverdueText]}>{installmentStatusLabel(installment)}</Text>
              </View>
              <Text style={styles.installmentDate}>Vence {dateLabel(installment.fecha_vencimiento)}</Text>
              <InfoRow label="Valor" value={currency(installment.monto_cuota)} />
              <InfoRow label="Pagado" value={currency(installment.monto_pagado)} />
              <InfoRow label="Saldo de esta cuota" value={currency(installmentBalance(installment))} />
            </View>
          ))}
        </View>
      ) : null}
      {loan.pagos.length > 0 ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Historial de pagos</Text>
          {loan.pagos.map((payment, index) => (
            <InfoRow key={`${payment.fecha_pago}-${index}`} label={dateLabel(payment.fecha_pago, true)} value={currency(payment.monto_pagado)} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <View style={styles.infoRow}><Text style={styles.bodyText}>{label}</Text><Text style={styles.infoValue}>{value}</Text></View>;
}

function StatusPill({ status }: { status: string }) {
  const approved = status === "APROBADO";
  const rejected = status === "RECHAZADO";
  return <View style={[styles.pill, approved && styles.pillApproved, rejected && styles.pillRejected]}><Text style={[styles.pillText, rejected && styles.pillRejectedText]}>{statusLabel(status)}</Text></View>;
}

function PrimaryButton({ title, onPress, disabled }: { title: string; onPress: () => void; disabled?: boolean }) {
  return <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled} style={({ pressed }) => [styles.primaryButton, (disabled || pressed) && styles.buttonDim]}><Text style={styles.primaryButtonText}>{title}</Text></Pressable>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.canvas },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.canvas },
  loginWrap: { flexGrow: 1, justifyContent: "center", padding: 24, paddingTop: 48, paddingBottom: 40 },
  connectionPanel: { marginTop: 18, padding: 14, borderWidth: 1, borderColor: colors.border, borderRadius: 14, backgroundColor: colors.white },
  connectionHeading: { flexDirection: "row", alignItems: "center", gap: 8 },
  connectionDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: "#a9b4b1" },
  connectionDotOnline: { backgroundColor: colors.green },
  connectionDotOffline: { backgroundColor: "#c54c4c" },
  connectionTitle: { color: colors.ink, fontSize: 13, fontWeight: "800" },
  connectionMessage: { color: colors.muted, fontSize: 12, lineHeight: 18, marginTop: 7 },
  connectionError: { color: "#a73535", fontSize: 12, lineHeight: 18, marginTop: 7 },
  connectionHost: { color: colors.muted, fontSize: 10, lineHeight: 15, marginTop: 6 },
  connectionButton: { alignSelf: "flex-start", marginTop: 5, paddingVertical: 5 },
  connectionButtonText: { color: colors.teal, fontSize: 12, fontWeight: "800" },
  connectionInline: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 7, marginTop: -13, marginBottom: 14, paddingVertical: 5 },
  connectionInlineText: { color: colors.muted, fontSize: 11, fontWeight: "700" },
  brandLockup: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 28 },
  brandMark: { width: 54, height: 54, borderRadius: 15 },
  brandName: { fontSize: 21, fontWeight: "800", letterSpacing: -0.7 },
  brandNameNavy: { color: colors.deep },
  brandNameGreen: { color: colors.green },
  brandTagline: { color: colors.muted, fontSize: 10, marginTop: 1 },
  eyebrow: { color: colors.teal, fontSize: 12, fontWeight: "800", letterSpacing: 1.5 },
  title: { marginTop: 12, color: colors.ink, fontSize: 37, lineHeight: 43, fontWeight: "800", letterSpacing: -1 },
  subtitle: { marginTop: 8, color: colors.muted, fontSize: 15, lineHeight: 22 },
  card: { marginTop: 24, padding: 20, borderWidth: 1, borderColor: colors.border, borderRadius: 20, backgroundColor: colors.white },
  fieldLabel: { color: colors.ink, fontSize: 13, fontWeight: "700", marginBottom: 8 },
  secondLabel: { marginTop: 16 },
  passwordLabelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  passwordToggle: { color: colors.teal, fontSize: 13, fontWeight: "700", paddingVertical: 4 },
  input: { height: 50, paddingHorizontal: 14, borderWidth: 1, borderColor: colors.border, borderRadius: 12, color: colors.ink, backgroundColor: "#fbfdfc", fontSize: 15 },
  primaryButton: { minHeight: 52, paddingHorizontal: 16, marginTop: 20, justifyContent: "center", alignItems: "center", borderRadius: 13, backgroundColor: colors.teal },
  primaryButtonText: { color: colors.white, fontSize: 15, fontWeight: "800" },
  buttonDim: { opacity: 0.55 },
  profileEditLink: { alignSelf: "flex-start", marginTop: 10 },
  authSwitch: { alignItems: "center", paddingVertical: 14 },
  authSwitchText: { color: colors.teal, fontSize: 14, fontWeight: "700", textAlign: "center" },
  error: { color: "#a73535", fontSize: 14, lineHeight: 20, marginTop: 14 },
  validationHint: { color: "#a73535", fontSize: 12, lineHeight: 17, marginTop: 6 },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 19, textAlign: "center", marginTop: 22 },
  warning: { color: colors.amber, fontSize: 12, lineHeight: 17, textAlign: "center", marginTop: 12 },
  content: { paddingHorizontal: 20, paddingTop: 62, paddingBottom: 36 },
  topLine: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 24 },
  topTitle: { color: colors.ink, fontSize: 26, fontWeight: "800", marginTop: 4 },
  textButton: { color: colors.teal, fontWeight: "800", fontSize: 14, paddingVertical: 8, paddingHorizontal: 4 },
  welcome: { marginBottom: 20 },
  greeting: { color: colors.muted, fontSize: 15 },
  name: { color: colors.ink, fontSize: 18, fontWeight: "800", marginTop: 2 },
  summaryCard: { padding: 20, borderRadius: 20, backgroundColor: colors.deep },
  summaryLabel: { color: "#c5e4dc", fontSize: 13, fontWeight: "700" },
  summaryNumber: { color: colors.white, fontSize: 36, fontWeight: "900", marginTop: 3 },
  summaryFoot: { color: "#c5e4dc", fontSize: 12, marginTop: 2 },
  notificationsSection: { marginTop: 24 },
  notificationHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 2 },
  notificationHeaderActions: { flexDirection: "row", alignItems: "center", gap: 9 },
  unreadBadge: { color: colors.teal, fontSize: 12, fontWeight: "800", backgroundColor: colors.mint, borderRadius: 20, paddingHorizontal: 10, paddingVertical: 6 },
  markAllRead: { color: colors.teal, fontSize: 12, fontWeight: "800", paddingVertical: 8 },
  notificationEmpty: { marginTop: 8, padding: 16, borderWidth: 1, borderColor: colors.border, borderRadius: 16, backgroundColor: colors.white },
  notificationCard: { marginTop: 8, padding: 16, borderWidth: 1, borderColor: colors.border, borderRadius: 16, backgroundColor: colors.white },
  notificationUnread: { borderColor: "#a9d8c9", backgroundColor: "#f7fcfa" },
  notificationTitle: { color: colors.ink, fontSize: 14, fontWeight: "800", flexShrink: 1, marginRight: 8 },
  notificationMessage: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 8 },
  notificationDate: { color: colors.muted, fontSize: 11, marginTop: 12, flexShrink: 1 },
  notificationAction: { color: colors.teal, fontSize: 11, fontWeight: "800", marginTop: 12, marginLeft: 8 },
  newLabel: { color: colors.teal, fontSize: 10, fontWeight: "900", textTransform: "uppercase" },
  showNotificationsButton: { alignItems: "center", marginTop: 4 },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 30, marginBottom: 4 },
  sectionTitle: { color: colors.ink, fontSize: 18, fontWeight: "800", marginBottom: 12 },
  emptyTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 8 },
  bodyText: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  loanCard: { marginTop: 12, padding: 18, borderWidth: 1, borderColor: colors.border, borderRadius: 18, backgroundColor: colors.white },
  loanRepaymentSummary: { marginTop: 8 },
  loanRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  loanId: { color: colors.ink, fontWeight: "800", fontSize: 14 },
  loanAmount: { color: colors.ink, fontSize: 25, fontWeight: "900", marginTop: 14, marginBottom: 4 },
  pill: { alignSelf: "flex-start", backgroundColor: "#f2f0e9", borderRadius: 30, paddingHorizontal: 11, paddingVertical: 7 },
  pillApproved: { backgroundColor: colors.mint },
  pillRejected: { backgroundColor: "#fdeeed" },
  pillText: { color: colors.amber, fontSize: 11, fontWeight: "800" },
  pillRejectedText: { color: "#a73535" },
  link: { color: colors.teal, fontSize: 13, fontWeight: "800", marginTop: 15 },
  footerNote: { color: colors.muted, fontSize: 12, lineHeight: 18, textAlign: "center", marginTop: 25, paddingHorizontal: 8 },
  detailHero: { padding: 20, borderRadius: 20, backgroundColor: colors.mint, alignItems: "flex-start" },
  detailAmount: { color: colors.ink, fontSize: 31, fontWeight: "900", marginTop: 18, marginBottom: 4 },
  infoRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 10, paddingVertical: 12, borderTopWidth: 1, borderTopColor: colors.border },
  infoValue: { color: colors.ink, fontSize: 14, fontWeight: "700", textAlign: "right", flexShrink: 1 },
  installmentItem: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 12, marginTop: 2 },
  installmentOverdue: { borderTopColor: "#e6b9b5" },
  installmentState: { color: colors.teal, fontSize: 12, fontWeight: "800" },
  installmentPaid: { color: "#3f7b5d" },
  installmentOverdueText: { color: "#a73535" },
  installmentDate: { color: colors.muted, fontSize: 13, marginTop: 5 },
  notice: { marginTop: 18, padding: 18, borderWidth: 1, borderColor: "#e8d7b8", borderRadius: 18, backgroundColor: "#fff8e9" },
  noticeTitle: { color: colors.amber, fontWeight: "800", fontSize: 16, marginBottom: 6 },
});
