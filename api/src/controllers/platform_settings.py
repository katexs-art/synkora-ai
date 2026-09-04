"""
Platform Settings Controller - Admin endpoints for platform configuration
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_async_db
from src.middleware.auth_middleware import require_role
from src.models import AccountRole
from src.services.billing.platform_settings_service import PlatformSettingsService

router = APIRouter(prefix="/platform-settings", tags=["Platform Settings"])


# Request/Response Schemas
class StripeKeysUpdate(BaseModel):
    """Schema for updating Stripe API keys"""

    secret_key: str | None = Field(None, description="Stripe secret key (will be encrypted)")
    publishable_key: str | None = Field(None, description="Stripe publishable key")
    webhook_secret: str | None = Field(None, description="Stripe webhook secret (will be encrypted)")


class PlatformSettingsResponse(BaseModel):
    """Schema for platform settings response"""

    stripe_enabled: bool
    stripe_configured: bool
    stripe_publishable_key: str | None

    model_config = ConfigDict(from_attributes=True)


class StripeConnectionTest(BaseModel):
    """Schema for Stripe connection test response"""

    success: bool
    account_id: str | None = None
    account_name: str | None = None
    country: str | None = None
    currency: str | None = None
    error: str | None = None


@router.get("", response_model=PlatformSettingsResponse)
async def get_platform_settings(
    db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))
):
    """
    Get current platform settings

    Requires: admin permission
    """
    service = PlatformSettingsService(db)
    settings = await service.get_settings()

    return PlatformSettingsResponse(
        stripe_enabled=settings.stripe_enabled == "true",
        stripe_configured=await service.is_stripe_configured(),
        stripe_publishable_key=settings.stripe_publishable_key,
    )


@router.put("/stripe-keys", response_model=PlatformSettingsResponse)
async def update_stripe_keys(
    data: StripeKeysUpdate, db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))
):
    """
    Update Stripe API keys

    Requires: admin permission
    """
    service = PlatformSettingsService(db)

    # Update keys
    settings = await service.update_stripe_keys(
        secret_key=data.secret_key, publishable_key=data.publishable_key, webhook_secret=data.webhook_secret
    )

    return PlatformSettingsResponse(
        stripe_enabled=settings.stripe_enabled == "true",
        stripe_configured=await service.is_stripe_configured(),
        stripe_publishable_key=settings.stripe_publishable_key,
    )


@router.post("/stripe/enable", response_model=PlatformSettingsResponse)
async def enable_stripe(db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))):
    """
    Enable Stripe integration

    Requires: admin permission
    Raises: 400 if Stripe keys are not configured
    """
    service = PlatformSettingsService(db)

    try:
        settings = await service.enable_stripe()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return PlatformSettingsResponse(
        stripe_enabled=settings.stripe_enabled == "true",
        stripe_configured=await service.is_stripe_configured(),
        stripe_publishable_key=settings.stripe_publishable_key,
    )


@router.post("/stripe/disable", response_model=PlatformSettingsResponse)
async def disable_stripe(db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))):
    """
    Disable Stripe integration

    Requires: admin permission
    """
    service = PlatformSettingsService(db)
    settings = await service.disable_stripe()

    return PlatformSettingsResponse(
        stripe_enabled=settings.stripe_enabled == "true",
        stripe_configured=await service.is_stripe_configured(),
        stripe_publishable_key=settings.stripe_publishable_key,
    )


@router.post("/stripe/test", response_model=StripeConnectionTest)
async def test_stripe_connection(
    db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))
):
    """
    Test Stripe connection with current keys

    Requires: admin permission
    Raises: 400 if Stripe is not configured
    """
    service = PlatformSettingsService(db)

    try:
        result = await service.test_stripe_connection()
        return StripeConnectionTest(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/stripe-keys", response_model=PlatformSettingsResponse)
async def clear_stripe_keys(
    db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))
):
    """
    Clear all Stripe keys (useful for testing or reconfiguration)

    Requires: admin permission
    """
    service = PlatformSettingsService(db)
    settings = await service.clear_stripe_keys()

    return PlatformSettingsResponse(
        stripe_enabled=settings.stripe_enabled == "true",
        stripe_configured=await service.is_stripe_configured(),
        stripe_publishable_key=settings.stripe_publishable_key,
    )


class BrandingUpdate(BaseModel):
    """Branding fields that admins can change."""

    platform_name: str | None = None
    platform_logo_url: str | None = None
    support_email: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


class BrandingResponse(BaseModel):
    """Branding payload returned to clients."""

    platform_name: str | None = None
    platform_logo_url: str | None = None
    support_email: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


def _branding_dict(settings) -> dict:
    return {
        "platform_name": settings.platform_name,
        "platform_logo_url": settings.platform_logo_url,
        "support_email": settings.support_email,
        "primary_color": settings.primary_color,
        "secondary_color": settings.secondary_color,
    }


@router.get("/branding", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_async_db), _: None = Depends(require_role(AccountRole.ADMIN))):
    """Get branding (admin)."""
    service = PlatformSettingsService(db)
    return _branding_dict(await service.get_settings())


@router.put("/branding", response_model=BrandingResponse)
async def update_branding(
    data: BrandingUpdate,
    db: AsyncSession = Depends(get_async_db),
    _: None = Depends(require_role(AccountRole.ADMIN)),
):
    """Update branding (admin)."""
    service = PlatformSettingsService(db)
    settings = await service.update_branding(
        platform_name=data.platform_name,
        platform_logo_url=data.platform_logo_url,
        support_email=data.support_email,
        primary_color=data.primary_color,
        secondary_color=data.secondary_color,
    )
    return _branding_dict(settings)


@router.get("/branding/public")
async def get_branding_public(db: AsyncSession = Depends(get_async_db)):
    """Public branding for login pages / widgets (no auth)."""
    service = PlatformSettingsService(db)
    return _branding_dict(await service.get_settings())

