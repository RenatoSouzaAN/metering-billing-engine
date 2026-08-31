from pydantic import BaseModel, Field, field_validator, model_validator


class GenerateRequest(BaseModel):
    meter: str
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)

    @field_validator("meter")
    @classmethod
    def meter_allowed(cls, value: str) -> str:
        if value not in ("api_call", "ai_tokens"):
            raise ValueError("meter must be api_call or ai_tokens")
        return value

    @model_validator(mode="after")
    def meter_matches_counts(self):
        tokens = (
            self.input_tokens
            + self.cached_input_tokens
            + self.output_tokens
            + self.reasoning_tokens
        )
        if self.meter == "api_call" and tokens != 0:
            raise ValueError("api_call must not include token counts")
        if self.meter == "ai_tokens" and tokens == 0:
            raise ValueError("ai_tokens requires at least one token count > 0")
        return self