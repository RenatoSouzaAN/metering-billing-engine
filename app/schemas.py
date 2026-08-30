from pydantic import BaseModel, field_validator


class GenerateRequest(BaseModel):
    meter: str

    @field_validator("meter")
    @classmethod
    def only_api_call_for_now(cls, value: str) -> str:
        if value != "api_call":
            raise ValueError("Only meter=api_call is supported for now")
        return value