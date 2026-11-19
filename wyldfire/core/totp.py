"""Client-side TOTP helpers shared by the server and the CLI.

Enrollment is a client-driven walk: the CLI generates the secret, renders
the QR code for the authenticator app, and sends the secret + a code to
the server, which verifies the code before storing the secret (encrypted).
The server never renders QR codes; the CLI never verifies codes itself
for login (the server holds the secret after enrollment).
"""

from __future__ import annotations

import io
import shutil

import pyotp
import segno


def new_totp_secret() -> str:
    """Generate a fresh TOTP secret (base32, for the otpauth URI)."""
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str = "Wyldfire") -> str:
    """otpauth:// URI for an authenticator app."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def render_totp_qr(uri: str) -> str | None:
    """Render an otpauth URI as a terminal QR code (compact half-block mode).

    Returns the rendered string, or None when the terminal is too narrow
    to show it — the caller then prints the text secret only (the
    manual-entry fallback the spec requires).
    """
    try:
        qr = segno.make(uri)
    except Exception:
        return None
    buf = io.StringIO()
    try:
        qr.terminal(buf, compact=True, border=1)
    except Exception:
        return None
    rendered = buf.getvalue()
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    widest = max((len(line) for line in rendered.splitlines()), default=0)
    if widest > width:
        return None
    return rendered
