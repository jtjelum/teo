"""Fejlrapportering til admin-panel — spec §6.1 (POST /v1/feedback).

Lader brugeren rapportere en konkret beslutning ("ventede for længe", "agerede
for tidligt", ...). Tilgængeligt for ALLE modeller — ingen autentificering.
Konteksten samles automatisk fra HA og er fuldstændig anonym (designprincip #5):
intet UUID-link til person, ingen IP, intet serienummer.

Klient-side throttling spejler serverens grænse (max 10 rapporter/UUID/døgn).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from .const import FEEDBACK_COMMENT_MAX_LEN, FEEDBACK_ISSUE_TYPES
from .teo_api_client import TEOAPIClient, TEOAPIError

_LOGGER = logging.getLogger(__name__)

_MAX_REPORTS_PER_DAY = 10


class FeedbackError(Exception):
    """Ugyldig feedback-input eller afsendelsesfejl."""


def build_feedback_payload(
    installation_uuid: str,
    decision_timestamp: str,
    decision_type: str,
    issue_type: str,
    context: dict[str, Any],
    user_comment: Optional[str] = None,
) -> dict[str, Any]:
    """Saml og validér en feedback-payload (spec §6.1).

    ``context`` skal kun indeholde anonyme felter (zone, batteritype, SOC,
    priser, solprognose, version). Kalderen må ALDRIG lægge person-/netdata heri.
    """
    if issue_type not in FEEDBACK_ISSUE_TYPES:
        raise FeedbackError(f"Ukendt issue_type: {issue_type}")
    if user_comment and len(user_comment) > FEEDBACK_COMMENT_MAX_LEN:
        raise FeedbackError(
            f"Kommentar over {FEEDBACK_COMMENT_MAX_LEN} tegn"
        )

    return {
        "id": installation_uuid,
        "decision_timestamp": decision_timestamp,
        "decision_type": decision_type,
        "issue_type": issue_type,
        "user_comment": user_comment,
        "context": context,
    }


class FeedbackReporter:
    """Indsender feedback og holder styr på daglig kvote."""

    def __init__(self, client: Optional[TEOAPIClient] = None) -> None:
        self._client = client or TEOAPIClient()
        self._owns_client = client is None
        self._sent_today: list[datetime] = []

    def _quota_remaining(self, now: datetime) -> int:
        self._sent_today = [
            t for t in self._sent_today if t.date() == now.date()
        ]
        return _MAX_REPORTS_PER_DAY - len(self._sent_today)

    async def submit(self, payload: dict[str, Any],
                     now: Optional[datetime] = None) -> dict[str, Any]:
        """Send en feedback-payload. Returnerer ``{report_id, received}``.

        Hæver ``FeedbackError`` ved overskreden kvote eller netfejl.
        """
        now = now or datetime.now()
        if self._quota_remaining(now) <= 0:
            raise FeedbackError(
                f"Daglig grænse på {_MAX_REPORTS_PER_DAY} rapporter nået"
            )
        try:
            result = await self._client.send_feedback(payload)
        except TEOAPIError as err:
            raise FeedbackError(str(err)) from err

        self._sent_today.append(now)
        _LOGGER.info("Feedback indsendt (report_id=%s)",
                     (result or {}).get("report_id"))
        return result or {}

    async def status(self, report_id: str) -> Optional[dict[str, Any]]:
        """Hent status på en tidligere rapport (spec §6.1 GET /v1/feedback/status)."""
        return await self._client.get_feedback_status(report_id)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
