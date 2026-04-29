import os
import uuid
import asyncio
import aiohttp
import asyncpg
import numpy as np
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer


async def _handle_sync_leads(campaign_history_id: int):
    print(f"running history_id={campaign_history_id}")