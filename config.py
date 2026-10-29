"""环境配置：所有可变项从环境变量 / .env 读取，禁止硬编码。

加载顺序：系统环境变量 > .env.<APP_ENV> > .env
  本地开发：APP_ENV 缺省，读 .env
  生产部署：APP_ENV=production，读 .env.production（PythonAnywhere WSGI 中设置）
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_env = os.getenv("APP_ENV", "")
_env_file = f".env.{_env}" if _env else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", _env_file), env_file_encoding="utf-8", extra="ignore")

    # ---- 数据库（优先级：DATABASE_URL > MySQL 分散配置 > SQLite）----
    # Render / Railway / Fly 等平台会自动注入 DATABASE_URL（PostgreSQL）
    DATABASE_URL: str = ""

    # ---- MySQL（本地开发 / PythonAnywhere 用，Render 部署时留空）----
    MYSQL_HOST: str = ""
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = ""

    # ---- JWT ----
    # 生产环境必须通过环境变量/.env 显式设置强随机密钥；缺省值仅用于本地开发
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 365  # 1 年

    # ---- 文件上传 ----
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_MB: int = 5

    @property
    def database_url(self) -> str:
        """优先级：DATABASE_URL（Render 等注入）> MySQL 分散配置 > SQLite 兜底。"""
        # Render 等平台的 DATABASE_URL 形如 postgres://user:pass@host/db，需转成 SQLAlchemy 方言
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg2://", 1)
            elif url.startswith("postgresql://") and "+psycopg2" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            elif url.startswith("mysql://"):
                url = url.replace("mysql://", "mysql+pymysql://", 1)
            return url
        # 本地开发：MySQL 分散配置
        if self.MYSQL_HOST and self.MYSQL_USER and self.MYSQL_DB:
            return (
                f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
                f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
            )
        # 完全没配置时回退 SQLite
        return "sqlite:///./dev.db"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


settings = Settings()

if not settings.JWT_SECRET:
    if os.getenv("APP_ENV") == "production":
        raise RuntimeError(
            "生产环境必须设置 JWT_SECRET 环境变量（强随机字符串），拒绝启动"
        )
    # 本地开发兜底：随机生成，仅本次进程有效（重启后旧 token 全部失效，开发场景可接受）
    import secrets
    settings.JWT_SECRET = secrets.token_hex(32)
