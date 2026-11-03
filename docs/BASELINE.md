# Baseline assessment

Source: supplied LECTIO_APP.zip; academic reference: supplied Lectio exposé, four pages.
Stack: FastAPI / SQLAlchemy async PostgreSQL, Streamlit, LangGraph, Groq, BGE / Chroma + BM25. No Paperclip implementation and no tests found.

Initial environment: no FastAPI, SQLAlchemy, Streamlit, LangGraph, PostgreSQL server, Docker or model cache. Baseline cannot start without dependencies and configuration. No original .env values were used or copied into deliverables.

Inspection failures: missing object-level authorization in workflow endpoints and nested resources; default bootstrap password; JWT roles not revalidated; failed login count rolled back on 401; logout UUID/string mismatch; launch before commit; synchronous graph blocks event loop; report persistence failures swallowed; absent evidence reported as pass; rank-normalization creates spurious perfect relevance; metadata used as evidence for its own objectives; unbounded upload read; duplicate files orphaned; no OOXML bomb validation; PDF page count lost after close; empty parses succeed; no guaranteed failure state when RAG initialization fails; no embedding invalidation on delete; source IDs lost in gap rows; no user-triggered generation API.

Existing functionality retained: course/module/week/topic/objective CRUD, role administration, file parsers, LangGraph director and specialized agents, approval records, Streamlit pages and analytics.
