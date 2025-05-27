from pydantic import BaseModel

class OfferModel(BaseModel):
    sdp: str
    type: str

class ClientModel(BaseModel):
    id: str
    offer: OfferModel
