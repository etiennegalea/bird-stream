import msgspec


# WebRTC signalling
class OfferModel(msgspec.Struct):
    sdp: str
    type: str


class ClientModel(msgspec.Struct):
    id: str
    offer: OfferModel


# Chat WebSocket messages
class ChatMessageData(msgspec.Struct):
    type: str  # "message" | "system" | "history"
    username: str | None = None
    text: str | None = None
    timestamp: str | None = None
    messages: list | None = None  # populated for "history" type


# Bird detection result (used once object recognition is wired in)
class BirdDetectionData(msgspec.Struct):
    species: str
    confidence: float
    detected_at: str
