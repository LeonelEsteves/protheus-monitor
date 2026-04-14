# Project Memory (GAMB / Protheus Monitor)

## HTTPS / TLS

- `GAMB_FORCE_HTTPS=1`: redirects `http://` to `https://` (302). Use only when HTTPS is actually available (reverse proxy or TLS enabled).
- `GAMB_BEHIND_PROXY=1`: enables `ProxyFix` so `X-Forwarded-Proto`/`X-Forwarded-Host` are respected (typical when running behind IIS/Nginx/Apache).
- `GAMB_SSL_CERT_FILE` + `GAMB_SSL_KEY_FILE`: enables TLS directly on Flask `app.run(..., ssl_context=(cert, key))`.

Notes:
- Browser “Not secure” disappears only with a certificate trusted by the client (corporate CA / Let’s Encrypt / proper PKI). A self-signed certificate will still show a warning.

## Frontend Offline

- Tailwind is vendored locally at `static/vendor/tailwindcss.js`.
- Main templates use the local script instead of `https://cdn.tailwindcss.com`, so the layout still renders without internet access.
