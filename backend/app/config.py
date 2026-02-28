from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://story:story@postgres:5432/story_engine"
    llm_provider: str = "mock"
    llm_model_character: str = "gpt-4o-mini"
    llm_model_summary: str = "gpt-4o-mini"
    llm_model_narrative: str = "gpt-4o"
    llm_external_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    chunk_size_prompts: int = 7

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
