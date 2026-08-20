from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_profile: Literal["local-cloud", "ci", "docker", "production"] = "local-cloud"
    app_name: str = "DeltaLedger AI"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = True
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    frontend_url: str | None = None
    readiness_dependency_checks_enabled: bool = False
    auth_enabled: bool = False
    auth_secret_key: str | None = None
    auth_token_ttl_seconds: int = 3600
    auth_login_username: str = "demo"
    auth_login_password: str | None = None
    auth_login_role: Literal["analyst", "reviewer", "admin"] = "admin"

    database_url: str = "postgresql+asyncpg://deltaledger@localhost:5433/deltaledger"
    alembic_database_url: str | None = None
    test_database_url: str = (
        "postgresql+asyncpg://deltaledger@localhost:5433/deltaledger_test"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout_seconds: float = 30.0
    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = 5.0
    redis_socket_timeout_seconds: float = 5.0

    object_storage_provider: Literal["filesystem", "minio"] = "filesystem"
    object_storage_local_root: str = "./data/object-storage"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_filings: str = "filings"
    minio_bucket_reports: str = "reports"

    sec_user_agent: str = Field(
        default="DeltaLedgerAI/0.1 contact@example.com",
        description="SEC-compliant User-Agent containing app/contact information.",
    )
    sec_base_url: str = "https://www.sec.gov"
    sec_data_url: str = "https://data.sec.gov"
    sec_request_timeout_seconds: float = 20.0
    sec_max_attempts: int = 3
    sec_min_wait_seconds: float = 1.0
    sec_max_wait_seconds: float = 8.0
    sec_requests_per_second: float = 5.0

    parser_version: str = "sec-html-parser-v0"
    table_extraction_version: str = "sec-table-extractor-v0"
    chunker_version: str = "section-aware-chunker-v0"
    chunk_max_tokens: int = 450
    chunk_overlap_tokens: int = 60

    embedding_provider: str = "fake"
    embedding_model: str = "BAAI/bge-m3"
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 16
    embedding_device: str = "cpu"
    embedding_normalize: bool = True
    embedding_timeout_seconds: float = 60.0
    hf_token: str | None = None
    hf_inference_base_url: str = "https://api-inference.huggingface.co"
    allow_fake_models_in_production: bool = False
    ai_provider_api_key: str | None = None
    ai_provider_base_url: str = "https://api.openai.com/v1"
    ai_provider_timeout_seconds: float = 60.0
    ai_provider_max_retries: int = 3
    ai_provider_input_token_cost_usd_per_million: float | None = None
    ai_provider_output_token_cost_usd_per_million: float | None = None

    reranker_enabled: bool = False
    reranker_provider: str = "fake"
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_batch_size: int = 16
    reranker_candidate_limit: int = 40
    reranker_timeout_seconds: float = 60.0

    comparison_version: str = "phase3-v1"
    passage_segmentation_version: str = "paragraph-segmentation-v1"
    section_match_min_score: float = 0.62
    section_match_weight_structural: float = 0.30
    section_match_weight_heading: float = 0.20
    section_match_weight_dense: float = 0.20
    section_match_weight_lexical: float = 0.15
    section_match_weight_reranker: float = 0.10
    section_match_weight_position: float = 0.05
    passage_alignment_min_score: float = 0.58
    passage_alignment_weight_dense: float = 0.35
    passage_alignment_weight_lexical: float = 0.35
    passage_alignment_weight_reranker: float = 0.15
    passage_alignment_weight_position: float = 0.15
    change_classifier_provider: str = "fake"
    change_classifier_model: str = "deterministic-disclosure-change-v1"
    change_classifier_timeout: float = 30.0
    materiality_weight_novelty: float = 0.25
    materiality_weight_risk: float = 0.25
    materiality_weight_uncertainty: float = 0.20
    materiality_weight_section: float = 0.15
    materiality_weight_numeric: float = 0.15

    claim_extractor_provider: str = "fake"
    claim_extractor_model: str = "deterministic-financial-claim-extractor-v1"
    claim_extractor_timeout: float = 30.0
    metric_resolution_min_confidence: float = 0.75
    xbrl_fact_min_score: float = 0.72
    xbrl_fact_ambiguity_margin: float = 0.03
    claim_absolute_tolerance: float = 0.01
    claim_percent_tolerance: float = 0.25
    claim_percentage_point_tolerance: float = 0.10
    financial_verification_version: str = "phase4-v1"
    contradiction_policy_version: str = "phase5-v1"
    contradiction_classifier_provider: str = "fake"
    contradiction_classifier_model: str = "deterministic-contradiction-classifier-v1"
    contradiction_classifier_timeout: float = 30.0
    contradiction_small_percent_threshold: float = 1.0
    contradiction_large_percent_threshold: float = 15.0
    contradiction_small_percentage_point_threshold: float = 0.5
    contradiction_large_percentage_point_threshold: float = 5.0
    analysis_workflow_version: str = "phase6-v1"
    analysis_graph_version: str = "phase6-langgraph-v1"
    analysis_report_version: str = "phase6-report-v1"
    workflow_checkpoint_provider: str = "memory"
    workflow_require_review_for_all_contradictions: bool = False
    workflow_review_min_severity: str = "high"
    workflow_review_low_confidence_threshold: float = 0.70
    workflow_review_ambiguous_financial_claims: bool = True
    workflow_max_node_attempts: int = 3

    @field_validator("sec_user_agent")
    @classmethod
    def validate_sec_user_agent(cls, value: str) -> str:
        if "@" not in value and "contact" not in value.lower():
            raise ValueError("SEC User-Agent must include contact information.")
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("Database URLs must use the postgresql+asyncpg driver.")
        return value

    @field_validator("alembic_database_url")
    @classmethod
    def validate_alembic_database_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ValueError("ALEMBIC_DATABASE_URL must use a synchronous PostgreSQL driver.")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must start with redis:// or rediss://.")
        return value

    @model_validator(mode="after")
    def validate_profile_and_aliases(self) -> Settings:
        if self.alembic_database_url is None:
            self.alembic_database_url = _sync_database_url(self.database_url)
        if self.embedding_dimension != self.embedding_dimensions:
            raise ValueError("EMBEDDING_DIMENSION and EMBEDDING_DIMENSIONS must match.")
        if self.embedding_model_name != self.embedding_model:
            raise ValueError("EMBEDDING_MODEL and EMBEDDING_MODEL_NAME must match.")
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be less than CHUNK_MAX_TOKENS.")
        _require_positive_int("DATABASE_POOL_SIZE", self.database_pool_size)
        _require_non_negative("DATABASE_MAX_OVERFLOW", self.database_max_overflow)
        _require_non_negative(
            "DATABASE_POOL_TIMEOUT_SECONDS",
            self.database_pool_timeout_seconds,
        )
        _require_unit_interval("SECTION_MATCH_MIN_SCORE", self.section_match_min_score)
        _require_unit_interval("PASSAGE_ALIGNMENT_MIN_SCORE", self.passage_alignment_min_score)
        _require_weight_sum(
            "SECTION_MATCH",
            [
                self.section_match_weight_structural,
                self.section_match_weight_heading,
                self.section_match_weight_dense,
                self.section_match_weight_lexical,
                self.section_match_weight_reranker,
                self.section_match_weight_position,
            ],
        )
        _require_weight_sum(
            "PASSAGE_ALIGNMENT",
            [
                self.passage_alignment_weight_dense,
                self.passage_alignment_weight_lexical,
                self.passage_alignment_weight_reranker,
                self.passage_alignment_weight_position,
            ],
        )
        _require_weight_sum(
            "MATERIALITY",
            [
                self.materiality_weight_novelty,
                self.materiality_weight_risk,
                self.materiality_weight_uncertainty,
                self.materiality_weight_section,
                self.materiality_weight_numeric,
            ],
        )
        _require_unit_interval(
            "METRIC_RESOLUTION_MIN_CONFIDENCE",
            self.metric_resolution_min_confidence,
        )
        _require_unit_interval("XBRL_FACT_MIN_SCORE", self.xbrl_fact_min_score)
        _require_unit_interval("XBRL_FACT_AMBIGUITY_MARGIN", self.xbrl_fact_ambiguity_margin)
        _require_non_negative("CLAIM_EXTRACTOR_TIMEOUT", self.claim_extractor_timeout)
        _require_non_negative("CLAIM_ABSOLUTE_TOLERANCE", self.claim_absolute_tolerance)
        _require_non_negative("CLAIM_PERCENT_TOLERANCE", self.claim_percent_tolerance)
        _require_non_negative(
            "CLAIM_PERCENTAGE_POINT_TOLERANCE",
            self.claim_percentage_point_tolerance,
        )
        _require_non_negative(
            "CONTRADICTION_CLASSIFIER_TIMEOUT",
            self.contradiction_classifier_timeout,
        )
        _require_non_negative(
            "CONTRADICTION_SMALL_PERCENT_THRESHOLD",
            self.contradiction_small_percent_threshold,
        )
        _require_non_negative(
            "CONTRADICTION_LARGE_PERCENT_THRESHOLD",
            self.contradiction_large_percent_threshold,
        )
        _require_non_negative(
            "CONTRADICTION_SMALL_PERCENTAGE_POINT_THRESHOLD",
            self.contradiction_small_percentage_point_threshold,
        )
        _require_non_negative(
            "CONTRADICTION_LARGE_PERCENTAGE_POINT_THRESHOLD",
            self.contradiction_large_percentage_point_threshold,
        )
        _require_unit_interval(
            "WORKFLOW_REVIEW_LOW_CONFIDENCE_THRESHOLD",
            self.workflow_review_low_confidence_threshold,
        )
        _require_positive_int("WORKFLOW_MAX_NODE_ATTEMPTS", self.workflow_max_node_attempts)
        _require_positive_int("AUTH_TOKEN_TTL_SECONDS", self.auth_token_ttl_seconds)
        if self.auth_login_role not in {"analyst", "reviewer", "admin"}:
            raise ValueError("AUTH_LOGIN_ROLE must be analyst, reviewer, or admin.")
        _require_non_negative("AI_PROVIDER_TIMEOUT_SECONDS", self.ai_provider_timeout_seconds)
        _require_positive_int("AI_PROVIDER_MAX_RETRIES", self.ai_provider_max_retries)
        if self.ai_provider_input_token_cost_usd_per_million is not None:
            _require_non_negative(
                "AI_PROVIDER_INPUT_TOKEN_COST_USD_PER_MILLION",
                self.ai_provider_input_token_cost_usd_per_million,
            )
        if self.ai_provider_output_token_cost_usd_per_million is not None:
            _require_non_negative(
                "AI_PROVIDER_OUTPUT_TOKEN_COST_USD_PER_MILLION",
                self.ai_provider_output_token_cost_usd_per_million,
            )
        if self.workflow_review_min_severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("WORKFLOW_REVIEW_MIN_SEVERITY must be low, medium, high, or critical.")
        if self.workflow_checkpoint_provider not in {"memory", "postgres"}:
            raise ValueError("WORKFLOW_CHECKPOINT_PROVIDER must be memory or postgres.")
        if "*" in self.cors_origins and self.is_production:
            raise ValueError("Production CORS origins must be explicit.")
        if self.is_production:
            self._validate_production_profile()
        if self.environment == "production" and self.app_profile != "production":
            raise ValueError("ENVIRONMENT=production requires APP_PROFILE=production.")
        if self.is_production and self.workflow_checkpoint_provider != "postgres":
            raise ValueError("Production workflow checkpointing must use PostgreSQL.")
        if self.is_production:
            if not self.auth_enabled:
                raise ValueError("Production must enable authentication.")
            if not self.auth_secret_key or _is_placeholder_secret(self.auth_secret_key):
                raise ValueError("Production AUTH_SECRET_KEY must be a non-placeholder secret.")
            if self.auth_login_password is not None and _is_placeholder_secret(
                self.auth_login_password
            ):
                raise ValueError("Production AUTH_LOGIN_PASSWORD must be a non-placeholder secret.")
        if self.app_profile == "docker":
            _require_host(self.database_url, "postgres", "DATABASE_URL")
            _require_host(self.redis_url, "redis", "REDIS_URL")
            if self.object_storage_provider != "minio":
                raise ValueError("APP_PROFILE=docker requires OBJECT_STORAGE_PROVIDER=minio.")
        if self.app_profile == "local-cloud" and self.object_storage_provider != "filesystem":
            raise ValueError(
                "APP_PROFILE=local-cloud uses OBJECT_STORAGE_PROVIDER=filesystem "
                "for Docker-free development."
            )
        return self

    def require_safe_test_database(self) -> None:
        app_db = _database_name(self.database_url)
        test_db = _database_name(self.test_database_url)
        if self.database_url == self.test_database_url:
            raise ValueError("TEST_DATABASE_URL must not equal DATABASE_URL.")
        if "test" not in test_db.lower():
            raise ValueError(
                "Refusing destructive integration tests: test database name must contain 'test'."
            )
        if app_db == test_db:
            raise ValueError(
                "Refusing destructive integration tests: app and test database names match."
            )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def is_production(self) -> bool:
        return self.environment == "production" or self.app_profile == "production"

    def _validate_production_profile(self) -> None:
        if self.object_storage_provider == "filesystem":
            raise ValueError("Production must use S3-compatible object storage.")
        if not self.readiness_dependency_checks_enabled:
            raise ValueError("Production must enable readiness dependency checks.")
        for origin in self.cors_origins:
            parsed = urlparse(origin)
            if parsed.scheme != "https":
                raise ValueError("Production CORS origins must use HTTPS.")
            if parsed.hostname in {"localhost", "127.0.0.1"}:
                raise ValueError("Production CORS origins must not point at localhost.")
        if _is_placeholder_contact(self.sec_user_agent):
            raise ValueError("Production SEC_USER_AGENT must include a real contact address.")
        if self.minio_access_key == "minioadmin" or self.minio_secret_key == "minioadmin":
            raise ValueError("Production object-storage credentials must not use demo defaults.")
        if not self.allow_fake_models_in_production:
            fake_fields = {
                "EMBEDDING_PROVIDER": self.embedding_provider,
                "CHANGE_CLASSIFIER_PROVIDER": self.change_classifier_provider,
                "CLAIM_EXTRACTOR_PROVIDER": self.claim_extractor_provider,
                "CONTRADICTION_CLASSIFIER_PROVIDER": self.contradiction_classifier_provider,
            }
            if self.reranker_enabled:
                fake_fields["RERANKER_PROVIDER"] = self.reranker_provider
            fake = [name for name, value in fake_fields.items() if value == "fake"]
            if fake:
                raise ValueError(
                    "Production fake model providers are disabled: " + ", ".join(sorted(fake))
                )
        if self._uses_openai_compatible_provider() and not self.ai_provider_api_key:
            raise ValueError("Production OpenAI-compatible providers require AI_PROVIDER_API_KEY.")
        if self.embedding_provider == "huggingface_inference" and not self.hf_token:
            raise ValueError("Production Hugging Face inference embeddings require HF_TOKEN.")

    def _uses_openai_compatible_provider(self) -> bool:
        providers = {
            self.embedding_provider,
            self.change_classifier_provider,
            self.claim_extractor_provider,
            self.contradiction_classifier_provider,
        }
        if self.reranker_enabled:
            providers.add(self.reranker_provider)
        return "openai_compatible" in providers


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _sync_database_url(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1))
    query = parsed.query.replace("ssl=require", "sslmode=require")
    return parsed._replace(query=query).geturl()


def _require_host(url: str, expected: str, name: str) -> None:
    actual = urlparse(url).hostname
    if actual != expected:
        raise ValueError(f"{name} must use host '{expected}' for APP_PROFILE=docker.")


def _is_placeholder_contact(value: str) -> bool:
    lowered = value.lower()
    return "example.com" in lowered or "your-email" in lowered


def _is_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    return lowered in {"change-me", "secret", "password"} or len(value) < 32


def _require_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0.")


def _require_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0.")


def _require_positive_int(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")


def _require_weight_sum(name: str, values: list[float]) -> None:
    for value in values:
        _require_unit_interval(f"{name} weight", value)
    if abs(sum(values) - 1.0) > 0.0001:
        raise ValueError(f"{name} weights must sum to 1.0.")
