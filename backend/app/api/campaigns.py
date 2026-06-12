from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_db
from backend.app.schemas.campaigns import CampaignCreateRequest, CampaignSummary
from backend.app.schemas.common import Envelope
from backend.app.services import campaign_service


router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=Envelope[list[CampaignSummary]])
def list_campaigns(connection: Connection = Depends(get_db)) -> Envelope[list[CampaignSummary]]:
    return Envelope(data=campaign_service.list_campaigns(connection))


@router.post("", response_model=Envelope[CampaignSummary])
def create_campaign(
    payload: CampaignCreateRequest,
    connection: Connection = Depends(get_db),
) -> Envelope[CampaignSummary]:
    return Envelope(data=campaign_service.create_campaign(connection, payload))
