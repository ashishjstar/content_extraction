# SOP Migration System — Project Configuration
"""Application-wide configuration loaded from environment or defaults."""

from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings

# Automatically load .env into os.environ on startup
load_dotenv()


class Settings(BaseSettings):
    """Central configuration — injected into all services via constructor."""

    # --- Paths ---
    project_root: Path = Path(__file__).resolve().parent.parent.parent
    upload_dir: Path = Path("data/uploads")
    extracted_images_dir: Path = Path("data/extracted_images")
    extracted_icons_dir: Path = Path("data/extracted_icons")
    temp_dir: Path = Path("data/temp")
    output_dir: Path = Path("data/output")

    # --- Processing ---
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = [".pdf", ".docx"]
    ocr_enabled: bool = False
    ocr_language: str = "eng"

    # --- Semantic Chunking ---
    embedding_model: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = 0.4

    # --- Watermark Filtering ---
    watermark_keywords: list[str] = [
        "WORKING COPY",
        "DRAFT",
        "CONFIDENTIAL",
        "DO NOT DISTRIBUTE",
        "WATERMARK"
    ]

    # --- Table Stitching ---
    table_stitch_enabled: bool = True
    table_stitch_score_threshold: float = 0.7
    table_stitch_column_tolerance_pt: float = 15.0
    table_stitch_bottom_zone_pct: float = 0.75
    table_stitch_top_zone_pct: float = 0.20

    # --- Logging ---
    log_level: str = "INFO"
    log_dir: Path = Path("data/logs")
    log_file_path: Path = Path("data/logs/app.log")
    error_file_path: Path = Path("data/logs/error.log")
    log_db_path: Path = Path("data/logs/logs.db")

    # --- Migration ---
    migration_output_dir: Path = Path("data/migrated")
    migration_template_dir: Path = Path("data/templates")
    skip_preamble_migration: bool = True       # Don't touch cover page / Section 0

    # --- LLM (LangChain) ---
    use_llm_section_summarizer: bool = False  # false = Mode A (programmatic), true = Mode B (LLM semantic)
    llm_planner_model: str = "gemini/gemini-2.5-flash"
    llm_summarizer_model: str = "gemini/gemini-2.5-flash"
    llm_temperature: float = 0.1
    llm_planner_max_tokens: int = 16384
    llm_summarizer_max_tokens: int = 4096

    # --- Azure OpenAI (optional — overrides llm_planner_model / llm_summarizer_model if set) ---
    use_azure_openai: bool = False                              # Set true to route all LLM calls through Azure
    azure_openai_endpoint: Optional[str] = None                # e.g. "https://<your-resource>.openai.azure.com/"
    azure_openai_api_version: str = "2024-12-01-preview"       # Azure OpenAI API version
    azure_openai_planner_deployment: str = "gpt-4o"            # Deployment name for planner (Phase 2)
    azure_openai_summarizer_deployment: str = "gpt-4o-mini"    # Deployment name for summarizer (Mode B)
    azure_openai_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "SOP_AZURE_OPENAI_API_KEY", "azure_openai_api_key")
    )

    # --- LLM Rate Limiting ---
    llm_max_concurrent: int = 3
    llm_min_delay_seconds: float = 0.5
    llm_max_retries: int = 5
    llm_base_backoff_seconds: float = 2.0

    # --- Authentication & JWT ---
    jwt_secret_key: str = "sop-governance-auth-secret-key-development-2026"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_seconds: int = 900
    jwt_issuer: str = "governance-sop-api"
    jwt_audience: str = "governance-sop-web"
    auth_db_path: Optional[Path] = None
    auth_refresh_token_expire_days: int = 1
    auth_remember_me_expire_days: int = 30
    auth_max_failed_attempts: int = 5
    auth_lockout_duration_minutes: int = 15
    auth_ip_rate_limit_max_attempts: int = 10
    auth_ip_rate_limit_window_minutes: int = 15
    auth_cookie_secure: bool = False

    model_config = {
        "env_prefix": "SOP_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def resolve_paths(self, base: Path) -> None:
        """Resolve all relative paths against a base directory."""
        self.upload_dir = base / self.upload_dir
        self.extracted_images_dir = base / self.extracted_images_dir
        self.extracted_icons_dir = base / self.extracted_icons_dir
        self.temp_dir = base / self.temp_dir
        self.output_dir = base / self.output_dir
        self.migration_output_dir = base / self.migration_output_dir
        self.migration_template_dir = base / self.migration_template_dir
        self.log_dir = base / self.log_dir
        self.log_file_path = base / self.log_file_path
        self.error_file_path = base / self.error_file_path
        self.log_db_path = base / self.log_db_path

    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        for dir_path in [
            self.upload_dir,
            self.extracted_images_dir,
            self.extracted_icons_dir,
            self.temp_dir,
            self.output_dir,
            self.migration_output_dir,
            self.migration_template_dir,
            self.log_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def get_document_image_dir(self, document_id: str) -> Path:
        """Return (and create) the image directory for a specific document."""
        p = self.extracted_images_dir / str(document_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_document_icon_dir(self, document_id: str) -> Path:
        """Return (and create) the icon directory for a specific document."""
        p = self.extracted_icons_dir / str(document_id)
        p.mkdir(parents=True, exist_ok=True)
        return p


def get_settings() -> Settings:
    """Factory function for dependency injection in FastAPI."""
    settings = Settings()
    settings.resolve_paths(settings.project_root)
    settings.ensure_directories()
    return settings
