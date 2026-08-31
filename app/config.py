from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    api_call_micro_usd: int = 100
    input_micro_usd_per_million: int = 150_000
    cached_input_micro_usd_per_million: int = 37_500
    output_micro_usd_per_million: int = 600_000

settings = Settings()