from pydantic import BaseModel


class CreateLocationRequest(BaseModel):
    location_name: str
    location_code: str
    address: str
    latitude: float
    longitude: float
    radius: int
