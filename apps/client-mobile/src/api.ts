const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type User = {
  id: number;
  email: string;
  rol: string;
  activo: boolean;
};

export type Notification = {
  id: number;
  usuario_id: number;
  credito_id: number | null;
  titulo: string;
  mensaje: string;
  leida: boolean;
  fecha_creacion: string;
};

export type Loan = {
  credito: {
    id: number;
    monto: number | string;
    plazo_meses: number;
    tasa_interes: number | string;
    estado: string;
  };
  evaluacion: null | {
    decision: string;
    tipo: string;
    cuota_mensual: number | string | null;
    motivos: string;
  };
  total_estimado: number | string | null;
  aceptacion: null | {
    fecha_aceptacion: string;
    monto: number | string;
    plazo_meses: number;
    tasa_interes: number | string;
    cuota_mensual: number | string;
    total_estimado: number | string;
  };
  cuotas: Array<{
    numero_cuota: number;
    fecha_vencimiento: string;
    monto_cuota: number | string;
    monto_pagado: number | string;
    estado: string;
  }>;
  pagos: Array<{
    fecha_pago: string;
    monto_pagado: number | string;
  }>;
};

export type FinancialProfileInput = {
  ingresos_mensuales: number;
  gastos_mensuales: number;
  otras_obligaciones: number;
  tipo_ingresos: string;
  actividad_economica: string;
};

export type FinancialProfile = FinancialProfileInput & {
  id: number;
  cliente_id: number;
};

type LoginResponse = { access_token: string; token_type: string };
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

const REQUEST_TIMEOUT_MS = 15_000;
const CONNECTION_ERROR = "No pudimos conectar con CrediFresh. Confirma que el computador y el iPhone estén en la misma Wi‑Fi y que el API esté encendido.";
const TIMEOUT_ERROR = "El servidor tardó demasiado en responder. Revisa que el API esté encendido y vuelve a intentarlo. Si estabas enviando una solicitud o aceptando una oferta, toca Actualizar antes de repetir.";

type AcceptOffer = {
  acepta: true;
  monto: number;
  plazo_meses: number;
  tasa_interes: number;
  cuota_mensual: number;
  total_estimado: number;
};

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch (cause) {
    const timedOut = cause instanceof Error && cause.name === "AbortError";
    throw new ApiError(timedOut ? TIMEOUT_ERROR : CONNECTION_ERROR, 0);
  } finally {
    clearTimeout(timeout);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status >= 500) {
      throw new ApiError("El servicio está temporalmente indisponible. Intenta de nuevo en unos minutos.", response.status);
    }
    const detail = body?.detail;
    throw new ApiError(typeof detail === "string" ? detail : `No se pudo completar la solicitud (${response.status}).`, response.status);
  }
  return body as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  login: (email: string, password: string) =>
    request<LoginResponse>("/auth/login", undefined, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string) =>
    request<User>("/auth/register", undefined, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: (token: string) => request<User>("/auth/me", token),
  myProfile: (token: string) => request<{ id: number; nombre: string; email: string | null; telefono: string; direccion: string | null }>("/clientes/me", token),
  updateMyContact: (token: string, contact: { telefono: string; direccion: string }) =>
    request<{ mensaje: string; telefono: string; direccion: string }>("/clientes/me/contacto", token, { method: "PUT", body: JSON.stringify(contact) }),
  requestPasswordReset: (email: string) => request<{ mensaje: string }>("/auth/password-reset/request", undefined, { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, password: string) => request<{ mensaje: string }>("/auth/password-reset/confirm", undefined, { method: "POST", body: JSON.stringify({ token, password }) }),
  financialProfile: (token: string, clientId: number) => request<FinancialProfile>(`/clientes/${clientId}/perfil-financiero`, token),
  saveFinancialProfile: (token: string, clientId: number, profile: FinancialProfileInput) =>
    request(`/clientes/${clientId}/perfil-financiero`, token, { method: "POST", body: JSON.stringify(profile) }),
  updateFinancialProfile: (token: string, clientId: number, profile: FinancialProfileInput) =>
    request<{ mensaje: string; perfil_financiero: FinancialProfile }>(`/clientes/${clientId}/perfil-financiero`, token, { method: "PUT", body: JSON.stringify(profile) }),
  requestLoan: (token: string, loan: { monto: number; plazo_meses: number }) =>
    request<{ mensaje: string; credito: Loan["credito"] }>("/creditos/mis", token, { method: "POST", body: JSON.stringify(loan) }),
  myLoans: (token: string) => request<Loan[]>("/creditos/mis", token),
  myNotifications: (token: string) => request<Notification[]>("/notificaciones/", token),
  markAllNotificationsRead: (token: string) =>
    request<Notification[]>("/notificaciones/leer-todas", token, { method: "PATCH" }),
  markNotificationRead: (token: string, notificationId: number) =>
    request<Notification>(`/notificaciones/${notificationId}/leer`, token, { method: "PATCH" }),
  acceptOffer: (token: string, loanId: number, offer: AcceptOffer) =>
    request<{ mensaje: string }>(`/creditos/${loanId}/aceptar`, token, {
      method: "POST",
      body: JSON.stringify(offer),
    }),
};

export const apiHost = API_BASE_URL;
