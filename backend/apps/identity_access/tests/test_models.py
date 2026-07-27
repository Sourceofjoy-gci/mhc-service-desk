from apps.identity_access.models import AuditLogin, Role, User, UserRole


def test_user_role_string_identifies_user_and_role():
    user = User(username="alice", display_name="Alice Analyst")
    role = Role(name="Queue Manager")

    assignment = UserRole(user=user, role=role)

    assert str(assignment) == "Alice Analyst: Queue Manager"


def test_audit_login_string_identifies_subject_and_outcome():
    login = AuditLogin(keycloak_subject="keycloak-subject-123", success=False)

    assert str(login) == "keycloak-subject-123: failure"
