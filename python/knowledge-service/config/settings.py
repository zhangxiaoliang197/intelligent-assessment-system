import os
from typing import Optional

class Config:
    SERVICE_NAME = "knowledge-service"
    SERVICE_VERSION = "1.0.0"
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8001"))

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "104857600"))

    VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "chroma")
    VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./vector_db")

    LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:8000/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def get_config(cls):
        return {
            "service_name": cls.SERVICE_NAME,
            "version": cls.SERVICE_VERSION,
            "host": cls.HOST,
            "port": cls.PORT,
            "upload_dir": cls.UPLOAD_DIR,
            "vector_db": {
                "type": cls.VECTOR_DB_TYPE,
                "path": cls.VECTOR_DB_PATH
            },
            "llm": {
                "api_url": cls.LLM_API_URL,
                "has_api_key": bool(cls.LLM_API_KEY)
            }
        }
