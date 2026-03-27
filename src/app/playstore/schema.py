from pydantic import BaseModel
from typing import Optional


class PlaystoreQueryInput(BaseModel):
    app_id: str          # e.g. com.spotify.music
    max_reviews: Optional[int] = 500