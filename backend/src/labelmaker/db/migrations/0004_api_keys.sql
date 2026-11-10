-- Settings-managed API keys for machine clients (bearer auth under AUTH_MODE=oidc).
-- Only the SHA-256 of the key is stored; `prefix` is the lookup handle.
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    sha256_hash TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('read', 'write')),
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX idx_api_keys_prefix ON api_keys (prefix);
