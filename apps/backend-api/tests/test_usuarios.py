"""Tests H.1 y H.2: gestión segura de usuarios, roles y ciclo de vida.

H.1: Solo ADMIN puede crear usuarios con rol ADMIN/GESTOR/CLIENTE o cambiar roles.
H.2: listado y detalle de usuarios, y baja/reactivación lógica (campo `activo`)
con protección de autodesactivación y del último ADMIN activo.
El registro público (/auth/register) sigue creando únicamente CLIENTE.
Se valida además que las contraseñas nunca se almacenan en texto plano.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.usuario import Usuario
from main import app
from conftest import override_get_db


# Sesiones abiertas por get_test_db() dentro de un test; se cierran en el
# teardown de la fixture autouse para no filtrar sesiones durante la suite.
_ACTIVE_SESSIONS: list[Session] = []


def get_test_db() -> Session:
    """Sesión sobre la BD SQLite de pruebas (misma que usa la fixture client).

    Obtiene la sesión llamando a override_get_db, el mismo override que la
    fixture client registra para get_db, importado de conftest (el módulo que
    pytest ya cargó; sin acceder a app.dependency_overrides, para no
    reproducir el KeyError).
    """
    db = next(override_get_db())
    _ACTIVE_SESSIONS.append(db)
    return db


@pytest.fixture(autouse=True)
def clean_auth_overrides():
    """Remueve los bypass de auth del conftest para probar autorización real."""
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.get(get_current_user)
    old_active_user = app.dependency_overrides.get(get_current_active_user)

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)

    yield

    if old_current_user:
        app.dependency_overrides[get_current_user] = old_current_user
    if old_active_user:
        app.dependency_overrides[get_current_active_user] = old_active_user

    # Cierre de sesiones: garantiza que ninguna sesión SQLite quede abierta
    # entre tests de la suite completa.
    for db in _ACTIVE_SESSIONS:
        db.close()
    _ACTIVE_SESSIONS.clear()


def ensure_user(email: str, password: str, rol: str) -> Usuario:
    """Crea (de forma idempotente) un usuario de prueba en la BD SQLite."""
    db = get_test_db()
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        usuario = Usuario(
            email=email,
            password_hash=get_password_hash(password),
            rol=rol,
            activo=True,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
    return usuario


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def admin_token(client: TestClient) -> str:
    ensure_user("admin_h1@credifresh.com", "PruebaSegura123", "ADMIN")
    return login(client, "admin_h1@credifresh.com", "PruebaSegura123")


# ---------------------------------------------------------------------------
# 1 y 2. ADMIN puede crear GESTOR y ADMIN
# ---------------------------------------------------------------------------

def test_admin_puede_crear_gestor(client: TestClient):
    """1. Un ADMIN crea un usuario con rol GESTOR."""
    token = admin_token(client)
    response = client.post("/usuarios/", json={
        "email": "gestor_nuevo_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    }, headers=auth_headers(token))
    assert response.status_code == 201
    data = response.json()
    assert data["rol"] == "GESTOR"
    assert data["activo"] is True


def test_admin_puede_crear_admin(client: TestClient):
    """2. Un ADMIN crea otro usuario con rol ADMIN."""
    token = admin_token(client)
    response = client.post("/usuarios/", json={
        "email": "admin_nuevo_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "ADMIN",
    }, headers=auth_headers(token))
    assert response.status_code == 201
    data = response.json()
    assert data["rol"] == "ADMIN"
    assert data["activo"] is True


# ---------------------------------------------------------------------------
# 3 y 4. GESTOR no puede crear ni promover
# ---------------------------------------------------------------------------

def test_gestor_no_puede_crear_usuario(client: TestClient):
    """3. Un GESTOR recibe 403 al crear usuarios."""
    ensure_user("gestor_bloqueo_h1@credifresh.com", "PruebaSegura123", "GESTOR")
    token = login(client, "gestor_bloqueo_h1@credifresh.com", "PruebaSegura123")
    response = client.post("/usuarios/", json={
        "email": "intento_gestor_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    }, headers=auth_headers(token))
    assert response.status_code == 403


def test_gestor_no_puede_promover_a_admin(client: TestClient):
    """4. Un GESTOR recibe 403 al promover a otro usuario a ADMIN."""
    objetivo = ensure_user("objetivo_promocion_h1@credifresh.com", "PruebaSegura123", "CLIENTE")
    ensure_user("gestor_promocion_h1@credifresh.com", "PruebaSegura123", "GESTOR")
    token = login(client, "gestor_promocion_h1@credifresh.com", "PruebaSegura123")
    response = client.patch(f"/usuarios/{objetivo.id}/rol", json={
        "rol": "ADMIN",
    }, headers=auth_headers(token))
    assert response.status_code == 403

    # El rol del usuario objetivo no cambió
    db = get_test_db()
    objetivo_bd = db.query(Usuario).filter(Usuario.id == objetivo.id).first()
    assert objetivo_bd.rol == "CLIENTE"


# ---------------------------------------------------------------------------
# 5. CLIENTE no puede crear ni promover
# ---------------------------------------------------------------------------

def test_cliente_no_puede_crear_ni_promover(client: TestClient):
    """5. Un CLIENTE recibe 403 en POST y PATCH de gestión de usuarios."""
    objetivo = ensure_user("objetivo_cliente_h1@credifresh.com", "PruebaSegura123", "CLIENTE")
    ensure_user("cliente_bloqueo_h1@credifresh.com", "PruebaSegura123", "CLIENTE")
    token = login(client, "cliente_bloqueo_h1@credifresh.com", "PruebaSegura123")
    headers = auth_headers(token)

    response_post = client.post("/usuarios/", json={
        "email": "intento_cliente_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    }, headers=headers)
    assert response_post.status_code == 403

    response_patch = client.patch(f"/usuarios/{objetivo.id}/rol", json={
        "rol": "ADMIN",
    }, headers=headers)
    assert response_patch.status_code == 403


# ---------------------------------------------------------------------------
# 6. Sin token recibe 403 según HTTPBearer
# ---------------------------------------------------------------------------

def test_sin_token_recibe_403(client: TestClient):
    """6. Los endpoints de gestión exigen autenticación (403 sin token)."""
    response_post = client.post("/usuarios/", json={
        "email": "sin_token_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    })
    assert response_post.status_code == 403

    response_patch = client.patch("/usuarios/1/rol", json={"rol": "ADMIN"})
    assert response_patch.status_code == 403


# ---------------------------------------------------------------------------
# 7. Un usuario no puede elevar su propio rol
# ---------------------------------------------------------------------------

def test_usuario_no_puede_elevar_su_propio_rol(client: TestClient):
    """7. Un GESTOR intenta promoverse a sí mismo y recibe 403."""
    gestor = ensure_user("gestor_self_h1@credifresh.com", "PruebaSegura123", "GESTOR")
    token = login(client, "gestor_self_h1@credifresh.com", "PruebaSegura123")
    response = client.patch(f"/usuarios/{gestor.id}/rol", json={
        "rol": "ADMIN",
    }, headers=auth_headers(token))
    assert response.status_code == 403

    db = get_test_db()
    gestor_bd = db.query(Usuario).filter(Usuario.id == gestor.id).first()
    assert gestor_bd.rol == "GESTOR"


# ---------------------------------------------------------------------------
# 8. /auth/register continúa creando CLIENTE
# ---------------------------------------------------------------------------

def test_register_sigue_creando_clientes(client: TestClient):
    """8. /auth/register acepta el campo rol en el body pero SIEMPRE crea CLIENTE."""
    response = client.post("/auth/register", json={
        "email": "registro_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "ADMIN",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["rol"] == "CLIENTE"

    # Verificación adicional: en la BD también quedó como CLIENTE
    db = get_test_db()
    usuario_bd = (
        db.query(Usuario)
        .filter(Usuario.email == "registro_h1@credifresh.com")
        .first()
    )
    assert usuario_bd is not None
    assert usuario_bd.rol == "CLIENTE"


# ---------------------------------------------------------------------------
# 9. Las contraseñas nunca están en texto plano
# ---------------------------------------------------------------------------

def test_passwords_nunca_en_texto_plano(client: TestClient):
    """9. La contraseña se almacena con hash bcrypt y nunca viaja en la respuesta."""
    token = admin_token(client)
    response = client.post("/usuarios/", json={
        "email": "hash_check_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    }, headers=auth_headers(token))
    assert response.status_code == 201

    data = response.json()
    assert "password" not in data
    assert "password_hash" not in data

    db = get_test_db()
    usuario_bd = (
        db.query(Usuario)
        .filter(Usuario.email == "hash_check_h1@credifresh.com")
        .first()
    )
    assert usuario_bd is not None
    assert usuario_bd.password_hash != "PruebaSegura123"
    assert usuario_bd.password_hash.startswith("$2")
    assert "PruebaSegura123" not in usuario_bd.password_hash
    assert verify_password("PruebaSegura123", usuario_bd.password_hash) is True


# ---------------------------------------------------------------------------
# 10. Rol inválido recibe 422
# ---------------------------------------------------------------------------

def test_rol_invalido_rechazado(client: TestClient):
    """10. Un rol fuera de la whitelist ADMIN/GESTOR/CLIENTE es rechazado (422)."""
    token = admin_token(client)
    response = client.post("/usuarios/", json={
        "email": "rol_invalido_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "SUPERUSER",
    }, headers=auth_headers(token))
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 11. Email duplicado recibe 409
# ---------------------------------------------------------------------------

def test_email_duplicado_conflict(client: TestClient):
    """11. Crear dos veces el mismo email devuelve 409."""
    token = admin_token(client)
    payload = {
        "email": "duplicado_h1@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "GESTOR",
    }
    response_primera = client.post("/usuarios/", json=payload, headers=auth_headers(token))
    assert response_primera.status_code == 201

    response_segunda = client.post("/usuarios/", json=payload, headers=auth_headers(token))
    assert response_segunda.status_code == 409


# ---------------------------------------------------------------------------
# H.2 — 12. GET /usuarios/ solo ADMIN
# ---------------------------------------------------------------------------

def test_listado_usuarios_solo_admin(client: TestClient):
    """12. GET /usuarios/ exige ADMIN: 403 para GESTOR/CLIENTE y sin token."""
    ensure_user("gestor_listado_h2@credifresh.com", "PruebaSegura123", "GESTOR")
    ensure_user("cliente_listado_h2@credifresh.com", "PruebaSegura123", "CLIENTE")

    token_gestor = login(client, "gestor_listado_h2@credifresh.com", "PruebaSegura123")
    response_gestor = client.get("/usuarios/", headers=auth_headers(token_gestor))
    assert response_gestor.status_code == 403

    token_cliente = login(client, "cliente_listado_h2@credifresh.com", "PruebaSegura123")
    response_cliente = client.get("/usuarios/", headers=auth_headers(token_cliente))
    assert response_cliente.status_code == 403

    response_sin_token = client.get("/usuarios/")
    assert response_sin_token.status_code == 403


# ---------------------------------------------------------------------------
# H.2 — 13. El listado nunca expone hashes ni contraseñas
# ---------------------------------------------------------------------------

def test_listado_no_expone_hashes(client: TestClient):
    """13. GET /usuarios/ solo devuelve id, email, rol y activo."""
    token = admin_token(client)
    response = client.get("/usuarios/", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) > 0
    for usuario in response.json():
        assert set(usuario.keys()) == {"id", "email", "rol", "activo"}
        assert "password_hash" not in usuario
        assert "password" not in usuario


# ---------------------------------------------------------------------------
# H.2 — 14. Filtros ?rol= y ?activo=
# ---------------------------------------------------------------------------

def test_listado_filtros_rol_y_activo(client: TestClient):
    """14. Los filtros acotan el listado; un rol fuera de la whitelist da 422."""
    token = admin_token(client)
    ensure_user("gestor_filtro_h2@credifresh.com", "PruebaSegura123", "GESTOR")
    ensure_user("cliente_filtro_h2@credifresh.com", "PruebaSegura123", "CLIENTE")

    response_rol = client.get("/usuarios/?rol=GESTOR", headers=auth_headers(token))
    assert response_rol.status_code == 200
    emails = [usuario["email"] for usuario in response_rol.json()]
    assert "gestor_filtro_h2@credifresh.com" in emails
    assert "cliente_filtro_h2@credifresh.com" not in emails

    # Damos de baja el gestor directamente en BD para probar ?activo=false
    db = get_test_db()
    try:
        gestor = (
            db.query(Usuario)
            .filter(Usuario.email == "gestor_filtro_h2@credifresh.com")
            .first()
        )
        assert gestor is not None
        gestor.activo = False
        db.commit()
    finally:
        db.close()

    response_inactivos = client.get("/usuarios/?activo=false", headers=auth_headers(token))
    assert response_inactivos.status_code == 200
    emails_inactivos = [usuario["email"] for usuario in response_inactivos.json()]
    assert "gestor_filtro_h2@credifresh.com" in emails_inactivos
    assert "cliente_filtro_h2@credifresh.com" not in emails_inactivos

    response_rol_invalido = client.get("/usuarios/?rol=SUPERUSER", headers=auth_headers(token))
    assert response_rol_invalido.status_code == 422


# ---------------------------------------------------------------------------
# H.2 — 15. GET /usuarios/{id}
# ---------------------------------------------------------------------------

def test_detalle_usuario(client: TestClient):
    """15. Detalle por id: 200 con datos saneados o 404 si no existe."""
    token = admin_token(client)
    objetivo = ensure_user("detalle_h2@credifresh.com", "PruebaSegura123", "CLIENTE")

    response = client.get(f"/usuarios/{objetivo.id}", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == objetivo.id
    assert data["email"] == "detalle_h2@credifresh.com"
    assert data["rol"] == "CLIENTE"
    assert data["activo"] is True
    assert "password_hash" not in data

    response_404 = client.get("/usuarios/99999999", headers=auth_headers(token))
    assert response_404.status_code == 404


# ---------------------------------------------------------------------------
# H.2 — 16. La baja bloquea login y token vigente
# ---------------------------------------------------------------------------

def test_desactivar_usuario_bloquea_acceso(client: TestClient):
    """16. Tras la baja: el token previo da 400 y el login también."""
    token_admin = admin_token(client)
    ensure_user("baja_h2@credifresh.com", "PruebaSegura123", "GESTOR")
    token_baja = login(client, "baja_h2@credifresh.com", "PruebaSegura123")

    db = get_test_db()
    usuario_id = (
        db.query(Usuario)
        .filter(Usuario.email == "baja_h2@credifresh.com")
        .first()
        .id
    )

    response = client.patch(
        f"/usuarios/{usuario_id}/activo",
        json={"activo": False},
        headers=auth_headers(token_admin),
    )
    assert response.status_code == 200
    assert response.json()["activo"] is False

    # El token emitido antes de la baja deja de servir (usuario inactivo)
    response_token = client.get("/usuarios/", headers=auth_headers(token_baja))
    assert response_token.status_code == 400

    # El login directo también queda bloqueado
    response_login = client.post(
        "/auth/login",
        json={"email": "baja_h2@credifresh.com", "password": "PruebaSegura123"},
    )
    assert response_login.status_code == 400
    assert response_login.json()["detail"] == "El usuario está inactivo"


# ---------------------------------------------------------------------------
# H.2 — 17. La reactivación restaura el acceso
# ---------------------------------------------------------------------------

def test_reactivar_usuario_restaura_acceso(client: TestClient):
    """17. Tras reactivar, el login vuelve a responder 200 con token."""
    token_admin = admin_token(client)
    ensure_user("reactiva_h2@credifresh.com", "PruebaSegura123", "GESTOR")

    db = get_test_db()
    usuario_id = (
        db.query(Usuario)
        .filter(Usuario.email == "reactiva_h2@credifresh.com")
        .first()
        .id
    )

    response_baja = client.patch(
        f"/usuarios/{usuario_id}/activo",
        json={"activo": False},
        headers=auth_headers(token_admin),
    )
    assert response_baja.status_code == 200
    assert response_baja.json()["activo"] is False

    response_alta = client.patch(
        f"/usuarios/{usuario_id}/activo",
        json={"activo": True},
        headers=auth_headers(token_admin),
    )
    assert response_alta.status_code == 200
    assert response_alta.json()["activo"] is True

    token = login(client, "reactiva_h2@credifresh.com", "PruebaSegura123")
    assert isinstance(token, str) and len(token) > 0


# ---------------------------------------------------------------------------
# H.2 — 18. La baja es lógica (nunca borra la fila ni el hash)
# ---------------------------------------------------------------------------

def test_desactivacion_es_logica(client: TestClient):
    """18. Tras la baja el usuario sigue en BD con su hash intacto."""
    token_admin = admin_token(client)
    ensure_user("logica_h2@credifresh.com", "PruebaSegura123", "CLIENTE")

    db = get_test_db()
    usuario_id = (
        db.query(Usuario)
        .filter(Usuario.email == "logica_h2@credifresh.com")
        .first()
        .id
    )

    response = client.patch(
        f"/usuarios/{usuario_id}/activo",
        json={"activo": False},
        headers=auth_headers(token_admin),
    )
    assert response.status_code == 200

    # Sesión nueva: la anterior tendría la fila en su identity map con el
    # estado antiguo (activo=True) y daría un falso negativo.
    db2 = get_test_db()
    usuario_bd = (
        db2.query(Usuario)
        .filter(Usuario.email == "logica_h2@credifresh.com")
        .first()
    )
    assert usuario_bd is not None
    assert usuario_bd.activo is False
    assert usuario_bd.password_hash != "PruebaSegura123"
    assert verify_password("PruebaSegura123", usuario_bd.password_hash) is True


# ---------------------------------------------------------------------------
# H.2 — 19. Un ADMIN no puede desactivarse a sí mismo
# ---------------------------------------------------------------------------

def test_admin_no_puede_desactivarse_a_si_mismo(client: TestClient):
    """19. 409 si el ADMIN aplica la baja sobre su propia cuenta."""
    token = admin_token(client)  # admin_h1@credifresh.com
    ensure_user("admin_companero_h2@credifresh.com", "PruebaSegura123", "ADMIN")

    db = get_test_db()
    admin_propio = (
        db.query(Usuario)
        .filter(Usuario.email == "admin_h1@credifresh.com")
        .first()
    )

    response = client.patch(
        f"/usuarios/{admin_propio.id}/activo",
        json={"activo": False},
        headers=auth_headers(token),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "No puede desactivar su propia cuenta"

    response_detalle = client.get(f"/usuarios/{admin_propio.id}", headers=auth_headers(token))
    assert response_detalle.json()["activo"] is True


# ---------------------------------------------------------------------------
# H.2 — 20. No se puede dejar la aplicación sin ADMIN activo
# ---------------------------------------------------------------------------

def test_no_se_puede_desactivar_ultimo_admin(client: TestClient):
    """20. 409 al bajar al único ADMIN activo; sí se permite bajar a otro ADMIN."""
    token = admin_token(client)  # admin_h1@credifresh.com
    otro_admin = ensure_user("admin_ultimo_h2@credifresh.com", "PruebaSegura123", "ADMIN")

    # Bajar a otro ADMIN está permitido mientras el solicitante siga activo
    response_otro = client.patch(
        f"/usuarios/{otro_admin.id}/activo",
        json={"activo": False},
        headers=auth_headers(token),
    )
    assert response_otro.status_code == 200

    # Aislamos a admin_h1 como único ADMIN activo y restauramos después para
    # no contaminar al resto de la suite (incluido el bypass del conftest).
    db = get_test_db()
    admin_propio = (
        db.query(Usuario)
        .filter(Usuario.email == "admin_h1@credifresh.com")
        .first()
    )
    otros_admines = (
        db.query(Usuario)
        .filter(
            Usuario.rol == "ADMIN",
            Usuario.activo.is_(True),
            Usuario.email != "admin_h1@credifresh.com",
        )
        .all()
    )
    try:
        for admin in otros_admines:
            admin.activo = False
        db.commit()

        response_ultimo = client.patch(
            f"/usuarios/{admin_propio.id}/activo",
            json={"activo": False},
            headers=auth_headers(token),
        )
        assert response_ultimo.status_code == 409
        assert response_ultimo.json()["detail"] == "No se puede desactivar al último ADMIN activo"
    finally:
        for admin in otros_admines:
            admin.activo = True
        db.commit()

    response_detalle = client.get(f"/usuarios/{admin_propio.id}", headers=auth_headers(token))
    assert response_detalle.json()["activo"] is True


# ---------------------------------------------------------------------------
# H.2 — 21. PATCH /usuarios/{id}/activo: 404 y 422
# ---------------------------------------------------------------------------

def test_activado_casos_borde(client: TestClient):
    """21. 404 para usuario inexistente y 422 para body inválido."""
    token = admin_token(client)

    response_404 = client.patch(
        "/usuarios/99999999/activo",
        json={"activo": False},
        headers=auth_headers(token),
    )
    assert response_404.status_code == 404

    response_sin_campo = client.patch(
        "/usuarios/1/activo",
        json={},
        headers=auth_headers(token),
    )
    assert response_sin_campo.status_code == 422

    response_tipo_invalido = client.patch(
        "/usuarios/1/activo",
        json={"activo": "si"},
        headers=auth_headers(token),
    )
    assert response_tipo_invalido.status_code == 422


