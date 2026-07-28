from dataclasses import replace

from scripts import permission_audit


def test_walk_views_recursively_enumerates_required_api_routes():
    """Catch reverting to reverse-dictionary inspection, which finds no API views."""
    routes = list(permission_audit._walk_views())
    paths = {route.path for route in routes}

    assert "api/v1/tickets/<number>/work-state/" in paths
    assert "api/v1/tickets/<number>/assignees/" in paths
    assert "api/v1/tickets/<number>/transition/" in paths
    assert "api/v1/tickets/<number>/activity/" in paths
    assert "api/v1/tickets/<ticket_number>/attachments/" in paths
    assert "api/v1/attachments/<attachment_id>/download/" in paths
    assert "api/v1/reports/tickets.csv" in paths


def test_walk_views_reports_effective_viewset_action_permissions():
    """Catch losing action metadata or an action-level permission override."""
    routes = list(permission_audit._walk_views())

    work_state = [
        route
        for route in routes
        if route.path == "api/v1/tickets/<number>/work-state/"
        and getattr(route, "method", None) == "PATCH"
        and getattr(route, "action", None) == "work_state"
    ]

    assert len(work_state) == 1
    assert work_state[0].permission_classes == (
        "IsAuthenticated",
        "ScopePermission",
    )
    assert "KeycloakJWTAuthentication" in work_state[0].authentication_classes


def test_walk_views_reports_function_wrapper_methods_and_permissions():
    """Catch excluding DRF's @api_view wrappers from the authoritative report."""
    routes = list(permission_audit._walk_views())
    attachment_methods = {
        getattr(route, "method", None)
        for route in routes
        if route.path == "api/v1/tickets/<ticket_number>/attachments/"
    }
    reporting = [route for route in routes if route.path.startswith("api/v1/reports/")]

    assert attachment_methods == {"GET", "POST"}
    assert reporting
    assert all(
        route.permission_classes == ("IsAuthenticated", "ScopePermission")
        for route in reporting
    )


def test_walk_views_marks_allow_any_routes_public():
    """Catch public metadata being lost by DRF's generated WrappedAPIView class."""
    public_intake = [
        route
        for route in permission_audit._walk_views()
        if route.path == "api/v1/tickets/public/intake/"
        and getattr(route, "method", None) == "POST"
    ]

    assert len(public_intake) == 1
    assert public_intake[0].is_public is True
    assert public_intake[0].permission_classes == ("AllowAny",)


def test_main_fails_closed_when_no_api_routes_are_found(monkeypatch, capsys):
    """Catch a broken enumerator turning zero coverage into a successful audit."""
    monkeypatch.setattr(permission_audit, "_walk_views", lambda: iter(()))

    result = permission_audit.main()

    assert result == 1
    assert "ERROR: no API views found" in capsys.readouterr().out


def test_main_fails_when_a_required_route_family_is_missing(monkeypatch, capsys):
    """Catch a route family disappearing while the rest of the audit still runs."""
    routes = [
        route
        for route in permission_audit._walk_views()
        if not route.path.startswith("api/v1/reports/")
    ]
    monkeypatch.setattr(permission_audit, "_walk_views", lambda: iter(routes))

    result = permission_audit.main()

    output = capsys.readouterr().out
    assert result == 1
    assert "ERROR: missing required reporting routes" in output
    assert "GET api/v1/reports/tickets.csv" in output


def test_main_reports_actions_and_authentication_deterministically(capsys):
    """Catch nondeterministic output or reports that omit effective route metadata."""
    assert permission_audit.main() == 0
    first = capsys.readouterr().out

    assert permission_audit.main() == 0
    second = capsys.readouterr().out

    assert first == second
    assert "PATCH work_state api/v1/tickets/<number>/work-state/" in first
    assert "AUTH=KeycloakJWTAuthentication" in first
    assert "PERMISSIONS=IsAuthenticated, ScopePermission" in first
    assert "POST tickets-public-intake api/v1/tickets/public/intake/" in first
    assert "ACCESS=PUBLIC" in first
    assert "audit passed:" in first


def test_main_deduplicates_repeated_normalized_router_actions(capsys):
    """Catch repeated DefaultRouter roots inflating the authoritative action count."""
    raw_routes = list(permission_audit._walk_views())
    raw_identities = [
        (route.path, route.method, route.action)
        for route in raw_routes
    ]
    unique_identities = set(raw_identities)
    assert raw_identities.count(("api/v1/", "GET", "api-root")) > 1

    assert permission_audit.main() == 0

    output = capsys.readouterr().out
    api_root = "GET api-root api/v1/ |"

    assert output.count(api_root) == 1
    assert (
        f"audit passed: {len(unique_identities)} route actions across "
        f"{len({path for path, _method, _action in unique_identities})} API paths"
    ) in output


def test_main_fails_closed_on_conflicting_duplicate_metadata(monkeypatch, capsys):
    """Catch deduplication silently choosing one security policy for a route action."""
    routes = list(permission_audit._walk_views())
    api_root = next(
        route
        for route in routes
        if (route.path, route.method, route.action) == ("api/v1/", "GET", "api-root")
    )
    routes.append(
        replace(
            api_root,
            permission_classes=("AllowAny",),
            is_public=True,
        )
    )
    monkeypatch.setattr(permission_audit, "_walk_views", lambda: iter(routes))

    first_result = permission_audit.main()
    first_output = capsys.readouterr().out

    second_result = permission_audit.main()
    second_output = capsys.readouterr().out

    assert first_result == second_result == 1
    assert first_output == second_output
    conflict = "ERROR: conflicting metadata for GET api-root api/v1/"
    assert conflict in first_output
    conflict_details = first_output.split(conflict, 1)[1]
    assert (
        "  AUTH=KeycloakJWTAuthentication, JWTAuthentication "
        "| PERMISSIONS=AllowAny | ACCESS=PUBLIC"
    ) in conflict_details
    assert (
        "  AUTH=KeycloakJWTAuthentication, JWTAuthentication "
        "| PERMISSIONS=IsAuthenticated | ACCESS=any auth"
    ) in conflict_details
