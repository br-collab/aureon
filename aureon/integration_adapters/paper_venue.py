"""
aureon.integration_adapters.paper_venue
=======================================
An independent synthetic venue for authorized releases (AUR-I-02, AUR-I-06).

Until L.C. provides the execution lifecycle, this is where a released decision
executes. It is independent of the approval in the ways reconciliation needs:

- It receives only the ``ReleaseAuthorized`` event.
- It prices from the market-data cache at its own observation time, through
  the ``price_source`` it was built with. It never reads the release's
  ``reference_price``, which is the decision's price.
- Its fills are labelled ``Provenance.FACT_SYNTHETIC``: a paper fact, not an
  external one.

It rejects rather than invents: an expired intent, no usable price, or a
notional too small for one unit returns a ``VenueRejection`` and nothing is
booked. A notional instruction fills the units it buys at the venue's price,
whole units where the asset class requires them (the quantity model, W2B-5).

A release is filled once. Delivering the same release again returns the
original fill, so a retry cannot create a second execution.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Literal

from cannae_kernel.canonical import canonical_bytes_of, digest_bytes
from cannae_kernel.provenance import Provenance
from pydantic import BaseModel, ConfigDict

from aureon.approval_service.release import ReleaseAuthorized

__all__ = ["VENUE_ID", "PaperFill", "PaperVenue", "PriceObservation", "VenueRejection"]

VENUE_ID = "AUREON-PAPER"
MAX_PERSISTED_FILLS = 1000

_Frozen = ConfigDict(frozen=True, extra="forbid")


class PriceObservation(BaseModel):
    model_config = _Frozen

    price: str
    observed_at: datetime
    source: str


class PaperFill(BaseModel):
    model_config = _Frozen

    schema_version: Literal["aureon.execution_fill/0.1-draft"] = "aureon.execution_fill/0.1-draft"
    event_type: Literal["EXECUTION_FILL"] = "EXECUTION_FILL"
    fill_id: str
    release_id: str
    decision_id: str
    symbol: str
    action: str
    asset_class: str
    quantity: str
    price: str
    notional: str
    venue: str
    price_source: str
    price_observed_at: datetime
    filled_at: datetime
    provenance: Provenance = Provenance.FACT_SYNTHETIC


class VenueRejection(BaseModel):
    model_config = _Frozen

    event_type: Literal["VENUE_REJECTED"] = "VENUE_REJECTED"
    release_id: str
    decision_id: str
    venue: str
    reason: str
    rejected_at: datetime
    provenance: Provenance = Provenance.FACT_SYNTHETIC


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


class PaperVenue:
    """Fills releases against the market-data cache. Stateless apart from ``state``."""

    def __init__(
        self,
        *,
        price_source: Callable[[str], PriceObservation | None],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._price_source = price_source
        self._clock = clock

    def execute(
        self, state: dict[str, Any], release: ReleaseAuthorized
    ) -> PaperFill | VenueRejection:
        """Fill ``release`` once. The caller holds the state lock."""
        for raw in state.get("venue_fills", []):
            if raw.get("release_id") == release.release_id:
                return PaperFill.model_validate_json(json.dumps(raw))

        now = self._clock().astimezone(timezone.utc)
        if now >= release.expires_at:
            return self._reject(release, now, "the approved intent expired at "
                                f"{release.expires_at.isoformat()}; it may not execute")
        observation = self._price_source(release.symbol)
        price = _positive_decimal(observation.price) if observation is not None else None
        if observation is None or price is None:
            return self._reject(release, now, f"no usable market price for {release.symbol}")
        if release.quantity_basis == "QUANTITY":
            quantity = _positive_decimal(release.quantity)
        else:
            # A notional instruction fills as many units as it buys at the
            # venue's price: whole units where the asset class requires them.
            notional = _positive_decimal(release.notional)
            quantity = None if notional is None else notional / price
            if quantity is not None:
                quantity = (quantity.to_integral_value(rounding=ROUND_DOWN) if release.whole_units
                            else quantity.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))
                if quantity <= 0:
                    return self._reject(release, now, f"notional {release.notional} buys less "
                                        f"than one unit of {release.symbol} at {price}")
        if quantity is None:
            return self._reject(release, now, "no positive quantity or notional on the release")

        fields = {
            "release_id": release.release_id,
            "decision_id": release.decision_id,
            "symbol": release.symbol,
            "action": release.action,
            "asset_class": release.asset_class,
            "quantity": format(quantity.normalize(), "f") if quantity != quantity.to_integral()
                        else str(int(quantity)),
            "price": format(price, "f"),
            "notional": format(quantity * price, "f"),
            "venue": VENUE_ID,
            "price_source": observation.source,
            "price_observed_at": observation.observed_at.astimezone(timezone.utc),
            "filled_at": now,
        }
        fill_id = "FILL-" + digest_bytes(canonical_bytes_of(fields))[7:23].upper()
        fill = PaperFill(fill_id=fill_id, **fields)
        log = state.setdefault("venue_fills", [])
        log.insert(0, fill.model_dump(mode="json"))
        del log[MAX_PERSISTED_FILLS:]
        return fill

    @staticmethod
    def _reject(release: ReleaseAuthorized, now: datetime, reason: str) -> VenueRejection:
        return VenueRejection(
            release_id=release.release_id,
            decision_id=release.decision_id,
            venue=VENUE_ID,
            reason=reason,
            rejected_at=now,
        )


def cache_price_source(
    prices: Mapping[str, Any], observed_at: Callable[[], datetime], source: str
) -> Callable[[str], PriceObservation | None]:
    """A price source over a market-data cache mapping symbol → last price."""

    def lookup(symbol: str) -> PriceObservation | None:
        value = prices.get(symbol)
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return PriceObservation(
            price=str(value), observed_at=observed_at().astimezone(timezone.utc), source=source
        )

    return lookup
