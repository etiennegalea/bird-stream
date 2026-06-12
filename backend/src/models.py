from pydantic import BaseModel
from typing import Optional

class OfferModel(BaseModel):
    sdp: str
    type: str

class ClientModel(BaseModel):
    id: str
    offer: OfferModel

class CameraControlModel(BaseModel):
    action: str
    srt_host: Optional[str] = None
    srt_port: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    bitrate: Optional[str] = None

