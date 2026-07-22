import os

QA_SERVICE_URL = os.getenv("QA_SERVICE_URL", "http://localhost:10253")
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")
EVALUATION_API_URL = os.getenv("EVALUATION_API_URL", "http://localhost:10253")

MAX_CONTEXT_ROUNDS = int(os.getenv("INDICATOR_CONTEXT_ROUNDS", "5"))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')


class Stage:
    ANALYZING = "analyzing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUERYING = "querying"
    DONE = "done"


class QueryType:
    CONCEPT_QA = "concept_qa"
    INDICATOR_ANALYSIS = "indicator_analysis"
    GENERAL_CHAT = "general_chat"