import msgspec


class OfferModel(msgspec.Struct):
    sdp: str
    type: str


class ClientModel(msgspec.Struct):
    id: str
    offer: OfferModel
