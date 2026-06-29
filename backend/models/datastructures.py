import msgspec


class BaseStruct(msgspec.Struct):
    """Base for all msgspec request/response structs."""


# WebRTC signalling
class OfferModel(BaseStruct):
    sdp: str
    type: str


class ClientModel(BaseStruct):
    id: str
    offer: OfferModel


# Auth
class RegisterRequest(BaseStruct):
    email: str
    username: str
    password: str


class LoginRequest(BaseStruct):
    email: str
    password: str


class VerifyEmailRequest(BaseStruct):
    token: str


class ForgotPasswordRequest(BaseStruct):
    email: str


class ResetPasswordRequest(BaseStruct):
    token: str
    password: str


# Chat WebSocket messages
class ChatMessageData(BaseStruct):
    type: str  # "message" | "system" | "history"
    username: str | None = None
    text: str | None = None
    timestamp: str | None = None
    messages: list | None = None  # populated for "history" type


# Bird detection result (used once object recognition is wired in)
class BirdDetectionData(BaseStruct):
    species: str
    confidence: float
    detected_at: str
