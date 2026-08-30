"""Auth: register / login. Every user of the platform is independent and
brings their own credentials.

Google sign-in (auth.txt): the frontend obtains a Google ID token via Google
Identity Services, the backend verifies it with Google's public keys, finds or
creates the local user, and issues the application's own JWT — the Google token
is never used as a long-term authorization credential."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .. import config, security
from ..database import get_db
from ..models import User, _now
from ..schemas import GoogleTokenRequest, LoginRequest, RegisterRequest, TokenResponse
from .deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter_by(username=body.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    email = body.email.strip().lower()
    if email:
        if db.query(User).filter_by(email=email).first():
            raise HTTPException(status_code=400, detail="Email already in use")
    user = User(
        username=body.username.strip(),
        email=email or None,
        password_hash=security.hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_for(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = None
    identifier = (body.email or body.username or "").strip()
    if not identifier:
        raise HTTPException(status_code=401, detail="Email or username is required")
    # Resolve by email when an @ is present, otherwise by username.
    if "@" in identifier:
        user = db.query(User).filter_by(email=identifier.lower()).first()
    if user is None:
        user = db.query(User).filter_by(username=identifier).first()
    if not user or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email/username or password")
    return _token_for(user)


def _token_for(user: User) -> dict:
    return {
        "access_token": security.create_access_token(user.id),
        "username": user.username,
        "email": user.email or "",
        "name": user.name or "",
        "picture": user.profile_picture or "",
    }


@router.post("/google", response_model=TokenResponse)
def google_login(body: GoogleTokenRequest, db: Session = Depends(get_db)):
    if not body.credential or not body.credential.strip():
        raise HTTPException(status_code=400, detail="Missing Google credential")
    info = _verify_google_token(body.credential.strip())
    sub = info["sub"]
    email = (info.get("email") or "").strip().lower()
    name = (info.get("name") or "").strip()
    picture = (info.get("picture") or "").strip()

    # 1) stable Google subject id  → 2) verified email (legacy/linking)
    user = db.query(User).filter_by(google_id=sub).first()
    if user is None and email:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = db.query(User).filter_by(username=email).first()

    if user is None:
        base = (email or f"google_{sub}")[:80]
        username = base
        if db.query(User).filter_by(username=username).first():
            username = f"google_{sub[-12:]}"[:80]
        user = User(
            username=username,
            password_hash="",
            email=email or None,
            name=name or None,
            google_id=sub,
            profile_picture=picture or None,
        )
        db.add(user)
    else:
        if not user.google_id:
            user.google_id = sub
        if email and (user.email or "").lower() != email:
            user.email = email
        if name:
            user.name = name
        if picture:
            user.profile_picture = picture
    user.updated_at = _now()
    try:
        db.commit()
    except IntegrityError:
        # concurrent duplicate sign-in: roll back and match the existing row
        db.rollback()
        user = db.query(User).filter_by(google_id=sub).first()
        if user is None and email:
            user = db.query(User).filter_by(email=email).first()
        if user is None:
            raise HTTPException(status_code=500, detail="Could not finish Google sign-in")
    db.refresh(user)
    return _token_for(user)


def _verify_google_token(credential: str) -> dict:
    """Verify a Google ID token against Google's public keys and return the
    verified claims. Rejects bad signatures, wrong issuer, wrong audience
    (client id) and expired tokens. Never trusts claims from the frontend."""
    from jwt import PyJWKClient

    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured yet. Contact your administrator.",
        )
    try:
        jwks = PyJWKClient(config.GOOGLE_CERTS_URL)
        signing_key = jwks.get_signing_key_from_jwt(credential).key
        import jwt

        claims = jwt.decode(
            credential,
            signing_key,
            algorithms=["RS256"],
            audience=config.GOOGLE_CLIENT_ID,
            options={"verify_exp": True, "verify_aud": True},
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001  (bad signature / expired / network)
        raise HTTPException(status_code=401, detail="Invalid or expired Google credential") from exc

    audience = claims.get("aud")
    if audience != config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google credential is not valid for this application")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Google credential has an invalid issuer")
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Google credential is missing a subject")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Google email is not verified")
    return claims


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "name": user.name or "",
        "picture": user.profile_picture or "",
    }