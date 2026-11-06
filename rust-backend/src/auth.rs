use base64::Engine as _;
use chrono::{Duration, Utc};
use jsonwebtoken::{Algorithm, DecodingKey, EncodingKey, Header, Validation, decode, encode};
use pbkdf2::pbkdf2_hmac;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use uuid::Uuid;

pub const JWT_SECRET_ENV: &str = "DATAOS_JWT_SECRET";
pub const MIN_SECRET_BYTES: usize = 32;
const DEFAULT_TTL_SECONDS: i64 = 3600;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub role: String,
    pub iat: i64,
    pub exp: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: String,
    pub username: String,
    pub email: String,
    pub role: String,
    pub password_hash: String,
    pub created_at: String,
}

pub fn jwt_secret() -> Option<Vec<u8>> {
    let secret = std::env::var(JWT_SECRET_ENV).ok()?;
    if secret.trim() != secret || secret.len() < MIN_SECRET_BYTES {
        return None;
    }
    Some(secret.into_bytes())
}

pub fn jwt_configured() -> bool {
    jwt_secret().is_some()
}

fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

pub fn hash_password(password: &str) -> String {
    let mut salt = [0_u8; 16];
    rand::thread_rng().fill_bytes(&mut salt);
    let iterations = 200_000_u32;
    let mut derived = [0_u8; 32];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), &salt, iterations, &mut derived);
    format!(
        "{}${}${}",
        hex::encode(salt),
        iterations,
        base64::engine::general_purpose::STANDARD.encode(derived)
    )
}

pub fn verify_password(password: &str, stored: &str) -> bool {
    let mut parts = stored.split('$');
    let salt_hex = match parts.next() {
        Some(value) => value,
        None => return false,
    };
    let iterations_text = match parts.next() {
        Some(value) => value,
        None => return false,
    };
    let hash_b64 = match parts.next() {
        Some(value) => value,
        None => return false,
    };
    let iterations = match iterations_text.parse::<u32>() {
        Ok(value) => value,
        Err(_) => return false,
    };
    let salt = match hex::decode(salt_hex) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let expected = match base64::engine::general_purpose::STANDARD.decode(hash_b64) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut actual = vec![0_u8; expected.len()];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), &salt, iterations, &mut actual);
    constant_time_eq(&actual, &expected)
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0_u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

pub fn issue_token(user_id: &str, role: &str) -> Result<String, String> {
    let secret = jwt_secret().ok_or_else(|| "DATAOS_JWT_SECRET is not configured".to_string())?;
    let now = Utc::now();
    let claims = Claims {
        sub: user_id.to_string(),
        role: role.to_string(),
        iat: now.timestamp(),
        exp: (now + Duration::seconds(DEFAULT_TTL_SECONDS)).timestamp(),
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(&secret),
    )
    .map_err(|error| error.to_string())
}

pub fn decode_token(token: &str) -> Result<Claims, String> {
    let secret = jwt_secret().ok_or_else(|| "DATAOS_JWT_SECRET is not configured".to_string())?;
    let mut validation = Validation::new(Algorithm::HS256);
    validation.validate_exp = true;
    validation.set_required_spec_claims(&["sub", "role", "iat", "exp"]);
    decode::<Claims>(token, &DecodingKey::from_secret(&secret), &validation)
        .map(|data| data.claims)
        .map_err(|error| error.to_string())
}

pub fn role_capabilities(role: &str) -> Vec<&'static str> {
    match role {
        "viewer" => vec!["search", "read_object"],
        "analyst" => vec!["search", "read_object", "create_relation", "query_sql", "extract_knowledge", "export_data"],
        "operator" => vec![
            "search", "read_object", "create_object", "update_object", "create_relation",
            "query_sql", "compute_python", "transform_data", "extract_knowledge",
            "execute_workflow", "call_connector", "export_data",
        ],
        "admin" => vec![
            "search", "read_object", "create_object", "update_object", "delete_object",
            "create_relation", "delete_relation", "query_sql", "compute_python",
            "transform_data", "extract_knowledge", "execute_workflow", "call_connector", "export_data",
        ],
        _ => vec!["search", "read_object"],
    }
}

pub fn user_payload(user: &User) -> serde_json::Value {
    serde_json::json!({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "capabilities": role_capabilities(&user.role),
        "created_at": user.created_at,
    })
}

pub fn new_user(username: &str, email: &str, password: &str, role: &str) -> Result<User, String> {
    if username.trim().is_empty() || email.trim().is_empty() {
        return Err("username and email are required".into());
    }
    if password.len() < 8 {
        return Err("Password must be at least 8 characters.".into());
    }
    if !["viewer", "analyst", "operator", "admin"].contains(&role) {
        return Err("Unknown role".into());
    }
    Ok(User {
        id: Uuid::new_v4().to_string(),
        username: username.trim().to_string(),
        email: email.trim().to_lowercase(),
        role: role.to_string(),
        password_hash: hash_password(password),
        created_at: utc_now(),
    })
}
