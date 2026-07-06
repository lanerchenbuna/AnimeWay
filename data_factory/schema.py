from typing import List, Optional, Dict
from pydantic import BaseModel, Field, field_validator

# --- Level 1: Geography (The "Where") ---
class Spot(BaseModel):
    id: str
    name: str # The specific location name
    image: Optional[str] = None
    lat: float
    lon: float
    description: Optional[str] = None
    city: Optional[str] = None # Enriched city name
    tags: List[str] = Field(default_factory=list)

    @field_validator('name')
    def normalize_name(cls, v):
        return str(v).strip()

# --- Level 2: Metadata (The "What" & "Why") ---
class AnimeMetadata(BaseModel):
    id: int
    titles: Dict[str, str] # {'cn': '...', 'jp': '...'}
    cover: Optional[str] = None
    type: Optional[str] = None # TV, Movie, OVA
    score: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None # Synopsis/Intro
    staff: Optional[Dict[str, str]] = None # Director, Studio...

# --- Level 3: Unified Knowledge Unit (The "Agent Context") ---
class AnimeItem(BaseModel):
    anime_id: int
    meta: AnimeMetadata
    spots: List[Spot] = Field(default_factory=list)
    
    # Pre-computed string for vector embedding/RAG retrieval
    rag_content: Optional[str] = None 
