from typing import Any, Dict, Optional
from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

# OpenStreetMap Nominatim requires a distinct User-Agent identifying the app
geolocator = Nominatim(user_agent="fastapi_geolocation_service")


def reverse_geocode_coordinates(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    """
    Reverse geocodes latitude and longitude into structured location details.
    """
    try:
        # addressdetails=True ensures the raw dictionary includes separated keys
        location = geolocator.reverse(
            f"{lat}, {lng}",
            language="en",
            addressdetails=True,
            timeout=10,
        )

        if not location:
            return None

        address = location.raw.get("address", {})

        # Nominatim uses varying keys depending on area density
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("suburb")
            or address.get("county")
            or "Unknown"
        )

        state = address.get("state") or address.get("region") or "Unknown"
        country = address.get("country", "Unknown")
        postal_code = address.get("postcode", "Unknown")

        return {
            "full_address": location.address,
            "city": city,
            "state": state,
            "country": country,
            "postal_code": postal_code,
            "raw_address": address,
        }

    except (GeocoderTimedOut, GeocoderUnavailable) as exc:
        raise TimeoutError("Geocoding service timed out or is temporarily unavailable.") from exc
    except GeocoderServiceError as exc:
        raise RuntimeError(f"Geocoding service error: {str(exc)}") from exc