//! Contract tests for the Rust API surface.
//!
//! These exercise the real router (`build_router`) over an isolated temp
//! database, so they fail if a route, capability check, or engine regresses.

use std::sync::Arc;
use std::sync::OnceLock;

use axum::body::Body;
use axum::http::{Method, Request, StatusCode, header};
use axum::Router;
use http_body_util::BodyExt;
use rand::RngCore;
use serde_json::{Value, json};
use tower::ServiceExt;

use crate::db::Db;
use crate::AppState;

fn random_test_secret() -> String {
    let mut bytes = [0_u8; 32];
    let mut rng = rand::rngs::OsRng;
    rng.fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn setup_env() {
    static INIT: OnceLock<()> = OnceLock::new();
    INIT.get_or_init(|| {
        // Use OS-backed random test keys; never commit reusable signing material.
        let jwt_secret = random_test_secret();
        let sharing_secret = random_test_secret();
        // SAFETY: called once, before any test issues requests.
        unsafe {
            std::env::set_var("DATAOS_JWT_SECRET", jwt_secret);
            std::env::set_var("DATAOS_SHARING_TOKEN_SECRET", sharing_secret);
            std::env::remove_var("DATAOS_ENV");
            std::env::remove_var("DATAOS_API_TOKEN");
        }
    });
}

fn test_app() -> (Router, Arc<Db>) {
    setup_env();
    let path = std::env::temp_dir().join(format!("dataos-rust-test-{}.db", uuid::Uuid::new_v4()));
    let db = Db::open(path.to_str().expect("temp path is valid")).expect("open test database");
    let db = Arc::new(db);
    (crate::build_router(AppState { db: db.clone() }), db)
}

async fn call(
    app: &Router,
    method: Method,
    uri: &str,
    body: Option<Value>,
    token: Option<&str>,
) -> (StatusCode, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    if let Some(token) = token {
        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
    }
    let request = match body {
        Some(value) => builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(serde_json::to_vec(&value).expect("serialisable body")))
            .expect("request"),
        None => builder.body(Body::empty()).expect("request"),
    };

    let response = app.clone().oneshot(request).await.expect("router response");
    let status = response.status();
    let bytes = response
        .into_body()
        .collect()
        .await
        .expect("body")
        .to_bytes();
    let parsed = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).to_string()))
    };
    (status, parsed)
}

async fn call_with_cookie(
    app: &Router,
    method: Method,
    uri: &str,
    body: Option<Value>,
    cookie: Option<&str>,
) -> (StatusCode, Value, Option<String>) {
    let mut builder = Request::builder().method(method).uri(uri);
    if let Some(cookie) = cookie {
        builder = builder.header(header::COOKIE, cookie);
    }
    let request = match body {
        Some(value) => builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(serde_json::to_vec(&value).expect("serialisable body")))
            .expect("request"),
        None => builder.body(Body::empty()).expect("request"),
    };
    let response = app.clone().oneshot(request).await.expect("router response");
    let status = response.status();
    let set_cookie = response.headers().get(header::SET_COOKIE)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let bytes = response.into_body().collect().await.expect("body").to_bytes();
    let parsed = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).to_string()))
    };
    (status, parsed, set_cookie)
}

async fn register(_app: &Router, db: &Db, role: &str) -> String {
    let username = format!("user_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let password = random_test_secret();
    let user = db
        .user_register(
            &username,
            &format!("{username}@example.com"),
            &password,
            role,
        )
        .expect("create test user directly in isolated test database");
    crate::auth::issue_token(&user.id, &user.role).expect("issue test JWT")
}

async fn create_dataset(app: &Router, token: &str, raw_csv: &str) -> String {
    let (status, body) = call(
        app,
        Method::POST,
        "/api/objects/",
        Some(json!({
            "type": "dataset",
            "properties": {"filename": "demo.csv", "raw_csv": raw_csv},
            "content": {},
            "source": "test://fixture"
        })),
        Some(token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "create dataset failed: {body}");
    body["id"].as_str().expect("object id").to_string()
}

const SAMPLE_CSV: &str = "id,name,score\n1,alpha,10\n2,beta,20\n";

// ---------------------------------------------------------------------------

#[tokio::test]
async fn health_reports_operational() {
    let (app, _db) = test_app();
    let (status, body) = call(&app, Method::GET, "/health", None, None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "operational");
    assert_eq!(body["storage_backend"], "RustObjectsSqlite");
}

#[tokio::test]
async fn auth_roundtrip_issue_me_and_capability_gate() {
    let (app, _db) = test_app();
    let viewer = register(&app, &_db, "viewer").await;

    let (status, body) = call(&app, Method::GET, "/api/auth/me", None, Some(&viewer)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["authenticated"], true);
    assert_eq!(body["user"]["role"], "viewer");

    // viewers must not create objects
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {}, "content": {}})),
        Some(&viewer),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "expected 403, got {body}");

    // operators may
    let operator = register(&app, &_db, "operator").await;
    let (status, _) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {}, "content": {}})),
        Some(&operator),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}


#[tokio::test]
async fn http_only_cookie_session_supports_me_and_logout() {
    let (app, db) = test_app();
    let username = format!("cookie_user_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let password = random_test_secret();
    let user = db.user_register(
        &username,
        &format!("{username}@example.com"),
        &password,
        "viewer",
    ).expect("create cookie-session user");

    let (status, body, set_cookie) = call_with_cookie(
        &app,
        Method::POST,
        "/api/auth/login",
        Some(json!({"login": user.email, "password": password})),
        None,
    ).await;
    assert_eq!(status, StatusCode::OK, "login failed: {body}");
    let set_cookie = set_cookie.expect("login must issue a session cookie");
    assert!(set_cookie.contains("HttpOnly"));
    assert!(set_cookie.contains("SameSite=Strict"));
    assert!(set_cookie.contains("Path=/"));
    assert!(set_cookie.contains("Max-Age=3600"));
    let cookie_pair = set_cookie.split(';').next().expect("cookie pair").to_string();

    let (status, body, _) = call_with_cookie(
        &app,
        Method::GET,
        "/api/auth/me",
        None,
        Some(&cookie_pair),
    ).await;
    assert_eq!(status, StatusCode::OK, "cookie authentication failed: {body}");
    assert_eq!(body["authenticated"], true);
    assert_eq!(body["user"]["id"], user.id);

    let (status, _, cleared_cookie) = call_with_cookie(
        &app,
        Method::POST,
        "/api/auth/logout",
        None,
        Some(&cookie_pair),
    ).await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let cleared_cookie = cleared_cookie.expect("logout must clear the session cookie");
    assert!(cleared_cookie.contains("HttpOnly"));
    assert!(cleared_cookie.contains("SameSite=Strict"));
    assert!(cleared_cookie.contains("Path=/"));
    assert!(cleared_cookie.contains("Max-Age=0"));
}

#[tokio::test]
async fn object_ownership_isolation_blocks_cross_user_reads_writes_and_relationships() {
    let (app, db) = test_app();
    let alice = register(&app, &db, "operator").await;
    let bob = register(&app, &db, "operator").await;

    let alice_object = create_dataset(&app, &alice, SAMPLE_CSV).await;
    let bob_object = create_dataset(&app, &bob, SAMPLE_CSV).await;

    let alice_id = crate::auth::decode_token(&alice).expect("valid Alice JWT").sub;
    let (status, _) = call(&app, Method::GET, &format!("/api/governance/quota/{alice_id}"), None, Some(&bob)).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "users must not inspect another principal's quota");

    // Each principal sees only their own objects in collection responses.
    let (status, alice_list) = call(&app, Method::GET, "/api/objects/", None, Some(&alice)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(alice_list["total"], 1);
    assert_eq!(alice_list["objects"][0]["id"], alice_object);

    let (status, bob_list) = call(&app, Method::GET, "/api/objects/", None, Some(&bob)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(bob_list["total"], 1);
    assert_eq!(bob_list["objects"][0]["id"], bob_object);

    // Direct reads and deletes conceal foreign objects as not found.
    let (status, _) = call(&app, Method::GET, &format!("/api/objects/{alice_object}"), None, Some(&bob)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    // Alternate object-addressed routes use the same ownership check.
    let (status, _) = call(&app, Method::GET, &format!("/api/graph/neighbors/{alice_object}"), None, Some(&bob)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    // Development/test mode keeps existing aggregate behavior; production
    // middleware denies these unscoped views to non-admin principals.
    let (status, _) = call(&app, Method::GET, "/api/catalog/health", None, Some(&bob)).await;
    assert_eq!(status, StatusCode::OK);

    let (status, _) = call(&app, Method::DELETE, &format!("/api/objects/{alice_object}"), None, Some(&bob)).await;
    // Operators cannot delete objects at all; the capability gate rejects this
    // before the resource-level ownership check.
    assert_eq!(status, StatusCode::FORBIDDEN);

    // A user cannot connect their own object to another user's object.
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({
            "source_id": bob_object,
            "target_id": alice_object,
            "relation_type": "references"
        })),
        Some(&bob),
    ).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "cross-user relationship unexpectedly succeeded: {body}");

    // Simulate legacy/admin-created cross-tenant edges. Object-scoped graph
    // routes must not disclose the other endpoint even when an edge exists.
    db.create_relationship(&alice_object, &bob_object, "derived_from", 1.0, json!({}))
        .expect("create legacy outgoing edge");
    db.create_relationship(&bob_object, &alice_object, "derived_from", 1.0, json!({}))
        .expect("create legacy incoming edge");

    for uri in [
        format!("/api/graph/neighbors/{alice_object}"),
        format!("/api/graph/traverse/{alice_object}?direction=both"),
        format!("/api/provenance/lineage/{alice_object}"),
        format!("/api/objects/{alice_object}/why"),
        format!("/api/objects/{alice_object}/impact"),
        format!("/api/recommendations/datasets/{alice_object}"),
        format!("/api/recommendations/connections/{alice_object}"),
    ] {
        let (status, body) = call(&app, Method::GET, &uri, None, Some(&alice)).await;
        assert_eq!(status, StatusCode::OK, "owner graph route failed at {uri}: {body}");
        assert!(
            !body.to_string().contains(&bob_object),
            "cross-tenant object leaked through {uri}: {body}"
        );
    }

    // The owner retains normal access to their object.
    let (status, own_object) = call(&app, Method::GET, &format!("/api/objects/{alice_object}"), None, Some(&alice)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(own_object["id"], alice_object);
}


#[tokio::test]
async fn explicit_read_acl_scopes_list_search_sql_and_never_grants_write() {
    let (app, db) = test_app();
    let reader = register(&app, &db, "analyst").await;
    let owner = register(&app, &db, "operator").await;
    let reader_id = crate::auth::decode_token(&reader).expect("valid reader JWT").sub;
    let owner_id = crate::auth::decode_token(&owner).expect("valid owner JWT").sub;

    let shared_id = create_dataset(&app, &owner, SAMPLE_CSV).await;
    let mut shared = db.get_object(&shared_id).expect("read shared object").expect("shared object exists");
    shared["permissions"] = json!({
        "owner": owner_id,
        "read": [owner_id, reader_id],
        "write": [owner_id]
    });
    db.save_object(&shared).expect("persist reader grant and ACL index");

    assert!(db.can_read_object(&shared_id, &reader_id, false).expect("read ACL query"));
    assert!(!db.can_write_object(&shared_id, &reader_id, false).expect("write ACL query"));

    let (status, body) = call(&app, Method::GET, &format!("/api/objects/{shared_id}"), None, Some(&reader)).await;
    assert_eq!(status, StatusCode::OK, "explicit reader could not fetch object: {body}");
    assert_eq!(body["id"], shared_id);

    let (status, listed) = call(&app, Method::GET, "/api/objects/?object_type=dataset", None, Some(&reader)).await;
    assert_eq!(status, StatusCode::OK, "explicit reader list failed: {listed}");
    assert_eq!(listed["total"], 1);
    assert_eq!(listed["objects"][0]["id"], shared_id);

    let (status, searched) = call(&app, Method::GET, "/api/search/?q=alpha", None, Some(&reader)).await;
    assert_eq!(status, StatusCode::OK, "principal-scoped search failed: {searched}");
    assert!(searched["results"].as_array().expect("search results").iter().any(|item| item["id"] == shared_id));

    let table = format!("tbl_{}", &shared_id[..8]);
    let (status, query) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": format!("SELECT name FROM {table} ORDER BY name")})),
        Some(&reader),
    ).await;
    assert_eq!(status, StatusCode::OK, "reader SQL request failed: {query}");
    assert_eq!(query["success"], true, "reader SQL query failed: {query}");
    assert_eq!(query["row_count"], 2);

    let (status, agent_search) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id":"agent_research","capability":"search","params":{"query":"alpha"}})),
        Some(&reader),
    ).await;
    assert_eq!(status, StatusCode::OK, "agent search failed: {agent_search}");
    assert!(agent_search["result"]["results"].as_array().expect("agent search results").iter().any(|item| item["id"] == shared_id));

    let (status, agent_read) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id":"agent_research","capability":"read_object","params":{"object_id":shared_id}})),
        Some(&reader),
    ).await;
    assert_eq!(status, StatusCode::OK, "agent read should honor explicit ACL: {agent_read}");

    let public_id = create_dataset(&app, &owner, SAMPLE_CSV).await;
    let mut public = db.get_object(&public_id).expect("read public object").expect("public object exists");
    public["permissions"] = json!({
        "owner": owner_id,
        "read": ["*"],
        "write": [owner_id]
    });
    db.save_object(&public).expect("persist public read grant");
    assert!(db.can_read_object(&public_id, &reader_id, false).expect("public read ACL"));
    assert!(!db.can_write_object(&public_id, &reader_id, false).expect("public write ACL"));

    let (status, public_get) = call(&app, Method::GET, &format!("/api/objects/{public_id}"), None, Some(&reader)).await;
    assert_eq!(status, StatusCode::OK, "public wildcard did not grant read: {public_get}");

    let write_only_id = create_dataset(&app, &owner, SAMPLE_CSV).await;
    let mut write_only = db.get_object(&write_only_id).expect("read write-only object").expect("write-only object exists");
    write_only["permissions"] = json!({
        "owner": owner_id,
        "read": [owner_id],
        "write": [owner_id, reader_id]
    });
    db.save_object(&write_only).expect("persist write-only grant");
    assert!(db.can_write_object(&write_only_id, &reader_id, false).expect("explicit write grant"));
    assert!(!db.can_read_object(&write_only_id, &reader_id, false).expect("write must not imply read"));
    let (status, hidden) = call(&app, Method::GET, &format!("/api/objects/{write_only_id}"), None, Some(&reader)).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "write-only principal received object content: {hidden}");
    // Relationship listing must filter both endpoints in SQL before pagination.
    let (status, _) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({"source_id": shared_id, "target_id": public_id, "relation_type": "visible_to_reader", "confidence": 0.9})),
        Some(&owner),
    ).await;
    assert_eq!(status, StatusCode::OK, "owner could not create visible relationship");

    let (status, _) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({"source_id": shared_id, "target_id": write_only_id, "relation_type": "must_be_hidden", "confidence": 0.9})),
        Some(&owner),
    ).await;
    assert_eq!(status, StatusCode::OK, "owner could not create private relationship");

    let (status, visible_relationships) = call(
        &app,
        Method::GET,
        "/api/relationships/?limit=10&offset=0",
        None,
        Some(&reader),
    ).await;
    assert_eq!(status, StatusCode::OK, "reader relationship list failed: {visible_relationships}");
    assert_eq!(visible_relationships["total"], 1, "relationship with an unreadable endpoint leaked into count");
    let visible = visible_relationships["relationships"].as_array().expect("relationship list");
    assert_eq!(visible.len(), 1);
    assert_eq!(visible[0]["source"], shared_id);
    assert_eq!(visible[0]["target"], public_id);


    let admin = register(&app, &db, "admin").await;
    let (status, admin_read) = call(&app, Method::GET, &format!("/api/objects/{write_only_id}"), None, Some(&admin)).await;
    assert_eq!(status, StatusCode::OK, "explicit administrator bypass should remain available: {admin_read}");

    let (status, export) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id":"agent_research","capability":"export_data"})),
        Some(&reader),
    ).await;
    assert_eq!(status, StatusCode::OK, "scoped agent export failed: {export}");
    let exported_ids: Vec<&str> = export["result"]["objects"].as_array().expect("export objects")
        .iter().filter_map(|object| object["id"].as_str()).collect();
    assert!(exported_ids.contains(&shared_id.as_str()));
    assert!(!exported_ids.contains(&write_only_id.as_str()), "write-only object leaked through agent export");

}

#[tokio::test]
async fn public_registration_cannot_assign_privileged_role() {
    let (app, _db) = test_app();
    let username = format!("self_register_{}", &uuid::Uuid::new_v4().simple().to_string()[..8]);
    let password = random_test_secret();

    let (status, registered) = call(
        &app,
        Method::POST,
        "/api/auth/register",
        Some(json!({
            "username": username,
            "email": format!("{username}@example.com"),
            "password": password.clone(),
            "role": "admin"
        })),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "registration failed: {registered}");
    assert_eq!(registered["role"], "viewer", "public registration must ignore caller-selected roles");

    let (status, login) = call(
        &app,
        Method::POST,
        "/api/auth/login",
        Some(json!({"login": username, "password": password})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "login failed: {login}");
    let token = login["access_token"].as_str().expect("access token").to_string();

    let (status, me) = call(&app, Method::GET, "/api/auth/me", None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(me["user"]["role"], "viewer");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "self-registered user unexpectedly gained write access: {body}");
}

#[tokio::test]
async fn objects_relationships_and_traverse() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;

    let (status, first) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {"name": "alpha"}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, second) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {"name": "beta"}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let a = first["id"].as_str().unwrap().to_string();
    let b = second["id"].as_str().unwrap().to_string();

    let (status, _) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({"source_id": a, "target_id": b, "relation_type": "transforms_to", "confidence": 0.9})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let (status, listed) = call(&app, Method::GET, "/api/relationships/", None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(listed["total"], 1);
    // frontend contract: source/target, never source_id/target_id
    assert!(listed["relationships"][0].get("source").is_some());
    assert!(listed["relationships"][0].get("source_id").is_none());

    let (status, traversal) = call(
        &app,
        Method::GET,
        &format!("/api/graph/traverse/{a}?max_hops=3"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(traversal["root_id"], a);
    assert_eq!(traversal["total_nodes_reached"], 2);
    assert_eq!(traversal["total_edges_traversed"], 1);
}

#[tokio::test]
async fn sql_executes_over_registered_dataset() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;
    let id = create_dataset(&app, &token, SAMPLE_CSV).await;
    let table = format!("tbl_{}", &id[..8]);

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": format!("SELECT name, score FROM {table} ORDER BY score")})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["success"], true, "sql failed: {body}");
    assert_eq!(body["row_count"], 2);
    assert_eq!(body["rows"][0]["name"], "alpha");
    assert_eq!(body["rows"][1]["score"], 20.0);

    // write attempts must be rejected
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": "DROP TABLE x"})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["success"], false, "write query must be refused: {body}");
}

#[tokio::test]
async fn sql_does_not_silently_choose_between_duplicate_dataset_aliases() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;
    let first_id = create_dataset(&app, &token, "id,name,score\n1,first,10\n").await;
    let second_id = create_dataset(&app, &token, "id,name,score\n2,second,20\n").await;
    let first_table = format!("tbl_{}", &first_id[..8]);
    let second_table = format!("tbl_{}", &second_id[..8]);

    // Both uploads use demo.csv. The friendly alias is ambiguous and must not
    // expose whichever dataset happened to be registered first.
    let (status, ambiguous) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": "SELECT name FROM demo"})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(ambiguous["success"], false, "ambiguous alias unexpectedly resolved: {ambiguous}");

    for (table, expected_name) in [(&first_table, "first"), (&second_table, "second")] {
        let (status, result) = call(
            &app,
            Method::POST,
            "/api/compute/sql",
            Some(json!({"query": format!("SELECT name FROM {table}")})),
            Some(&token),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "SQL endpoint contract changed: {result}");
        assert_eq!(result["success"], true, "unique dataset alias failed: {result}");
        assert_eq!(result["rows"][0]["name"], expected_name);
        assert!(
            result["ambiguous_table_names"].as_array().unwrap().iter().any(|name| name == "demo"),
            "ambiguous aliases must be disclosed: {result}"
        );
    }
}

#[tokio::test]
async fn sql_authorizer_rejects_extension_loading() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": "SELECT load_extension('untrusted-extension')"})),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["success"], false, "extension loading must be denied: {body}");
    assert!(
        body["error"].as_str().unwrap_or("").to_ascii_lowercase().contains("not authorized"),
        "expected SQLite authorizer denial, got: {body}"
    );
}

#[tokio::test]
async fn sql_enforces_query_and_result_limits() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;

    let oversized_query = format!("SELECT 1 -- {}", "x".repeat(64 * 1024));
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": oversized_query})),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["success"], false);
    assert!(body["error"].as_str().unwrap_or("").contains("byte limit"));

    let recursive_query = "WITH RECURSIVE seq(x) AS (VALUES(1) UNION ALL SELECT x + 1 FROM seq WHERE x < 10001) SELECT x FROM seq";
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": recursive_query})),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["success"], false, "oversized result must be rejected: {body}");
    assert!(body["error"].as_str().unwrap_or("").contains("row limit"));
}

#[tokio::test]
async fn profiling_and_quality_reports() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;
    let id = create_dataset(&app, &token, SAMPLE_CSV).await;

    let (status, profile) = call(&app, Method::GET, &format!("/api/profiling/{id}"), None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK, "profiling failed: {profile}");
    assert_eq!(profile["row_count"], 2);
    assert_eq!(profile["column_count"], 3);
    assert_eq!(profile["columns"]["name"]["null_count"], 0);
    assert_eq!(profile["columns"]["score"]["stats"]["mean"], 15.0);
    assert_eq!(profile["summary"]["completeness_ratio"], 1.0);

    let (status, report) = call(
        &app,
        Method::POST,
        &format!("/api/quality/{id}"),
        Some(json!({"rules": [
            {"type": "row_count_min", "min_rows": 1},
            {"type": "unique", "column": "id"},
            {"type": "range", "column": "score", "min": 0, "max": 100}
        ]})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "quality failed: {report}");
    assert_eq!(report["schema"], "quality_report.v1");
    assert_eq!(report["properties"]["total_checks"], 3);
    assert_eq!(report["properties"]["overall_pass"], true);
    assert_eq!(report["properties"]["quality_score"], 100.0);

    // a failing rule must be reported, not hidden
    let (status, report) = call(
        &app,
        Method::POST,
        &format!("/api/quality/{id}"),
        Some(json!({"rules": [{"type": "row_count_min", "min_rows": 50}]})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(report["properties"]["overall_pass"], false);
    assert_eq!(report["properties"]["failed_checks"], 1);
}

#[tokio::test]
async fn sharing_tokens_roundtrip_and_tamper_detection() {
    let (app, _db) = test_app();

    let (status, issued) = call(
        &app,
        Method::POST,
        "/api/sharing/issue_token",
        Some(json!({
            "issuer": "dataos-test",
            "subject_principal": "analyst-1",
            "subgraph_root_id": "root-1",
            "duration_seconds": 300
        })),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "issue failed: {issued}");
    let token = issued["token"].as_str().expect("token").to_string();

    let (status, verified) = call(
        &app,
        Method::POST,
        "/api/sharing/verify_token",
        Some(json!({"token": token})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "verify failed: {verified}");
    assert_eq!(verified["status"], "valid");
    assert_eq!(verified["payload"]["subgraph_root_id"], "root-1");
    assert_eq!(verified["payload"]["issuer"], "dataos-test");

    // tampering must be detected
    let mut tampered = token.clone();
    let last = tampered.pop().expect("token has characters");
    tampered.push(if last == 'A' { 'B' } else { 'A' });
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/sharing/verify_token",
        Some(json!({"token": tampered})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "tampered token accepted: {body}");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/sharing/verify_token",
        Some(json!({"token": "not-a-token"})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "malformed token accepted: {body}");
}

#[tokio::test]
async fn vector_index_recompute_and_search() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;
    create_dataset(&app, &token, SAMPLE_CSV).await;

    let (status, body) = call(&app, Method::POST, "/api/vectors/recompute", Some(json!({})), Some(&token)).await;
    assert_eq!(status, StatusCode::OK, "recompute failed: {body}");
    assert!(body["recomputed"].as_u64().unwrap_or(0) >= 1);

    let (status, results) = call(
        &app,
        Method::GET,
        "/api/vectors/search?q=alpha&top_k=5",
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "search failed: {results}");
    assert!(results["total_matches"].as_u64().unwrap_or(0) >= 1, "no matches: {results}");
    assert!(results["results"][0]["score"].as_f64().unwrap_or(0.0) > 0.0);
}

#[tokio::test]
async fn time_travel_returns_prior_version() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;

    let (status, created) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "document", "properties": {"name": "v1"}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let id = created["id"].as_str().unwrap().to_string();
    let t1 = created["timestamps"]["created_at"].as_str().unwrap().to_string();

    // mutate through the store to produce version 2
    let mut object = db.get_object(&id).unwrap().expect("object exists");
    object["properties"]["name"] = json!("v2");
    object["version"] = json!(2);
    let t2 = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true);
    object["timestamps"]["updated_at"] = json!(t2.clone());
    db.save_object(&object).expect("save version 2");

    let (status, as_t1) = call(
        &app,
        Method::GET,
        &format!("/api/time_travel/object/{id}?as_of={}", urlencode(&t1)),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "time travel failed: {as_t1}");
    assert_eq!(as_t1["version"], 1);
    assert_eq!(as_t1["properties"]["name"], "v1");

    let (status, as_t2) = call(
        &app,
        Method::GET,
        &format!("/api/time_travel/object/{id}?as_of={}", urlencode(&t2)),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(as_t2["version"], 2);
    assert_eq!(as_t2["properties"]["name"], "v2");

    // invalid axis must be rejected
    let (status, _) = call(
        &app,
        Method::GET,
        &format!("/api/time_travel/object/{id}?as_of={}&temporal_axis=bogus", urlencode(&t1)),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn lineage_traces_upstream_and_downstream() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;

    let (status, raw) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "dataset", "properties": {"filename": "raw.csv"}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, report) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({"type": "report", "properties": {"name": "summary"}, "content": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let raw_id = raw["id"].as_str().unwrap().to_string();
    let report_id = report["id"].as_str().unwrap().to_string();

    let (status, _) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({"source_id": raw_id, "target_id": report_id, "relation_type": "transforms_to"})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let (status, upstream) = call(
        &app,
        Method::GET,
        &format!("/api/provenance/lineage/{report_id}?direction=upstream&max_depth=5"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "lineage failed: {upstream}");
    assert_eq!(upstream["target_object_id"], report_id);
    assert_eq!(upstream["total_ancestors"], 1);
    let ancestor_ids: Vec<&str> = upstream["lineage_nodes"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|node| node["object_id"].as_str())
        .collect();
    assert!(ancestor_ids.contains(&raw_id.as_str()));

    let (status, downstream) = call(
        &app,
        Method::GET,
        &format!("/api/provenance/lineage/{raw_id}?direction=downstream&max_depth=5"),
        None,
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(downstream["total_downstream_dependents"], 1);
    assert_eq!(downstream["impacted_nodes"][0]["object_id"], report_id);
}

#[tokio::test]
async fn workflow_execution_is_bounded_and_validated() {
    let (app, _db) = test_app();

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/workflows/execute",
        Some(json!({
            "definition": {
                "name": "demo",
                "nodes": {
                    "a": {"action_type": "set_variable", "parameters": {"name": "x", "value": 1}},
                    "b": {"action_type": "log", "parameters": {"message": "hello"}, "depends_on": ["a"]}
                }
            },
            "context": {"run": "test"}
        })),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "workflow failed: {body}");
    assert_eq!(body["status"], "completed");
    assert_eq!(body["nodes_total"], 2);
    assert_eq!(body["variables"]["x"], 1);
    assert_eq!(body["logs"].as_array().unwrap().len(), 1);

    // arbitrary actions are rejected up front
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/workflows/execute",
        Some(json!({"definition": {"name": "bad", "nodes": {"a": {"action_type": "shell", "parameters": {}}}}})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "unsafe action accepted: {body}");

    // dependency cycles are rejected
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/workflows/execute",
        Some(json!({"definition": {"name": "cycle", "nodes": {
            "a": {"action_type": "noop", "depends_on": ["b"]},
            "b": {"action_type": "noop", "depends_on": ["a"]}
        }}})),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "cycle accepted: {body}");
}

#[tokio::test]
async fn agent_dispatch_is_capability_checked() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;
    create_dataset(&app, &token, SAMPLE_CSV).await;

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id": "agent_unknown", "capability": "search", "params": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "unknown agent accepted: {body}");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id": "agent_research", "capability": "not_a_capability", "params": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "bad capability accepted: {body}");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id": "agent_research", "capability": "search", "params": {"query": "alpha"}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "agent search failed: {body}");
    assert_eq!(body["runtime"], "rust-deterministic");
    assert!(body["result"]["total_matches"].as_u64().unwrap_or(0) >= 1);

    // LLM-backed capabilities must fail loudly instead of fabricating output
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/execute",
        Some(json!({"agent_id": "agent_report", "capability": "compute_python", "params": {}})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_IMPLEMENTED, "unmigrated capability must 501: {body}");
}

#[tokio::test]
async fn unmigrated_routes_answer_501_not_fake_data() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/ask",
        Some(json!({"query": "what is in my data?"})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
    assert!(body["error"].as_str().unwrap_or("").contains("not been migrated"));

    let (status, _body) = call(
        &app,
        Method::POST,
        "/api/compute/python",
        Some(json!({"code": "print(1)"})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn knowledge_query_returns_scoped_evidence() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;

    let (status, dataset) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({
            "type": "dataset",
            "properties": {"filename": "measurements.csv", "raw_csv": SAMPLE_CSV},
            "content": {}
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let dataset_id = dataset["id"].as_str().unwrap().to_string();

    let (status, document) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({
            "type": "document",
            "properties": {"filename": "notes.md"},
            "content": {"body": "alpha measurements are recorded here"}
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let document_id = document["id"].as_str().unwrap().to_string();

    let (status, _) = call(
        &app,
        Method::POST,
        "/api/relationships",
        Some(json!({
            "source_id": document_id,
            "target_id": dataset_id,
            "relation_type": "references",
            "confidence": 0.9
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    // Simulate a legacy/admin-created edge to another tenant. Retrieval must
    // not include the foreign object merely because the edge exists.
    let bob = register(&app, &db, "operator").await;
    let foreign_dataset = create_dataset(&app, &bob, "id,name\\n9,private\\n").await;
    db.create_relationship(&document_id, &foreign_dataset, "references", 0.99, json!({}))
        .expect("create legacy cross-tenant edge");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/knowledge/query",
        Some(json!({
            "query": "alpha measurements",
            "selected_file_ids": [document_id],
            "include_related": true
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "knowledge query failed: {body}");
    assert_eq!(body["mode"], "scoped_evidence_retrieval");
    assert_eq!(body["generation_available"], false);
    assert_eq!(body["eligible_file_count"], 2);
    assert_eq!(body["related_files"].as_array().unwrap().len(), 1);
    assert_eq!(body["related_files"][0]["file_id"], dataset_id);
    assert_eq!(body["related_files"][0]["relationship_type"], "references");
    assert!(!body.to_string().contains(&foreign_dataset), "foreign related object leaked: {body}");

    let evidence = body["evidence"].as_array().expect("evidence list");
    assert!(!evidence.is_empty(), "expected evidence: {body}");
    assert_eq!(evidence[0]["file_id"], document_id, "explicitly selected file must rank first");
    assert_eq!(evidence[0]["selected"], true);
    assert_eq!(evidence[0]["inclusion_reason"], "explicitly selected");
    assert!(evidence[0]["score"].as_f64().unwrap_or(0.0) > 0.0);

    // a missing selection must fail loudly rather than silently dropping it
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/knowledge/query",
        Some(json!({"query": "alpha", "selected_file_ids": ["no-such-file"]})),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"]["missing_file_ids"][0], "no-such-file");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/knowledge/query",
        Some(json!({"query": "private", "selected_file_ids": [foreign_dataset]})),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "foreign selected object was accepted: {body}");
}

#[tokio::test]
async fn research_pipeline_runs_four_deterministic_stages() {
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;
    let id = create_dataset(&app, &token, SAMPLE_CSV).await;
    let table = format!("tbl_{}", &id[..8]);

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/pipeline/research",
        Some(json!({
            "goal_prompt": "summarise alpha scores",
            "target_dataset_id": id,
            "analysis_sql_or_python": format!("SELECT name, score FROM {table} ORDER BY score"),
            "quality_rules": [{"type": "row_count_min", "min_rows": 1}]
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "pipeline failed: {body}");
    assert_eq!(body["status"], "completed");
    assert!(body["pipeline_id"].as_str().unwrap().starts_with("pipeline_"));

    let stages = body["trace"]["stages"].as_array().expect("stage trace");
    assert_eq!(stages.len(), 4, "expected all four stages: {body}");
    assert_eq!(stages[0]["agent"], "agent_research");
    assert_eq!(stages[1]["agent"], "agent_analysis");
    assert_eq!(stages[1]["success"], true);
    assert_eq!(stages[2]["agent"], "agent_quality");
    assert_eq!(stages[2]["quality_pass"], true);
    assert_eq!(stages[3]["action"], "grounded_report_synthesis");
    assert_eq!(stages[3]["report_object_id"], body["report_object_id"]);
    assert!(body["cost_summary"]["total_tokens"].as_u64().unwrap_or(0) > 0);
    assert!(body["cost_summary"]["total_cost_usd"].as_f64().unwrap_or(1.0) == 0.0);

    // the report must be a first-class object linked derived_from the dataset
    let report_id = body["report_object_id"].as_str().unwrap();
    let (status, report) = call(&app, Method::GET, &format!("/api/objects/{report_id}"), None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK, "report object missing: {report}");
    assert_eq!(report["type"], "report");
    assert_eq!(report["schema"], "report.v1");

    let (status, relationships) = call(&app, Method::GET, "/api/relationships/", None, Some(&token)).await;
    assert_eq!(status, StatusCode::OK);
    let derived = relationships["relationships"]
        .as_array()
        .unwrap()
        .iter()
        .find(|rel| rel["relation_type"] == "derived_from")
        .expect("derived_from link");
    assert_eq!(derived["source"], report_id);
    assert_eq!(derived["target"], id);

    // non-SELECT analysis needs the Python sandbox, which Rust does not have
    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/pipeline/research",
        Some(json!({
            "goal_prompt": "run python",
            "target_dataset_id": id,
            "analysis_sql_or_python": "print(1)"
        })),
        Some(&token),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_IMPLEMENTED, "must not fake Python compute: {body}");
}

#[tokio::test]
async fn research_pipeline_cannot_read_or_report_another_users_dataset() {
    let (app, db) = test_app();
    let alice = register(&app, &db, "operator").await;
    let bob = register(&app, &db, "operator").await;
    let alice_dataset = create_dataset(&app, &alice, SAMPLE_CSV).await;
    let bob_dataset = create_dataset(&app, &bob, "id,name,score\\n9,private,99\\n").await;
    let alice_id = crate::auth::decode_token(&alice).expect("valid Alice JWT").sub;
    let bob_table = format!("tbl_{}",&bob_dataset[..8]);
    let alice_table = format!("tbl_{}",&alice_dataset[..8]);

    let before = db.list_objects_for_owner(&alice_id, Some("report"), None, 100, 0)
        .expect("list Alice reports").len();

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/pipeline/research",
        Some(json!({
            "goal_prompt": "summarise private scores",
            "target_dataset_id": alice_dataset,
            "analysis_sql_or_python": format!("SELECT name, score FROM {bob_table}")
        })),
        Some(&alice),
    ).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "foreign table query unexpectedly succeeded: {body}");

    let after = db.list_objects_for_owner(&alice_id, Some("report"), None, 100, 0)
        .expect("list Alice reports").len();
    assert_eq!(after, before, "failed analysis must not persist a report");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/agents/pipeline/research",
        Some(json!({
            "goal_prompt": "read foreign dataset",
            "target_dataset_id": bob_dataset,
            "analysis_sql_or_python": format!("SELECT name, score FROM {alice_table}")
        })),
        Some(&alice),
    ).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "foreign target dataset was accepted: {body}");
}

#[tokio::test]
async fn universal_ingest_accepts_form_encoded_body_from_frontend() {
    // The Next.js DropZone/EmptyState components post
    // `application/x-www-form-urlencoded`, which is what the FastAPI route
    // accepts via `Form(...)`. The Rust route must accept the same encoding.
    let (app, _db) = test_app();
    let token = register(&app, &_db, "operator").await;

    let request = Request::builder()
        .method(Method::POST)
        .uri("/api/ingest/universal")
        .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .body(Body::from(
            "filename=demo.csv&content=id%2Cname%2Cscore%0A1%2Calpha%2C10&discover_relations=true",
        ))
        .expect("request");
    let response = app.clone().oneshot(request).await.expect("router response");
    let status = response.status();
    let bytes = response
        .into_body()
        .collect()
        .await
        .expect("body")
        .to_bytes();
    let body: Value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).to_string()));
    assert_eq!(
        status,
        StatusCode::OK,
        "form-encoded ingest must work from the browser UI: {body}"
    );
    assert_eq!(body["objects_created"], 1, "unexpected ingest result: {body}");
    assert!(body["primary_object_id"].as_str().is_some(), "missing object id: {body}");
}

fn urlencode(value: &str) -> String {
    value
        .chars()
        .map(|c| match c {
            ':' => "%3A".to_string(),
            '+' => "%2B".to_string(),
            c if c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.' || c == '~' => c.to_string(),
            c => format!("%{:02X}", c as u32),
        })
        .collect()
}


#[tokio::test]
async fn object_creation_recomputes_server_managed_hash_and_validates_metadata() {
    let (app, db) = test_app();
    let token = register(&app, &db, "operator").await;
    let forged_hash = "0".repeat(64);

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({
            "type": "document",
            "properties": {"name": "canonical"},
            "content": {"text": "private evidence"},
            "metadata": {
                "content_hash": forged_hash,
                "source_note": "preserve this caller metadata"
            }
        })),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::OK, "object creation failed: {body}");

    let object_id = body["id"].as_str().expect("created object id");
    let stored = db.get_object(object_id).expect("read stored object").expect("object exists");
    let stored_hash = stored.pointer("/metadata/content_hash")
        .and_then(Value::as_str)
        .expect("server-managed content hash");
    assert_ne!(stored_hash, forged_hash, "caller-supplied content hash must never be trusted");
    assert_eq!(stored_hash, body.pointer("/metadata/content_hash").and_then(Value::as_str).unwrap());
    assert_eq!(
        stored.pointer("/metadata/source_note").and_then(Value::as_str),
        Some("preserve this caller metadata"),
        "ordinary caller metadata should be preserved"
    );
    assert_eq!(stored_hash.len(), 64);
    assert!(stored_hash.chars().all(|c| c.is_ascii_hexdigit()));

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/objects/",
        Some(json!({
            "type": "document",
            "properties": {},
            "content": {},
            "metadata": "not-an-object"
        })),
        Some(&token),
    ).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "invalid metadata shape was accepted: {body}");
}


#[test]
fn principal_scoped_research_routes_are_not_admin_only_aggregates() {
    assert!(
        !crate::is_global_data_route("/api/knowledge/query"),
        "knowledge retrieval enforces object ownership and should remain available to authorized analysts"
    );
    assert!(
        !crate::is_global_data_route("/api/agents/pipeline/research"),
        "the research pipeline registers and queries only the caller's datasets"
    );
    assert!(
        !crate::is_global_data_route("/api/compute/sql"),
        "SQL is principal-scoped: compute_sql registers only datasets readable by the authenticated principal"
    );
    assert!(
        crate::is_global_data_route("/api/io/export"),
        "global export must remain admin-only"
    );
}

#[tokio::test]
async fn sql_does_not_register_datasets_unreadable_by_principal() {
    let (app, db) = test_app();
    let owner = register(&app, &db, "operator").await;
    let reader = register(&app, &db, "analyst").await;

    // The dataset is private to its creator. Knowing its deterministic table
    // alias must not let another principal query its contents.
    let private_id = create_dataset(&app, &owner, SAMPLE_CSV).await;
    let private_table = format!("tbl_{}", &private_id[..8]);
    let query = format!("SELECT name FROM {private_table} ORDER BY name");

    let (status, body) = call(
        &app,
        Method::POST,
        "/api/compute/sql",
        Some(json!({"query": query})),
        Some(&reader),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "SQL endpoint contract changed: {body}");
    assert_eq!(
        body["success"],
        false,
        "a principal must not query a dataset outside its read ACL: {body}"
    );
    assert!(
        body["error"]
            .as_str()
            .unwrap_or("")
            .to_ascii_lowercase()
            .contains("no such table"),
        "unreadable datasets must not be registered in the query schema: {body}"
    );
    assert!(
        !body.to_string().contains("alpha"),
        "private dataset content leaked through SQL: {body}"
    );
}

