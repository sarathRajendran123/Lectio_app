# Setup guide

The current, tested instructions are in [README.md](README.md) and [START_HERE_WINDOWS.txt](START_HERE_WINDOWS.txt).

The previous setup assumed Docker services and a shared default administrator password. Those assumptions no longer apply. Local setup now generates private credentials and uses the explicit `local_test` configuration. Live mode retains PostgreSQL, multilingual BGE-M3 embeddings and OpenRouter; verify those services separately before using live analysis.
