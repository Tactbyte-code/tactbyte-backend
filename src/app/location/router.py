from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status
from src.app.location.schema import CoordinatesPayload, LocationResponse
from src.app.location.services import reverse_geocode_coordinates

router = APIRouter(prefix="/location", tags=["Location"])

@router.post(
    "/reverse-geocode",
    response_model=LocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Reverse geocode GPS coordinates to an address",
)

async def reverse_geocode_endpoint(payload: CoordinatesPayload):
    try:
        location_data = reverse_geocode_coordinates(payload.lat, payload.lng)

        if not location_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No address found for the provided coordinates.",
            )

        return location_data

    except TimeoutError as err:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(err),
        )
    except RuntimeError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(err),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while resolving coordinates.",
        )