(() => {
  "use strict";

  const API_BASE = (window.CREDIFRESH_CONFIG?.apiBase || "http://localhost:8000").replace(/\/+$/, "");
  let accessToken = null;
  let activeEmail = "";
  let profileClientId = null;
  let profileClient = null;
  let profileExists = false;
  let selectedCreditDetailId = null;
  let auditRecords = [];
  let auditTotal = 0;
  let auditOffset = 0;
  let auditAppliedFilters = new URLSearchParams();
  let pendingDisbursementLoadError = "";
  let overdueInstallmentsLoadError = "";
  let overdueOffset = 0;
  const AUDIT_PAGE_SIZE = 50;
  const OVERDUE_PAGE_SIZE = 20;
  const AUDIT_ACTION_LABELS = {
    INICIO_SESION: "Inicio de sesión exitoso",
    INICIO_SESION_FALLIDO: "Inicio de sesión fallido",
    INICIO_SESION_BLOQUEADO: "Inicio de sesión bloqueado",
    REGISTRO_PUBLICO_CLIENTE: "Registro público de cliente",
    CREAR_USUARIO: "Crear usuario",
    CAMBIAR_ROL_USUARIO: "Cambiar rol de usuario",
    CAMBIAR_ESTADO_USUARIO: "Cambiar estado de usuario",
    CREAR_CLIENTE: "Crear cliente",
    ACTUALIZAR_CLIENTE: "Actualizar cliente",
    ACTUALIZAR_CONTACTO_CLIENTE: "Actualizar contacto del cliente",
    ELIMINAR_CLIENTE: "Eliminar cliente",
    VINCULAR_CUENTA_CLIENTE: "Vincular cuenta de cliente",
    CREAR_PERFIL_FINANCIERO: "Crear perfil financiero",
    ACTUALIZAR_PERFIL_FINANCIERO: "Actualizar perfil financiero",
    CREAR_CREDITO: "Crear solicitud de crédito",
    ASIGNAR_TASA_CREDITO: "Asignar tasa mensual del crédito",
    EVALUAR_CREDITO: "Evaluar crédito",
    CAMBIAR_ESTADO_CREDITO: "Cambiar estado de crédito",
    ACEPTAR_CONDICIONES_CREDITO: "Aceptar condiciones del crédito",
    DESEMBOLSAR_CREDITO: "Desembolsar crédito",
    DESEMBOLSO_BLOQUEADO_CONDICIONES_DESACTUALIZADAS: "Desembolso bloqueado: condiciones distintas",
    REGISTRAR_PAGO: "Registrar pago",
    LIQUIDAR_CREDITO: "Liquidar crédito",
  };
  let cache = { users: [], clients: [], credits: [], summary: null, portfolio: null, pendingDisbursements: [], overdueInstallments: { items: [], total: 0, limit: OVERDUE_PAGE_SIZE, offset: 0 }, bankOperationsEnabled: null };

  const $ = (id) => document.getElementById(id);
  const loginView = $("login-view");
  const appView = $("app-view");
  const clientView = $("client-view");
  const loginForm = $("login-form");
  const loginMessage = $("login-message");
  const globalMessage = $("global-message");

  function setMessage(node, message, kind = "") {
    node.textContent = message;
    node.className = `message ${kind}`.trim();
  }

  function safe(value, fallback = "—") {
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function cell(text, className = "") {
    const td = document.createElement("td");
    td.textContent = safe(text);
    if (className) td.className = className;
    return td;
  }

  function auditActionLabel(action) {
    return AUDIT_ACTION_LABELS[action] || action;
  }

  function auditDetailsCell(value) {
    const td = document.createElement("td");
    td.className = "audit-details-cell";
    if (!value) {
      td.textContent = "—";
      return td;
    }
    let formatted = value;
    try { formatted = JSON.stringify(JSON.parse(value), null, 2); }
    catch { /* Keep non-JSON legacy detail text readable. */ }
    const disclosure = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Ver detalles";
    const content = document.createElement("pre");
    content.textContent = formatted;
    disclosure.append(summary, content);
    td.append(disclosure);
    return td;
  }

  function table(headers, rows, emptyMessage) {
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap";
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = emptyMessage;
      wrapper.append(empty);
      return wrapper;
    }
    const tableEl = document.createElement("table");
    tableEl.className = "data-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach((header) => {
      const th = document.createElement("th");
      th.textContent = header;
      headRow.append(th);
    });
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => tbody.append(row));
    tableEl.append(thead, tbody);
    wrapper.append(tableEl);
    return wrapper;
  }

  function badge(value, kind) {
    const span = document.createElement("span");
    span.className = `badge ${kind || ""}`.trim();
    span.textContent = safe(value);
    return span;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    if (options.body) headers.set("Content-Type", "application/json");
    let response;
    try {
      response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch {
      throw new Error(`No se pudo conectar con la API en ${API_BASE}. Confirma que el backend esté iniciado.`);
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) {
        logout("La sesión venció. Ingresa de nuevo.");
      }
      const error = new Error(body.detail || `La API respondió ${response.status}.`);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function formatMoney(value) {
    const amount = Number(value || 0);
    return new Intl.NumberFormat("es-CO", {
      style: "currency", currency: "COP", maximumFractionDigits: 0,
    }).format(amount);
  }

  function formatPercentage(value) {
    return `${new Intl.NumberFormat("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`;
  }

  function daysSinceColombiaDate(dateValue) {
    const dayNumber = (date) => {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota", year: "numeric", month: "2-digit", day: "2-digit",
      }).formatToParts(date).reduce((values, part) => {
        if (part.type !== "literal") values[part.type] = Number(part.value);
        return values;
      }, {});
      return Date.UTC(parts.year, parts.month - 1, parts.day);
    };
    return Math.max(0, Math.floor((dayNumber(new Date()) - dayNumber(new Date(dateValue))) / 86400000));
  }

  function downloadCsv(filename, columns, records) {
    if (!records.length) return;
    const csvCell = (value) => {
      let text = value === null || value === undefined ? "" : String(value);
      if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    };
    const csv = [
      columns.map(([label]) => csvCell(label)).join(","),
      ...records.map((record) => columns.map(([, key]) => csvCell(typeof key === "function" ? key(record) : record[key])).join(",")),
    ].join("\r\n");
    const objectUrl = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  function downloadAuditCsv(records) {
    downloadCsv(`credifresh-auditoria-${localDateInputValue()}.csv`, [
      ["ID", "id"], ["Fecha y hora", "fecha_creacion"], ["ID de usuario", "usuario_id"],
      ["Rol", "rol"], ["Acción", "accion"], ["Entidad", "entidad"], ["ID de entidad", "entidad_id"],
      ["Resultado", "resultado"], ["Detalles", "detalles"], ["IP", "ip"],
    ], records);
  }

  function exportPendingDisbursementsCsv() {
    if (pendingDisbursementLoadError) return;
    const search = $("pending-disbursement-search").value.trim().toLocaleLowerCase("es-CO");
    const records = cache.pendingDisbursements.filter((record) =>
      !search || `${record.cliente_nombre} ${record.credito_id}`.toLocaleLowerCase("es-CO").includes(search)
    );
    if (!records.length) return;
    downloadCsv(`credifresh-aceptados-pendientes-${localDateInputValue()}.csv`, [
      ["ID cliente", "cliente_id"], ["Cliente", "cliente_nombre"], ["ID crédito", "credito_id"],
      ["Aceptado por", "aceptado_por"], ["Fecha de aceptación (ISO)", "fecha_aceptacion"],
      ["Días en espera", (record) => daysSinceColombiaDate(record.fecha_aceptacion)],
      ["Monto aceptado COP", "monto"], ["Plazo meses", "plazo_meses"],
      ["Tasa mensual %", "tasa_interes"], ["Cuota aceptada COP", "cuota_mensual"],
      ["Total estimado COP", "total_estimado"], ["Versión condiciones", "condiciones_version"],
    ], records);
    setMessage($("pending-disbursement-message"), `CSV descargado con ${records.length} ${records.length === 1 ? "crédito" : "créditos"}.`, "success");
  }

  async function exportAuditCsv() {
    if (!auditTotal) return;
    const button = $("audit-export-button");
    button.disabled = true;
    setMessage($("audit-message"), "Preparando el CSV con todos los resultados filtrados…", "info");
    try {
      const params = new URLSearchParams(auditAppliedFilters);
      params.set("limit", "200");
      let offset = 0;
      const expectedTotal = auditTotal;
      const records = [];
      do {
        params.set("offset", String(offset));
        const page = await api(`/auditoria/consulta?${params.toString()}`);
        if (page.total !== expectedTotal) {
          throw new Error("La auditoría cambió durante la exportación. Actualiza los eventos e inténtalo de nuevo.");
        }
        if (!page.items.length && offset < expectedTotal) {
          throw new Error("La auditoría cambió durante la exportación. Actualiza los eventos e inténtalo de nuevo.");
        }
        records.push(...page.items);
        if (!page.items.length) break;
        offset += page.items.length;
      } while (offset < expectedTotal);
      if (records.length !== expectedTotal) {
        throw new Error("No se pudieron recuperar todos los eventos. Actualiza los eventos e inténtalo de nuevo.");
      }
      downloadAuditCsv(records);
      setMessage($("audit-message"), `CSV descargado con ${records.length} ${records.length === 1 ? "evento" : "eventos"}.`, "success");
    } catch (error) {
      setMessage($("audit-message"), error.message || "No se pudo exportar la auditoría.");
    } finally {
      button.disabled = auditTotal === 0;
    }
  }

  function getEffectiveAnnualRate(monthlyRate) {
    if (monthlyRate === null || monthlyRate === undefined || String(monthlyRate).trim() === "") return null;
    const monthly = Number(monthlyRate);
    if (!Number.isFinite(monthly) || monthly < 0) return null;
    return ((1 + monthly / 100) ** 12 - 1) * 100;
  }

  function updateRateEquivalence() {
    const input = $("credit-rate");
    const effectiveAnnual = getEffectiveAnnualRate(input.value);
    $("credit-rate-equivalent").textContent = effectiveAnnual === null
      ? "La equivalencia E.A. aparecerá al ingresar una tasa mensual."
      : `Equivale aproximadamente a ${formatPercentage(effectiveAnnual)} E.A. (capitalización mensual). Es una conversión matemática, no valida el límite legal aplicable.`;
  }

  function localDateInputValue() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${now.getFullYear()}-${month}-${day}`;
  }

  async function changeUserActive(user, button) {
    const nextActive = !user.activo;
    const action = nextActive ? "reactivar" : "desactivar";
    const warning = nextActive
      ? `¿Reactivar la cuenta de ${user.email}? Podrá volver a iniciar sesión.`
      : `¿Desactivar la cuenta de ${user.email}? Perderá acceso al sistema. Podrás reactivarla después.`;
    if (!window.confirm(warning)) return;

    button.disabled = true;
    try {
      await api(`/usuarios/${user.id}/activo`, {
        method: "PATCH",
        body: JSON.stringify({ activo: nextActive }),
      });
      await loadDashboard();
      setMessage(globalMessage, `Cuenta ${nextActive ? "reactivada" : "desactivada"} correctamente.`, "success");
    } catch (error) {
      setMessage(globalMessage, error.message || `No se pudo ${action} la cuenta.`);
      button.disabled = false;
    }
  }

  async function changeUserRole(user, select, button) {
    const nextRole = select.value;
    if (!nextRole || nextRole === user.rol) return;
    const roleNames = { ADMIN: "Admin", GESTOR: "Gestor", CLIENTE: "Cliente" };
    const warning = nextRole === "ADMIN"
      ? `¿Asignar el rol Admin a ${user.email}? Tendrá permisos completos para gestionar usuarios y operaciones.`
      : `¿Cambiar el rol de ${user.email} de ${roleNames[user.rol] || user.rol} a ${roleNames[nextRole]}?`;
    if (!window.confirm(warning)) {
      select.value = user.rol;
      return;
    }

    button.disabled = true;
    select.disabled = true;
    try {
      await api(`/usuarios/${user.id}/rol`, {
        method: "PATCH",
        body: JSON.stringify({ rol: nextRole }),
      });
      await loadDashboard();
      setMessage(globalMessage, `Rol actualizado a ${roleNames[nextRole]}.`, "success");
    } catch (error) {
      select.value = user.rol;
      select.disabled = false;
      button.disabled = false;
      setMessage(globalMessage, error.message || "No se pudo cambiar el rol.");
    }
  }

  function renderAuditUserOptions() {
    const select = $("audit-user-filter");
    const selectedId = select.value;
    const options = [new Option("Todos los usuarios", "")];
    cache.users
      .slice()
      .sort((left, right) => left.email.localeCompare(right.email, "es-CO"))
      .forEach((user) => options.push(new Option(`${user.email} · ${user.rol}`, String(user.id))));
    select.replaceChildren(...options);
    if (cache.users.some((user) => String(user.id) === selectedId)) select.value = selectedId;
  }

  function renderUsers() {
    const roleFilter = $("user-role-filter").value;
    const activeFilter = $("user-active-filter").value;
    const emailQuery = $("user-email-search").value.trim().toLocaleLowerCase("es-CO");
    const visibleUsers = cache.users.filter((user) => {
      const matchesRole = !roleFilter || user.rol === roleFilter;
      const matchesActive = !activeFilter || user.activo === (activeFilter === "true");
      const matchesEmail = !emailQuery || (user.email || "").toLocaleLowerCase("es-CO").includes(emailQuery);
      return matchesRole && matchesActive && matchesEmail;
    });
    $("users-count").textContent = visibleUsers.length === cache.users.length
      ? String(cache.users.length)
      : `${visibleUsers.length} de ${cache.users.length}`;
    const rows = visibleUsers.map((user) => {
      const tr = document.createElement("tr");
      tr.append(cell(user.email, "primary-cell"));
      const roleCell = document.createElement("td");
      const roleClass = { ADMIN: "badge-admin", GESTOR: "badge-gestor", CLIENTE: "badge-cliente" }[user.rol] || "";
      roleCell.append(badge(user.rol, roleClass));
      tr.append(roleCell);
      const stateCell = document.createElement("td");
      stateCell.append(badge(user.activo ? "Activo" : "Inactivo", user.activo ? "badge-active" : "badge-inactive"));
      tr.append(stateCell);
      const actionCell = document.createElement("td");
      if (user.email.toLowerCase() === activeEmail.toLowerCase()) {
        actionCell.textContent = "Cuenta actual · sin cambios de rol";
        actionCell.className = "secondary-cell";
      } else {
        const roleSelect = document.createElement("select");
        roleSelect.className = "user-row-role-select";
        roleSelect.setAttribute("aria-label", `Nuevo rol para ${user.email}`);
        [["CLIENTE", "Cliente"], ["GESTOR", "Gestor"], ["ADMIN", "Admin"]].forEach(([value, label]) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          roleSelect.append(option);
        });
        roleSelect.value = user.rol;
        const roleButton = document.createElement("button");
        roleButton.type = "button";
        roleButton.className = "table-action";
        roleButton.textContent = "Guardar rol";
        roleButton.addEventListener("click", () => changeUserRole(user, roleSelect, roleButton));
        actionCell.append(roleSelect, roleButton);

        const actionButton = document.createElement("button");
        actionButton.type = "button";
        actionButton.className = "table-action";
        actionButton.textContent = user.activo ? "Desactivar" : "Reactivar";
        actionButton.addEventListener("click", () => changeUserActive(user, actionButton));
        actionCell.append(actionButton);
      }
      tr.append(actionCell);
      return tr;
    });
    $("users-table").replaceChildren(table(["Correo", "Rol", "Estado", "Acciones"], rows, "No hay usuarios que coincidan con esos filtros."));
  }

  function renderProfileDetails(profile) {
    const entries = [
      ["Ingresos mensuales", formatMoney(profile.ingresos_mensuales)],
      ["Gastos mensuales", formatMoney(profile.gastos_mensuales)],
      ["Otras obligaciones", formatMoney(profile.otras_obligaciones)],
      ["Tipo de ingresos", profile.tipo_ingresos],
      ["Actividad económica", profile.actividad_economica],
    ];
    const grid = $("profile-details");
    grid.replaceChildren();
    entries.forEach(([label, value]) => {
      const item = document.createElement("div");
      item.className = "profile-item";
      const labelEl = document.createElement("span");
      labelEl.textContent = label;
      const valueEl = document.createElement("strong");
      valueEl.textContent = safe(value);
      item.append(labelEl, valueEl);
      grid.append(item);
    });
    grid.hidden = false;
    $("profile-form").hidden = true;
  }

  async function openClientProfile(client) {
    profileClientId = client.id;
    profileClient = client;
    profileExists = false;
    $("profile-form").reset();
    $("client-profile-title").textContent = `Perfil financiero · ${client.nombre}`;
    $("contact-client-name").value = client.nombre || "";
    $("contact-client-id").value = client.cedula || "";
    $("contact-client-phone").value = client.telefono || "";
    $("contact-client-address").value = client.direccion || "";
    $("contact-client-email").value = client.email || "";
    setMessage($("client-contact-message"), "");
    $("client-profile-panel").hidden = false;
    renderClientAccountLink(client);
    $("profile-details").hidden = true;
    $("profile-form").hidden = true;
    setMessage($("profile-message"), "Consultando perfil…");
    try {
      const profile = await api(`/clientes/${client.id}/perfil-financiero`);
      profileExists = true;
      $("profile-income").value = profile.ingresos_mensuales;
      $("profile-expenses").value = profile.gastos_mensuales;
      $("profile-obligations").value = profile.otras_obligaciones;
      $("profile-income-type").value = profile.tipo_ingresos;
      $("profile-activity").value = profile.actividad_economica;
      $("profile-form").hidden = false;
      $("profile-submit-button").textContent = "Actualizar perfil";
      setMessage($("profile-message"), "Perfil existente. Puedes corregir o actualizar sus datos.", "info");
    } catch (error) {
      if (error.status === 404 && error.message === "Perfil financiero no encontrado") {
        $("profile-form").hidden = false;
        $("profile-submit-button").textContent = "Guardar perfil";
        setMessage($("profile-message"), "Este cliente aún no tiene perfil. Completa los datos con información autorizada.", "info");
      } else {
        setMessage($("profile-message"), error.message || "No se pudo consultar el perfil.");
      }
    }
  }

  function renderClientAccountLink(client) {
    const select = $("client-linked-user");
    const button = $("link-client-account-button");
    select.replaceChildren();
    if (client.usuario_id) {
      const linkedUser = cache.users.find((user) => user.id === client.usuario_id);
      const option = document.createElement("option");
      option.value = String(client.usuario_id);
      option.textContent = linkedUser?.email || `Usuario ${client.usuario_id}`;
      option.selected = true;
      select.append(option);
      select.disabled = true;
      button.hidden = true;
      setMessage($("client-account-link-message"), "Esta cuenta ya puede iniciar sesión y consultar los créditos de este cliente.", "success");
      return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Selecciona una cuenta CLIENTE activa";
    placeholder.disabled = true;
    placeholder.selected = true;
    select.append(placeholder);
    const linkedUserIds = new Set(cache.clients.filter((item) => item.usuario_id).map((item) => item.usuario_id));
    const availableUsers = cache.users.filter((user) => user.rol === "CLIENTE" && user.activo && !linkedUserIds.has(user.id));
    availableUsers.forEach((user) => {
      const option = document.createElement("option");
      option.value = String(user.id);
      option.textContent = user.email;
      select.append(option);
    });
    select.disabled = availableUsers.length === 0;
    button.hidden = false;
    button.disabled = availableUsers.length === 0;
    setMessage(
      $("client-account-link-message"),
      availableUsers.length ? "Al vincularla, esa cuenta podrá ver el perfil y los créditos de este cliente." : "No hay cuentas CLIENTE activas disponibles. Crea una cuenta antes de vincularla.",
      "info"
    );
  }

  async function linkClientAccount() {
    if (!profileClient) return;
    const userId = Number($("client-linked-user").value);
    const user = cache.users.find((item) => item.id === userId);
    if (!user) {
      setMessage($("client-account-link-message"), "Selecciona una cuenta CLIENTE activa.");
      return;
    }
    if (!window.confirm(`¿Vincular ${user.email} con el perfil de ${profileClient.nombre}? Esa cuenta podrá ver sus créditos y aceptar condiciones.`)) return;

    const button = $("link-client-account-button");
    button.disabled = true;
    try {
      const result = await api(`/clientes/${profileClient.id}/vincular-usuario`, {
        method: "PATCH",
        body: JSON.stringify({ usuario_id: user.id }),
      });
      profileClient.usuario_id = result.cliente.usuario_id;
      const cachedClient = cache.clients.find((item) => item.id === profileClient.id);
      if (cachedClient) cachedClient.usuario_id = result.cliente.usuario_id;
      renderClientAccountLink(profileClient);
      renderClients();
      setMessage($("client-account-link-message"), result.mensaje, "success");
    } catch (error) {
      button.disabled = false;
      setMessage($("client-account-link-message"), error.message || "No se pudo vincular la cuenta.");
    }
  }

  function renderClients() {
    const query = $("client-search-input").value.trim().toLocaleLowerCase("es-CO");
    const visibleClients = cache.clients.filter((client) => {
      const searchable = `${client.nombre || ""} ${client.cedula || ""} ${client.email || ""}`.toLocaleLowerCase("es-CO");
      return !query || searchable.includes(query);
    });
    $("clients-count").textContent = visibleClients.length === cache.clients.length
      ? String(cache.clients.length)
      : `${visibleClients.length} de ${cache.clients.length}`;
    const rows = visibleClients.map((client) => {
      const tr = document.createElement("tr");
      tr.append(cell(client.nombre, "primary-cell"), cell(client.email || "—"), cell(client.cedula), cell(client.telefono), cell(client.direccion || "—"), cell(client.id));
      const action = document.createElement("td");
      const profileButton = document.createElement("button");
      profileButton.type = "button";
      profileButton.className = "table-action";
      profileButton.textContent = "Perfil financiero";
      profileButton.addEventListener("click", () => openClientProfile(client));
      action.append(profileButton);
      tr.append(action);
      return tr;
    });
    $("clients-table").replaceChildren(table(["Nombre", "Correo", "Documento", "Teléfono", "Dirección", "ID", "Perfil"], rows, "No hay clientes que coincidan con la búsqueda."));
  }

  function renderCredits() {
    const statusFilter = $("credit-status-filter").value;
    const clientQuery = $("credit-client-search").value.trim().toLocaleLowerCase("es-CO");
    const states = [
      ["SOLICITADO", "Solicitados"], ["APROBADO", "Aprobados"], ["RECHAZADO", "Rechazados"],
      ["DESEMBOLSADO", "Desembolsados"], ["PAGADO", "Pagados"],
    ];
    const stateSummary = $("credit-state-summary");
    stateSummary.replaceChildren();
    states.forEach(([state, label]) => {
      const count = cache.credits.filter((credit) => credit.estado === state).length;
      const item = document.createElement("span");
      item.className = "credit-state-item";
      item.textContent = `${label}: ${count}`;
      stateSummary.append(item);
    });
    $("new-credit-button").disabled = cache.clients.length === 0;
    $("new-credit-button").title = cache.clients.length === 0 ? "Registra un cliente antes de crear una solicitud" : "Crear una solicitud de crédito";
    const names = new Map(cache.clients.map((client) => [client.id, client.nombre]));
    const makeCreditRow = (credit, withAction = false) => {
      const tr = document.createElement("tr");
      tr.append(cell(names.get(credit.cliente_id) || `Cliente ${credit.cliente_id}`, "primary-cell"));
      const rateText = Number(credit.tasa_interes) > 0 ? `${safe(credit.tasa_interes)}%` : "Por asignar";
      tr.append(cell(formatMoney(credit.monto)), cell(`${safe(credit.plazo_meses)} meses`), cell(rateText));
      const stateCell = document.createElement("td");
      stateCell.append(badge(credit.estado));
      tr.append(stateCell);
      if (withAction) {
        const actionCell = document.createElement("td");
        const detailsButton = document.createElement("button");
        detailsButton.type = "button";
        detailsButton.className = "table-action";
        detailsButton.textContent = "Detalle";
        detailsButton.addEventListener("click", () => showCreditDetails(credit));
        actionCell.append(detailsButton);
        if (credit.estado === "SOLICITADO") {
          const evaluateButton = document.createElement("button");
          evaluateButton.type = "button";
          evaluateButton.className = "table-action";
          evaluateButton.textContent = "Evaluación automática";
          evaluateButton.addEventListener("click", () => evaluateCredit(credit.id, evaluateButton));
          actionCell.append(evaluateButton);
        }
        tr.append(actionCell);
      }
      return tr;
    };
    const visibleCredits = cache.credits.filter((credit) => {
      const clientName = names.get(credit.cliente_id) || `Cliente ${credit.cliente_id}`;
      const matchesStatus = !statusFilter || credit.estado === statusFilter;
      const matchesClient = !clientQuery || clientName.toLocaleLowerCase("es-CO").includes(clientQuery);
      return matchesStatus && matchesClient;
    });
    $("credits-count").textContent = visibleCredits.length === cache.credits.length
      ? String(cache.credits.length)
      : `${visibleCredits.length} de ${cache.credits.length}`;
    const rows = visibleCredits.map((credit) => makeCreditRow(credit, true));
    $("credits-table").replaceChildren(table(["Cliente", "Monto", "Plazo", "Tasa", "Estado", "Acción"], rows, "No hay créditos que coincidan con esos filtros."));
    const recent = cache.credits.slice(-5).reverse().map((credit) => makeCreditRow(credit));
    $("recent-credits").replaceChildren(table(["Cliente", "Monto", "Plazo", "Tasa", "Estado"], recent, "Aún no hay solicitudes de crédito."));
  }

  function renderPendingDisbursements(error = "") {
    const records = cache.pendingDisbursements;
    const search = $("pending-disbursement-search").value.trim().toLocaleLowerCase("es-CO");
    const visibleRecords = records.filter((record) =>
      !search || `${record.cliente_nombre} ${record.credito_id}`.toLocaleLowerCase("es-CO").includes(search)
    );
    $("pending-disbursement-export-button").disabled = visibleRecords.length === 0 || Boolean(error);
    const rows = visibleRecords.map((record) => {
      const row = document.createElement("tr");
      const acceptedAt = record.fecha_aceptacion
        ? new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota" }).format(new Date(record.fecha_aceptacion))
        : "—";
      const daysWaiting = record.fecha_aceptacion ? daysSinceColombiaDate(record.fecha_aceptacion) : null;
      const state = document.createElement("td");
      state.append(badge("En espera de integración bancaria", "badge-pending"));
      const action = document.createElement("td");
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "table-action";
      detailButton.textContent = "Ver crédito";
      const credit = cache.credits.find((item) => item.id === record.credito_id);
      detailButton.disabled = !credit;
      if (credit) detailButton.addEventListener("click", () => showCreditDetails(credit));
      action.append(detailButton);
      row.append(
        cell(record.cliente_nombre, "primary-cell"), cell(`#${record.credito_id}`), cell(acceptedAt),
        cell(daysWaiting === null ? "—" : `${daysWaiting} ${daysWaiting === 1 ? "día" : "días"}`),
        cell(formatMoney(record.monto)), cell(`${record.plazo_meses} meses`),
        cell(`${safe(record.tasa_interes)} %`), cell(formatMoney(record.cuota_mensual)),
        cell(formatMoney(record.total_estimado)), cell(record.condiciones_version), state, action,
      );
      return row;
    });
    $("pending-disbursement-table").replaceChildren(table(
      ["Cliente", "Crédito", "Aceptado", "Días en espera", "Monto", "Plazo", "Tasa mensual", "Cuota estimada", "Total estimado", "Versión", "Seguimiento", ""],
      rows,
      search ? "No hay coincidencias para esta búsqueda." : "No hay créditos aceptados pendientes de desembolso.",
    ));
    if (error) setMessage($("pending-disbursement-message"), `No se pudo actualizar la lista. Se muestran los últimos datos cargados. ${error}`);
    else if (search) setMessage($("pending-disbursement-message"), `${visibleRecords.length} de ${records.length} ${records.length === 1 ? "caso" : "casos"} en espera.`, "info");
    else setMessage($("pending-disbursement-message"), `${records.length} ${records.length === 1 ? "caso" : "casos"} en espera.`, records.length ? "info" : "success");
  }

  function renderBankOperationsStatus() {
    const status = $("bank-operations-status");
    const note = $("bank-operation-note");
    if (cache.bankOperationsEnabled === true) {
      status.className = "status-pill status-enabled";
      status.textContent = "Operaciones habilitadas";
      note.textContent = "La API permite desembolsos y registro de pagos. Confirma la transferencia y la recepción de fondos antes de registrar movimientos.";
    } else if (cache.bankOperationsEnabled === false) {
      status.className = "status-pill status-waiting";
      status.textContent = "Operaciones bloqueadas";
      note.textContent = "La API bloquea desembolsos y pagos hasta configurar y habilitar el proceso bancario.";
    } else {
      status.className = "status-pill status-unknown";
      status.textContent = "Estado no disponible";
      note.textContent = "No se pudo consultar si los desembolsos y pagos están habilitados en la API.";
    }
  }

  function renderOverdueInstallments(error = "") {
    const page = cache.overdueInstallments;
    const installments = page.items || [];
    const rows = installments.map((installment) => {
      const row = document.createElement("tr");
      const dueAt = installment.fecha_vencimiento
        ? new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "America/Bogota" }).format(new Date(installment.fecha_vencimiento))
        : "—";
      const credit = cache.credits.find((item) => item.id === installment.credito_id);
      const action = document.createElement("td");
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "table-action";
      detailButton.textContent = "Ver crédito";
      detailButton.disabled = !credit;
      if (credit) detailButton.addEventListener("click", () => showCreditDetails(credit));
      action.append(detailButton);
      row.append(
        cell(installment.cliente_nombre, "primary-cell"),
        cell(`#${installment.credito_id}`),
        cell(`#${installment.numero_cuota}`),
        cell(dueAt),
        cell(`${installment.dias_vencida} ${installment.dias_vencida === 1 ? "día" : "días"}`),
        cell(formatMoney(installment.saldo_pendiente)),
        action,
      );
      return row;
    });
    $("overdue-installments-table").replaceChildren(table(
      ["Cliente", "Crédito", "Cuota", "Vencimiento", "Días de atraso", "Saldo pendiente", ""],
      rows,
      error ? "No hay datos recientes disponibles." : "No hay cuotas vencidas registradas.",
    ));
    const firstResult = page.total ? page.offset + 1 : 0;
    const lastResult = Math.min(page.offset + installments.length, page.total);
    $("overdue-page-info").textContent = `Mostrando ${firstResult}–${lastResult} de ${page.total}`;
    $("overdue-previous-button").disabled = Boolean(error) || page.offset === 0;
    $("overdue-next-button").disabled = Boolean(error) || page.offset + installments.length >= page.total;
    $("overdue-export-button").disabled = Boolean(error) || page.total === 0;
    if (error) setMessage($("overdue-installments-message"), `No se pudo actualizar la lista. Se muestran los últimos datos cargados. ${error}`);
    else setMessage($("overdue-installments-message"), `${page.total} ${page.total === 1 ? "cuota vencida" : "cuotas vencidas"} en la cartera.`, page.total ? "info" : "success");
  }

  async function loadOverdueInstallments(offset) {
    $("overdue-previous-button").disabled = true;
    $("overdue-next-button").disabled = true;
    $("overdue-export-button").disabled = true;
    setMessage($("overdue-installments-message"), "Consultando cuotas vencidas…", "info");
    try {
      cache.overdueInstallments = await api(`/reportes/cuotas-vencidas?limit=${OVERDUE_PAGE_SIZE}&offset=${offset}`);
      overdueOffset = cache.overdueInstallments.offset;
      overdueInstallmentsLoadError = "";
    } catch (error) {
      overdueInstallmentsLoadError = error.message || "No se pudo consultar la cartera vencida.";
    }
    renderOverdueInstallments(overdueInstallmentsLoadError);
  }

  async function exportOverdueInstallmentsCsv() {
    const button = $("overdue-export-button");
    if (!cache.overdueInstallments.total || overdueInstallmentsLoadError) return;
    button.disabled = true;
    setMessage($("overdue-installments-message"), "Preparando CSV con todas las cuotas vencidas…", "info");
    try {
      const records = [];
      let offset = 0;
      const expectedTotal = cache.overdueInstallments.total;
      do {
        const page = await api(`/reportes/cuotas-vencidas?limit=100&offset=${offset}`);
        if (page.total !== expectedTotal) {
          throw new Error("La cartera cambió durante la exportación. Actualiza el resumen e inténtalo de nuevo.");
        }
        if (!page.items.length && offset < expectedTotal) {
          throw new Error("La cartera cambió durante la exportación. Actualiza el resumen e inténtalo de nuevo.");
        }
        records.push(...page.items);
        if (!page.items.length) break;
        offset += page.items.length;
      } while (offset < expectedTotal);
      if (records.length !== expectedTotal) {
        throw new Error("No se pudieron recuperar todas las cuotas. Actualiza el resumen e inténtalo de nuevo.");
      }
      downloadCsv(`credifresh-cuotas-vencidas-${localDateInputValue()}.csv`, [
        ["ID cliente", "cliente_id"], ["Cliente", "cliente_nombre"], ["ID crédito", "credito_id"],
        ["ID cuota", "cuota_id"], ["Número de cuota", "numero_cuota"],
        ["Fecha de vencimiento (ISO)", "fecha_vencimiento"], ["Días de atraso", "dias_vencida"],
        ["Saldo pendiente COP", "saldo_pendiente"],
      ], records);
      setMessage($("overdue-installments-message"), `CSV descargado con ${records.length} ${records.length === 1 ? "cuota vencida" : "cuotas vencidas"}.`, "success");
    } catch (error) {
      setMessage($("overdue-installments-message"), error.message || "No se pudieron exportar las cuotas vencidas.");
    } finally {
      button.disabled = !cache.overdueInstallments.total || Boolean(overdueInstallmentsLoadError);
    }
  }

  function addCreditDetail(grid, label, value) {
    const item = document.createElement("div");
    item.className = "profile-item";
    const labelEl = document.createElement("span");
    labelEl.textContent = label;
    const valueEl = document.createElement("strong");
    valueEl.textContent = safe(value);
    item.append(labelEl, valueEl);
    grid.append(item);
  }

  async function showCreditDetails(creditSummary) {
    const panel = $("credit-details-panel");
    const requestGrid = $("credit-request-details");
    const evaluationGrid = $("credit-evaluation-details");
    const acceptanceGrid = $("credit-acceptance-details");
    const rateForm = $("credit-rate-form");
    const rejectionForm = $("credit-rejection-form");
    panel.hidden = false;
    selectedCreditDetailId = creditSummary.id;
    $("credit-simulation-panel").hidden = true;
    $("credit-simulation-summary").replaceChildren();
    $("credit-amortization-table").replaceChildren();
    setMessage($("credit-simulation-message"), "");
    requestGrid.replaceChildren();
    evaluationGrid.replaceChildren();
    acceptanceGrid.replaceChildren();
    evaluationGrid.hidden = true;
    acceptanceGrid.hidden = true;
    rateForm.hidden = true;
    rejectionForm.hidden = true;
    setMessage($("credit-rate-message"), "");
    setMessage($("credit-rejection-message"), "");
    setMessage($("credit-details-message"), "Consultando detalle…", "info");
    panel.scrollIntoView({ behavior: "smooth", block: "start" });

    try {
      const credit = await api(`/creditos/${creditSummary.id}`);
      const client = cache.clients.find((item) => item.id === credit.cliente_id);
      $("credit-details-title").textContent = `Detalle del crédito #${credit.id}`;
      addCreditDetail(requestGrid, "Cliente", client?.nombre || `Cliente ${credit.cliente_id}`);
      addCreditDetail(requestGrid, "Monto solicitado", formatMoney(credit.monto));
      addCreditDetail(requestGrid, "Plazo", `${safe(credit.plazo_meses)} meses`);
      addCreditDetail(requestGrid, "Tasa mensual", Number(credit.tasa_interes) > 0 ? `${safe(credit.tasa_interes)}%` : "Pendiente de asignación");
      if (credit.estado === "SOLICITADO" && Number(credit.tasa_interes) <= 0) {
        rateForm.hidden = false;
        $("credit-rate-value").value = "";
      }
      rejectionForm.hidden = credit.estado !== "SOLICITADO";
      const effectiveAnnualRate = getEffectiveAnnualRate(credit.tasa_interes);
      if (effectiveAnnualRate !== null) addCreditDetail(requestGrid, "Equivalencia matemática E.A.", formatPercentage(effectiveAnnualRate));
      addCreditDetail(requestGrid, "Estado", credit.estado);
      addCreditDetail(requestGrid, "Fecha de solicitud", credit.fecha_creacion ? new Date(credit.fecha_creacion).toLocaleString("es-CO") : "—");
      if (credit.estado === "APROBADO") {
        const dateInput = $("credit-simulation-date");
        dateInput.min = localDateInputValue();
        dateInput.value = dateInput.min;
        $("credit-simulation-panel").hidden = false;
      }

      try {
        const evaluation = await api(`/creditos/${credit.id}/evaluacion`);
        addCreditDetail(evaluationGrid, "Decisión", evaluation.decision);
        if (evaluation.tipo === "MANUAL") {
          addCreditDetail(evaluationGrid, "Tipo de decisión", "Rechazo manual");
        } else {
          addCreditDetail(evaluationGrid, "Cuota mensual estimada", formatMoney(evaluation.cuota_mensual));
          addCreditDetail(evaluationGrid, "Capacidad mensual calculada", formatMoney(evaluation.capacidad_mensual));
        }
        addCreditDetail(evaluationGrid, "Motivos", evaluation.motivos);
        addCreditDetail(evaluationGrid, "Fecha de evaluación", evaluation.fecha_evaluacion ? new Date(evaluation.fecha_evaluacion).toLocaleString("es-CO") : "—");
        evaluationGrid.hidden = false;
        setMessage($("credit-details-message"), "Detalle consultado. Esta vista no desembolsa ni mueve dinero.", "success");
      } catch (error) {
        if (error.status === 404 && error.message === "El crédito aún no tiene una evaluación") {
          setMessage($("credit-details-message"), "La solicitud todavía no tiene una evaluación guardada.", "info");
        } else {
          throw error;
        }
      }

      try {
        const acceptance = await api(`/creditos/${credit.id}/aceptacion`);
        addCreditDetail(acceptanceGrid, "Aceptación", "Aceptada por el cliente");
        addCreditDetail(acceptanceGrid, "Cuenta que aceptó", acceptance.aceptado_por);
        addCreditDetail(acceptanceGrid, "Fecha y hora", new Intl.DateTimeFormat("es-CO", {
          dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota",
        }).format(new Date(acceptance.fecha_aceptacion)));
        addCreditDetail(acceptanceGrid, "Monto aceptado", formatMoney(acceptance.monto));
        addCreditDetail(acceptanceGrid, "Plazo aceptado", `${acceptance.plazo_meses} meses`);
        addCreditDetail(acceptanceGrid, "Tasa mensual aceptada", `${acceptance.tasa_interes} %`);
        addCreditDetail(acceptanceGrid, "Cuota aceptada", formatMoney(acceptance.cuota_mensual));
        addCreditDetail(acceptanceGrid, "Total estimado aceptado", formatMoney(acceptance.total_estimado));
        addCreditDetail(acceptanceGrid, "Versión de condiciones", acceptance.condiciones_version);
        acceptanceGrid.hidden = false;
      } catch (error) {
        if (error.status === 404 && error.message === "El cliente aún no ha aceptado las condiciones") {
          addCreditDetail(acceptanceGrid, "Aceptación", "Pendiente por el cliente");
          acceptanceGrid.hidden = false;
        } else {
          throw error;
        }
      }
    } catch (error) {
      setMessage($("credit-details-message"), error.message || "No se pudo consultar el detalle.");
    }
  }

  async function simulateCreditAmortization() {
    const creditId = selectedCreditDetailId;
    if (!creditId) return;
    const dateInput = $("credit-simulation-date");
    const selectedDate = dateInput.value;
    if (!selectedDate || selectedDate < dateInput.min) {
      setMessage($("credit-simulation-message"), "Elige una fecha de hoy o posterior.");
      return;
    }
    const button = $("simulate-credit-button");
    button.disabled = true;
    $("credit-simulation-summary").replaceChildren();
    $("credit-amortization-table").replaceChildren();
    setMessage($("credit-simulation-message"), "Calculando cuotas estimadas…", "info");
    try {
      const query = new URLSearchParams({ fecha_inicio: selectedDate });
      const result = await api(`/creditos/${creditId}/simulacion-amortizacion?${query}`);
      if (selectedCreditDetailId !== creditId) return;
      const summary = document.createElement("p");
      summary.className = "form-note";
      summary.textContent = `${result.nota} Total estimado: ${formatMoney(result.total_estimado)}.`;
      $("credit-simulation-summary").replaceChildren(summary);
      const rows = result.cuotas.map((installment) => {
        const row = document.createElement("tr");
        const estimatedDate = installment.fecha_vencimiento
          ? new Date(installment.fecha_vencimiento).toLocaleDateString("es-CO", { timeZone: "UTC" })
          : "—";
        row.append(
          cell(installment.numero_cuota), cell(estimatedDate), cell(formatMoney(installment.monto_cuota)),
          cell(formatMoney(installment.capital)), cell(formatMoney(installment.interes)),
          cell(formatMoney(installment.saldo_remanente))
        );
        return row;
      });
      $("credit-amortization-table").replaceChildren(table(
        ["Cuota", "Fecha tentativa", "Pago estimado", "Capital", "Interés", "Saldo restante"],
        rows,
        "No hay cuotas para mostrar."
      ));
      setMessage($("credit-simulation-message"), "Simulación lista; no se guardó ni se desembolsó el crédito.", "success");
    } catch (error) {
      setMessage($("credit-simulation-message"), error.message || "No se pudo calcular la simulación.");
    } finally {
      button.disabled = false;
    }
  }

  function renderClientCredits(entries) {
    const list = $("client-credit-list");
    list.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No tienes solicitudes de crédito registradas todavía.";
      list.append(empty);
      return;
    }

    entries.forEach((entry) => {
      const credit = entry.credito;
      const evaluation = entry.evaluacion;
      const acceptance = entry.aceptacion;
      const card = document.createElement("article");
      card.className = "content-card client-credit-card";
      const heading = document.createElement("div");
      heading.className = "client-credit-heading";
      const title = document.createElement("h2");
      title.textContent = `Solicitud #${credit.id}`;
      heading.append(title, badge(credit.estado));
      const details = document.createElement("div");
      details.className = "profile-grid";
      addCreditDetail(details, "Monto", formatMoney(acceptance?.monto ?? credit.monto));
      addCreditDetail(details, "Plazo", `${safe(acceptance?.plazo_meses ?? credit.plazo_meses)} meses`);
      addCreditDetail(details, "Tasa mensual", `${safe(acceptance?.tasa_interes ?? credit.tasa_interes)}%`);
      const annualRate = getEffectiveAnnualRate(acceptance?.tasa_interes ?? credit.tasa_interes);
      if (annualRate !== null) addCreditDetail(details, "Equivalencia matemática E.A.", formatPercentage(annualRate));
      if (evaluation?.decision === "APROBADO") {
        addCreditDetail(details, "Cuota mensual estimada", formatMoney(acceptance?.cuota_mensual ?? evaluation.cuota_mensual));
        const totalEstimado = acceptance?.total_estimado ?? entry.total_estimado;
        if (totalEstimado !== null && totalEstimado !== undefined) {
          addCreditDetail(details, "Total estimado", formatMoney(totalEstimado));
        }
      }
      card.append(heading, details);

      if (acceptance) {
        const acceptedMessage = document.createElement("p");
        acceptedMessage.className = "message success";
        acceptedMessage.textContent = `Condiciones aceptadas desde tu sesión el ${new Date(acceptance.fecha_aceptacion).toLocaleString("es-CO")}. La aceptación no desembolsa el crédito.`;
        card.append(acceptedMessage);
      }

      if (credit.estado === "APROBADO" && evaluation?.decision === "APROBADO" && !acceptance) {
          const consentForm = document.createElement("form");
          consentForm.className = "client-consent-form";
          const consentLabel = document.createElement("label");
          consentLabel.className = "client-consent-label";
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.required = true;
          const consentText = document.createElement("span");
          consentText.textContent = "He leído y acepto el monto, plazo, tasa mensual y cuota estimada mostrados para esta solicitud.";
          consentLabel.append(checkbox, consentText);
          const note = document.createElement("p");
          note.className = "form-note";
          note.textContent = "Al confirmar, se guardarán la fecha, tu cuenta y una copia de estas condiciones. Esto no desembolsa el crédito.";
          const message = document.createElement("p");
          message.className = "message";
          message.setAttribute("role", "status");
          message.setAttribute("aria-live", "polite");
          const submit = document.createElement("button");
          submit.type = "submit";
          submit.className = "button button-primary";
          submit.textContent = "Acepto las condiciones";
          consentForm.append(consentLabel, note, message, submit);
          consentForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!checkbox.checked) return;
            submit.disabled = true;
            setMessage(message, "Registrando tu aceptación…", "info");
            try {
              const result = await api(`/creditos/${credit.id}/aceptar`, {
                method: "POST",
                body: JSON.stringify({
                  acepta: true,
                  monto: Number(acceptance?.monto ?? credit.monto),
                  plazo_meses: Number(acceptance?.plazo_meses ?? credit.plazo_meses),
                  tasa_interes: Number(acceptance?.tasa_interes ?? credit.tasa_interes),
                  cuota_mensual: Number(acceptance?.cuota_mensual ?? evaluation.cuota_mensual),
                  total_estimado: Number(acceptance?.total_estimado ?? entry.total_estimado),
                }),
              });
              await loadClientPortal();
              setMessage($("client-portal-message"), result.mensaje, "success");
            } catch (error) {
              setMessage(message, error.message || "No se pudo registrar la aceptación.");
              submit.disabled = false;
            }
          });
          card.append(consentForm);
      } else if (credit.estado === "SOLICITADO") {
        const pending = document.createElement("p");
        pending.className = "message info";
        pending.textContent = "Tu solicitud está pendiente de evaluación. Aún no hay condiciones aprobadas para aceptar.";
        card.append(pending);
      }

      if (["DESEMBOLSADO", "PAGADO"].includes(credit.estado)) {
        const scheduleSection = document.createElement("section");
        scheduleSection.className = "client-payment-section";
        const scheduleTitle = document.createElement("h3");
        scheduleTitle.textContent = "Plan de pagos";
        const scheduleNote = document.createElement("p");
        scheduleNote.className = "form-note";
        scheduleNote.textContent = "Fechas y saldos del plan generado al desembolsar el crédito.";
        scheduleSection.append(scheduleTitle, scheduleNote);
        const scheduleRows = (entry.cuotas || []).map((installment) => {
          const row = document.createElement("tr");
          row.append(
            cell(installment.numero_cuota),
            cell(installment.fecha_vencimiento ? new Date(installment.fecha_vencimiento).toLocaleDateString("es-CO") : "—"),
            cell(formatMoney(installment.monto_cuota)),
            cell(formatMoney(installment.monto_pagado)),
            cell(formatMoney(installment.saldo_remanente)),
            cell(installment.estado)
          );
          return row;
        });
        scheduleSection.append(table(
          ["Cuota", "Vencimiento", "Valor", "Pagado", "Saldo de capital", "Estado"],
          scheduleRows,
          "El plan de pagos aún no está disponible."
        ));
        card.append(scheduleSection);

        const paymentSection = document.createElement("section");
        paymentSection.className = "client-payment-section";
        const paymentTitle = document.createElement("h3");
        paymentTitle.textContent = "Pagos registrados";
        paymentSection.append(paymentTitle);
        const paymentRows = (entry.pagos || []).map((payment) => {
          const row = document.createElement("tr");
          row.append(
            cell(payment.fecha_pago ? new Date(payment.fecha_pago).toLocaleString("es-CO") : "—"),
            cell(formatMoney(payment.monto_pagado)),
            cell(payment.metodo_pago)
          );
          return row;
        });
        paymentSection.append(table(["Fecha", "Valor recibido", "Medio registrado"], paymentRows, "Aún no hay pagos registrados."));
        card.append(paymentSection);
      }
      list.append(card);
    });
  }

  async function loadClientPortal() {
    setMessage($("client-portal-message"), "Cargando tus créditos…", "info");
    try {
      const credits = await api("/creditos/mis");
      renderClientCredits(credits);
      setMessage(
        $("client-portal-message"),
        credits.length ? "Información de tus solicitudes actualizada." : "No tienes solicitudes de crédito registradas.",
        credits.length ? "success" : "info"
      );
    } catch (error) {
      $("client-credit-list").replaceChildren();
      const message = error.status === 403
        ? "Tu cuenta aún no está vinculada a un perfil de cliente. Comunícate con CrediFresh para completar la vinculación."
        : error.message || "No se pudieron cargar tus créditos.";
      setMessage($("client-portal-message"), message);
    }
  }

  async function assignCreditRate(event) {
    event.preventDefault();
    if (!selectedCreditDetailId) return;
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const rate = Number($("credit-rate-value").value);
    if (!Number.isFinite(rate) || rate <= 0 || rate > 100) {
      setMessage($("credit-rate-message"), "Ingresa una tasa mensual mayor que 0 y hasta 100 %.");
      return;
    }
    submit.disabled = true;
    setMessage($("credit-rate-message"), "Guardando la tasa…", "info");
    try {
      await api(`/creditos/${selectedCreditDetailId}/tasa`, {
        method: "PATCH",
        body: JSON.stringify({ tasa_interes: rate }),
      });
      await loadDashboard();
      const credit = cache.credits.find((item) => item.id === selectedCreditDetailId);
      if (credit) await showCreditDetails(credit);
      setMessage(globalMessage, "Tasa asignada. Ya puedes evaluar la solicitud.", "success");
    } catch (error) {
      setMessage($("credit-rate-message"), error.message || "No se pudo guardar la tasa.");
    } finally {
      submit.disabled = false;
    }
  }

  async function evaluateCredit(creditId, button) {
    const confirmed = window.confirm(
      "¿Ejecutar la evaluación automática? La regla decide APROBADO o RECHAZADO según la capacidad de pago. El resultado será definitivo y no se podrá repetir. Para rechazar manualmente, abre Detalle y usa la sección de rechazo con motivo."
    );
    if (!confirmed) return;

    button.disabled = true;
    setMessage(globalMessage, "Evaluando solicitud…", "info");
    try {
      const result = await api(`/creditos/${creditId}/evaluar`, { method: "POST" });
      await loadDashboard();
      const reasons = Array.isArray(result.motivos) ? result.motivos.join("; ") : "";
      setMessage(
        globalMessage,
        `Solicitud evaluada: ${result.decision}. Cuota estimada: ${formatMoney(result.cuota_mensual)}. ${reasons}`,
        result.decision === "APROBADO" ? "success" : "info"
      );
    } catch (error) {
      setMessage(globalMessage, error.message || "No se pudo evaluar la solicitud.");
      button.disabled = false;
    }
  }

  async function rejectCreditManually(event) {
    event.preventDefault();
    if (!selectedCreditDetailId) return;
    const form = event.currentTarget;
    const submit = $("credit-rejection-submit");
    const motivo = $("credit-rejection-reason").value.trim();
    if (motivo.length < 5 || motivo.length > 500) {
      setMessage($("credit-rejection-message"), "Escribe un motivo de 5 a 500 caracteres.");
      return;
    }
    const confirmed = window.confirm(
      `¿Rechazar definitivamente la solicitud #${selectedCreditDetailId}? El motivo quedará registrado en la evaluación y la auditoría. Esta decisión no se puede repetir.`
    );
    if (!confirmed) return;

    submit.disabled = true;
    setMessage($("credit-rejection-message"), "Registrando el rechazo…", "info");
    try {
      const result = await api(`/creditos/${selectedCreditDetailId}/rechazar`, {
        method: "POST",
        body: JSON.stringify({ motivo }),
      });
      form.reset();
      await loadDashboard();
      const credit = cache.credits.find((item) => item.id === selectedCreditDetailId);
      if (credit) await showCreditDetails(credit);
      setMessage(globalMessage, result.mensaje, "success");
    } catch (error) {
      setMessage($("credit-rejection-message"), error.message || "No se pudo registrar el rechazo.");
    } finally {
      submit.disabled = false;
    }
  }

  async function loadDashboard() {
    document.body.classList.add("loading");
    setMessage(globalMessage, "Actualizando información…");
    const results = await Promise.allSettled([
      api("/usuarios/"), api("/clientes/"), api("/creditos/"), api("/reportes/resumen"), api("/reportes/cartera"), api("/creditos/pendientes-desembolso"), api(`/reportes/cuotas-vencidas?limit=${OVERDUE_PAGE_SIZE}&offset=${overdueOffset}`), api("/creditos/estado-operaciones"), api("/health"),
    ]);
    document.body.classList.remove("loading");
    const failures = [];
    ["users", "clients", "credits", "summary", "portfolio", "pendingDisbursements", "overdueInstallments"].forEach((key, index) => {
      if (results[index].status === "fulfilled") cache[key] = results[index].value;
      else failures.push(results[index].reason.message);
    });
    if (results[7].status === "fulfilled") {
      cache.bankOperationsEnabled = results[7].value.operaciones_bancarias_habilitadas;
    } else {
      cache.bankOperationsEnabled = null;
      failures.push(results[7].reason.message);
    }
    pendingDisbursementLoadError = results[5].status === "rejected" ? results[5].reason.message : "";
    overdueInstallmentsLoadError = results[6].status === "rejected" ? results[6].reason.message : "";
    const apiStatusDot = $("api-status-dot");
    const apiStatusLabel = $("api-status-label");
    const apiIsHealthy = results[8].status === "fulfilled" && results[8].value.status === "healthy";
    apiStatusDot.className = `online-dot ${apiIsHealthy ? "" : "offline"}`.trim();
    apiStatusLabel.textContent = apiIsHealthy ? "API y base de datos conectadas" : "API o base de datos sin conexión";
    apiStatusLabel.title = apiIsHealthy ? "Verificación /health correcta" : "No respondió correctamente el endpoint /health";
    $("service-status-icon").className = `status-icon ${apiIsHealthy ? "" : "offline"}`.trim();
    $("service-status-icon").textContent = apiIsHealthy ? "✓" : "!";
    $("service-status-title").textContent = apiIsHealthy ? "Servicios disponibles" : "Conexión no disponible";
    $("service-status-description").textContent = apiIsHealthy
      ? "La API y la base de datos responden. Las solicitudes nuevas quedan pendientes; este panel no las aprueba ni desembolsa."
      : "No se pudo confirmar la conexión con la API y la base de datos. Actualiza los datos para volver a comprobarla.";
    $("service-status-pill").className = `status-pill ${apiIsHealthy ? "status-enabled" : "status-waiting"}`;
    $("service-status-pill").textContent = apiIsHealthy ? "Operativo" : "Sin conexión";
    if (!apiIsHealthy) failures.push("No se pudo verificar la conexión con la API y la base de datos.");
    $("metric-users").textContent = safe(cache.users.length, "0");
    $("metric-clients").textContent = safe(cache.clients.length, "0");
    $("metric-credits").textContent = safe(cache.credits.length, "0");
    const requestedAmount = cache.summary?.monto_total_solicitado
      ?? cache.credits.reduce((sum, credit) => sum + Number(credit.monto || 0), 0);
    $("metric-amount").textContent = formatMoney(requestedAmount);
    const quotaStates = cache.portfolio?.cuotas_por_estado || {};
    $("metric-accepted-undisbursed").textContent = safe(cache.summary?.creditos_aceptados_sin_desembolso, "—");
    $("metric-accepted-amount").textContent = cache.summary
      ? formatMoney(cache.summary.monto_aceptado_sin_desembolso)
      : "—";
    $("metric-pending-balance").textContent = cache.portfolio
      ? formatMoney(cache.portfolio.saldo_pendiente_cartera)
      : "—";
    $("metric-open-installments").textContent = cache.portfolio
      ? safe(Number(quotaStates.pendiente || 0) + Number(quotaStates.pago_parcial || 0))
      : "—";
    $("metric-overdue-installments").textContent = safe(cache.portfolio?.cuotas_vencidas, "—");
    $("metric-overdue-balance").textContent = `Saldo vencido: ${cache.portfolio ? formatMoney(cache.portfolio.saldo_vencido) : "—"}`;
    renderAuditUserOptions();
    renderUsers();
    renderClients();
    renderCredits();
    renderPendingDisbursements(pendingDisbursementLoadError);
    renderOverdueInstallments(overdueInstallmentsLoadError);
    renderBankOperationsStatus();
    setMessage(globalMessage, failures.length ? "Algunos datos no pudieron cargarse. Usa Actualizar datos para volver a intentarlo." : "Información actualizada.", failures.length ? "info" : "success");
  }

  function getAuditFilterParams() {
    const params = new URLSearchParams();
    const action = $("audit-action-filter").value.trim();
    const result = $("audit-result-filter").value;
    const entity = $("audit-entity-filter").value;
    const entityId = $("audit-entity-id-filter").value.trim();
    const userId = $("audit-user-filter").value.trim();
    const ip = $("audit-ip-filter").value.trim();
    const from = $("audit-from-filter").value;
    const to = $("audit-to-filter").value;
    if (action) params.set("accion", action);
    if (result) params.set("resultado", result);
    if (entity) params.set("entidad", entity);
    if (entity && entityId) params.set("entidad_id", entityId);
    if (userId) params.set("usuario_id", userId);
    if (ip) params.set("ip", ip);
    if (from) params.set("fecha_desde", `${from}T00:00:00-05:00`);
    if (to) params.set("fecha_hasta", `${to}T23:59:59.999999-05:00`);
    return params;
  }

  function syncAuditEntityIdFilter() {
    const entity = $("audit-entity-filter").value;
    const entityId = $("audit-entity-id-filter");
    entityId.disabled = !entity;
    entityId.placeholder = entity ? "ID" : "Elige tipo";
    if (!entity) entityId.value = "";
  }

  async function loadAudit(offset = 0, useCurrentControls = true) {
    if (useCurrentControls) auditAppliedFilters = getAuditFilterParams();
    const params = new URLSearchParams(auditAppliedFilters);
    params.set("limit", String(AUDIT_PAGE_SIZE));
    params.set("offset", String(offset));
    const refreshButton = $("audit-refresh-button");
    refreshButton.disabled = true;
    $("audit-export-button").disabled = true;
    $("audit-previous-button").disabled = true;
    $("audit-next-button").disabled = true;
    setMessage($("audit-message"), "Consultando eventos…", "info");
    try {
      const page = await api(`/auditoria/consulta?${params.toString()}`);
      auditRecords = page.items;
      auditTotal = page.total;
      auditOffset = page.offset;
      $("audit-export-button").disabled = auditTotal === 0;
      $("audit-count").textContent = `${auditTotal} ${auditTotal === 1 ? "evento" : "eventos"}`;
      const totalPages = Math.max(1, Math.ceil(auditTotal / AUDIT_PAGE_SIZE));
      const currentPage = Math.floor(auditOffset / AUDIT_PAGE_SIZE) + 1;
      const firstResult = auditTotal ? auditOffset + 1 : 0;
      const lastResult = Math.min(auditOffset + auditRecords.length, auditTotal);
      $("audit-page-info").textContent = `Página ${currentPage} de ${totalPages} · Mostrando ${firstResult}–${lastResult} de ${auditTotal}`;
      $("audit-previous-button").disabled = auditOffset === 0;
      $("audit-next-button").disabled = auditOffset + auditRecords.length >= auditTotal;
      const rows = auditRecords.map((log) => {
        const row = document.createElement("tr");
        const date = log.fecha_creacion ? new Intl.DateTimeFormat("es-CO", {
          dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota",
        }).format(new Date(log.fecha_creacion)) : "—";
        row.append(
          cell(date),
          cell(log.usuario_id
            ? `${cache.users.find((user) => user.id === log.usuario_id)?.email || `Usuario #${log.usuario_id}`} · ${log.rol}`
            : log.rol),
          (() => {
            const actionCell = cell(auditActionLabel(log.accion), "primary-cell");
            actionCell.title = log.accion;
            return actionCell;
          })(),
          cell(`${safe(log.entidad)}${log.entidad_id ? ` #${log.entidad_id}` : ""}`),
          cell(log.resultado),
          auditDetailsCell(log.detalles),
          cell(log.ip),
        );
        const action = document.createElement("td");
        const entityId = Number(log.entidad_id);
        const addOpenButton = (label, onClick) => {
          const openButton = document.createElement("button");
          openButton.type = "button";
          openButton.className = "table-action";
          openButton.textContent = label;
          openButton.addEventListener("click", onClick);
          action.append(openButton);
        };
        const credit = log.entidad === "credito" ? cache.credits.find((item) => item.id === entityId) : null;
        const user = log.entidad === "usuario" ? cache.users.find((item) => item.id === entityId) : null;
        const client = log.entidad === "cliente" ? cache.clients.find((item) => item.id === entityId) : null;
        if (credit) addOpenButton("Abrir crédito", () => {
          showSection("creditos");
          showCreditDetails(credit);
        });
        if (user) addOpenButton("Ver usuario", () => {
          $("user-email-search").value = user.email;
          showSection("usuarios");
          renderUsers();
        });
        if (client) addOpenButton("Ver cliente", () => {
          $("client-search-input").value = client.nombre;
          showSection("clientes");
          renderClients();
        });
        row.append(action);
        return row;
      });
      $("audit-table").replaceChildren(table(
        ["Fecha y hora", "Usuario", "Acción", "Entidad", "Resultado", "Detalles", "IP", ""],
        rows,
        "No hay eventos que coincidan con estos filtros.",
      ));
      setMessage($("audit-message"), "Consulta actualizada.", "success");
    } catch (error) {
      auditRecords = [];
      auditTotal = 0;
      $("audit-export-button").disabled = true;
      $("audit-count").textContent = "—";
      $("audit-page-info").textContent = "—";
      $("audit-table").replaceChildren();
      setMessage($("audit-message"), error.message || "No se pudo consultar la auditoría.");
    } finally {
      refreshButton.disabled = false;
    }
  }

  function showSection(name) {
    document.querySelectorAll(".page-section").forEach((section) => {
      section.hidden = section.id !== `section-${name}`;
    });
    document.querySelectorAll("[data-section-link]").forEach((link) => {
      link.classList.toggle("active", link.dataset.sectionLink === name);
      if (link.dataset.sectionLink === name) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    const titles = { inicio: "Resumen", usuarios: "Usuarios", clientes: "Clientes", creditos: "Créditos", auditoria: "Auditoría" };
    $("page-title").textContent = titles[name] || titles.inicio;
  }

  function logout(message = "") {
    accessToken = null;
    activeEmail = "";
    appView.hidden = true;
    clientView.hidden = true;
    loginView.hidden = false;
    loginForm.reset();
    setMessage(loginMessage, message);
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = loginForm.querySelector("button[type=submit]");
    submit.disabled = true;
    setMessage(loginMessage, "Validando acceso…");
    try {
      try {
        await api("/health");
      } catch (error) {
        if (error.status === 503) {
          throw new Error("La API está activa, pero la base de datos no responde. Inicia PostgreSQL y vuelve a intentar.");
        }
        throw error;
      }
      const credentials = {
        email: $("email").value.trim(),
        password: $("password").value,
      };
      const result = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify(credentials),
      });
      accessToken = result.access_token;
      const sessionUser = await api("/auth/me");
      activeEmail = sessionUser.email;
      $("password").value = "";
      loginView.hidden = true;
      if (sessionUser.rol === "CLIENTE") {
        clientView.hidden = false;
        appView.hidden = true;
        $("client-signed-in-email").textContent = activeEmail;
        await loadClientPortal();
        return;
      }
      if (sessionUser.rol !== "ADMIN") {
        throw new Error("Este portal permite iniciar sesión a cuentas ADMIN y CLIENTE.");
      }
      const userList = await api("/usuarios/");
      if (!Array.isArray(userList)) throw new Error("No se pudo validar el acceso de administrador.");
      cache.users = userList;
      $("signed-in-email").textContent = activeEmail;
      clientView.hidden = true;
      appView.hidden = false;
      showSection("inicio");
      await loadDashboard();
    } catch (error) {
      accessToken = null;
      activeEmail = "";
      loginView.hidden = false;
      clientView.hidden = true;
      appView.hidden = true;
      setMessage(loginMessage, error.message || "No se pudo iniciar sesión.");
    } finally {
      submit.disabled = false;
    }
  });

  document.querySelectorAll("[data-section-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      showSection(link.dataset.sectionLink);
      if (link.dataset.sectionLink === "auditoria") loadAudit();
    });
  });
  $("audit-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    const from = $("audit-from-filter").value;
    const to = $("audit-to-filter").value;
    if (from && to && from > to) {
      setMessage($("audit-message"), "La fecha Desde no puede ser posterior a la fecha Hasta.");
      return;
    }
    loadAudit(0);
  });
  Object.entries(AUDIT_ACTION_LABELS).forEach(([action, label]) => {
    const option = document.createElement("option");
    option.value = action;
    option.label = label;
    option.textContent = `${label} (${action})`;
    $("audit-action-options").append(option);
  });
  $("audit-refresh-button").addEventListener("click", () => loadAudit(auditOffset, false));
  $("audit-export-button").addEventListener("click", exportAuditCsv);
  $("audit-clear-button").addEventListener("click", () => {
    $("audit-filters").reset();
    syncAuditEntityIdFilter();
    loadAudit(0);
  });
  $("audit-entity-filter").addEventListener("change", syncAuditEntityIdFilter);
  $("audit-previous-button").addEventListener("click", () => loadAudit(Math.max(0, auditOffset - AUDIT_PAGE_SIZE), false));
  $("audit-next-button").addEventListener("click", () => loadAudit(auditOffset + AUDIT_PAGE_SIZE, false));
  $("logout-button").addEventListener("click", () => logout());
  $("client-logout-button").addEventListener("click", () => logout());
  $("link-client-account-button").addEventListener("click", linkClientAccount);
  $("new-user-button").addEventListener("click", () => {
    $("user-form-panel").hidden = false;
    $("user-new-email").focus();
  });
  $("cancel-user-button").addEventListener("click", () => {
    $("user-form").reset();
    setMessage($("user-form-message"), "");
    $("user-form-panel").hidden = true;
  });
  $("user-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const payload = {
      email: $("user-new-email").value.trim().toLowerCase(),
      password: $("user-new-password").value,
      rol: $("user-new-role").value,
    };
    submit.disabled = true;
    setMessage($("user-form-message"), "Creando usuario…", "info");
    try {
      await api("/usuarios/", { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      $("user-form-panel").hidden = true;
      await loadDashboard();
      setMessage(globalMessage, "Usuario creado correctamente. La cuenta quedó activa.", "success");
    } catch (error) {
      setMessage($("user-form-message"), error.message || "No se pudo crear el usuario.");
    } finally {
      submit.disabled = false;
    }
  });
  $("user-role-filter").addEventListener("change", renderUsers);
  $("user-active-filter").addEventListener("change", renderUsers);
  $("user-email-search").addEventListener("input", renderUsers);
  $("client-search-input").addEventListener("input", renderClients);
  $("credit-status-filter").addEventListener("change", renderCredits);
  $("credit-client-search").addEventListener("input", renderCredits);
  $("refresh-button").addEventListener("click", loadDashboard);
  $("pending-disbursement-search").addEventListener("input", () => renderPendingDisbursements(pendingDisbursementLoadError));
  $("pending-disbursement-export-button").addEventListener("click", exportPendingDisbursementsCsv);
  $("overdue-previous-button").addEventListener("click", () => loadOverdueInstallments(Math.max(0, overdueOffset - OVERDUE_PAGE_SIZE)));
  $("overdue-next-button").addEventListener("click", () => loadOverdueInstallments(overdueOffset + OVERDUE_PAGE_SIZE));
  $("overdue-export-button").addEventListener("click", exportOverdueInstallmentsCsv);
  $("new-client-button").addEventListener("click", () => {
    $("client-form-panel").hidden = false;
    $("client-name").focus();
  });
  $("cancel-client-button").addEventListener("click", () => {
    $("client-form").reset();
    setMessage($("client-form-message"), "");
    $("client-form-panel").hidden = true;
  });
  $("client-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.email = payload.email.trim() || null;
    submit.disabled = true;
    setMessage($("client-form-message"), "Registrando cliente…");
    try {
      await api("/clientes/", { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      setMessage($("client-form-message"), "Cliente registrado correctamente.", "success");
      await loadDashboard();
    } catch (error) {
      setMessage($("client-form-message"), error.message || "No se pudo registrar el cliente.");
    } finally {
      submit.disabled = false;
    }
  });
  $("close-profile-button").addEventListener("click", () => {
    $("client-profile-panel").hidden = true;
    $("profile-form").reset();
    $("profile-details").hidden = true;
    profileClientId = null;
    profileClient = null;
  });
  $("cancel-profile-button").addEventListener("click", () => {
    $("profile-form").reset();
    $("client-profile-panel").hidden = true;
    profileClientId = null;
    profileClient = null;
  });
  $("client-contact-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!profileClient) return;
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const payload = {
      nombre: $("contact-client-name").value.trim(),
      cedula: $("contact-client-id").value.trim(),
      telefono: $("contact-client-phone").value.trim(),
      direccion: $("contact-client-address").value.trim() || null,
      email: $("contact-client-email").value.trim() || null,
    };
    submit.disabled = true;
    setMessage($("client-contact-message"), "Guardando datos de contacto…");
    try {
      const result = await api(`/clientes/${profileClient.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      Object.assign(profileClient, result.cliente);
      const cachedClient = cache.clients.find((item) => item.id === profileClient.id);
      if (cachedClient) Object.assign(cachedClient, result.cliente);
      $("client-profile-title").textContent = `Perfil financiero · ${profileClient.nombre}`;
      renderClients();
      setMessage($("client-contact-message"), result.mensaje, "success");
    } catch (error) {
      setMessage($("client-contact-message"), error.message || "No se pudieron actualizar los datos de contacto.");
    } finally {
      submit.disabled = false;
    }
  });
  $("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const payload = {
      ingresos_mensuales: Number($("profile-income").value),
      gastos_mensuales: Number($("profile-expenses").value),
      otras_obligaciones: Number($("profile-obligations").value),
      tipo_ingresos: $("profile-income-type").value.trim(),
      actividad_economica: $("profile-activity").value.trim(),
    };
    submit.disabled = true;
    setMessage($("profile-message"), "Guardando perfil financiero…");
    try {
      const result = await api(`/clientes/${profileClientId}/perfil-financiero`, {
        method: profileExists ? "PUT" : "POST", body: JSON.stringify(payload),
      });
      profileExists = true;
      $("profile-submit-button").textContent = "Actualizar perfil";
      setMessage($("profile-message"), result.mensaje, "success");
    } catch (error) {
      setMessage($("profile-message"), error.message || "No se pudo guardar el perfil.");
    } finally {
      submit.disabled = false;
    }
  });
  $("new-credit-button").addEventListener("click", () => {
    const select = $("credit-client");
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Selecciona un cliente";
    placeholder.disabled = true;
    placeholder.selected = true;
    select.append(placeholder);
    cache.clients.forEach((client) => {
      const option = document.createElement("option");
      option.value = String(client.id);
      option.textContent = `${client.nombre} · ID ${client.id}`;
      select.append(option);
    });
    $("credit-form-panel").hidden = false;
    select.focus();
  });
  $("cancel-credit-button").addEventListener("click", () => {
    $("credit-form").reset();
    updateRateEquivalence();
    setMessage($("credit-form-message"), "");
    $("credit-form-panel").hidden = true;
  });
  $("close-credit-details-button").addEventListener("click", () => {
    $("credit-details-panel").hidden = true;
    selectedCreditDetailId = null;
    $("credit-simulation-panel").hidden = true;
    $("credit-request-details").replaceChildren();
    $("credit-evaluation-details").replaceChildren();
    $("credit-acceptance-details").replaceChildren();
  });
  $("simulate-credit-button").addEventListener("click", simulateCreditAmortization);
  $("credit-rate-form").addEventListener("submit", assignCreditRate);
  $("credit-rejection-form").addEventListener("submit", rejectCreditManually);
  $("credit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector("button[type=submit]");
    const payload = {
      cliente_id: Number($("credit-client").value),
      monto: Number($("credit-amount").value),
      plazo_meses: Number($("credit-term").value),
      tasa_interes: Number($("credit-rate").value),
    };
    submit.disabled = true;
    setMessage($("credit-form-message"), "Creando solicitud…");
    try {
      const result = await api("/creditos/", { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      updateRateEquivalence();
      setMessage($("credit-form-message"), `Solicitud creada. Estado: ${result.credito.estado}.`, "success");
      await loadDashboard();
    } catch (error) {
      setMessage($("credit-form-message"), error.message || "No se pudo crear la solicitud.");
    } finally {
      submit.disabled = false;
    }
  });
  $("credit-rate").addEventListener("input", updateRateEquivalence);
})();
