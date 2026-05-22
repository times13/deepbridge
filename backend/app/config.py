"""
Centralized configuration. Values can be overridden via environment variables
or a `.env` file at the backend root.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Paths
    data_dir: Path = Path("./data")
    model_dir: Path = Path("./app/models")

    # Model filenames (placed inside model_dir)
    unet_model_filename: str = "carotide_detector_v2.h5"
    rf_model_filename: str = "random_forest.onnx"

    # API metadata
    app_version: str = "0.1.0"

    # CORS — extend as needed
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    @property
    def unet_model_path(self) -> Path:
        return self.model_dir / self.unet_model_filename

    @property
    def rf_model_path(self) -> Path:
        return self.model_dir / self.rf_model_filename


settings = Settings()
