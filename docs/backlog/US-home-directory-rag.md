# User Story: Home Directory RAG Index

⬜ Backlog — P3

## Summary
As a user, I want Remy to be able to search across my files in ~/Projects and ~/Documents
semantically — not just files I explicitly read with `read_file` — so that I can ask questions
like "do I have any notes about the fence quote?" and get an answer even if I don't remember
which file it's in.

---

## Background

The current file access model is **pull-only**: Remy can only read a file if the user asks for
it by path, or if a README.md is loaded via `MemoryInjector._get_project_context()`. There is
no background indexing of file content.

The existing `EmbeddingStore` in `drbot/memory/embeddings.py` already stores vectors in
`embeddings_vec` using `all-MiniLM-L6-v2` (384 dims) with sqlite-vec / FTS5 fallback. The
`source_type` column in the `embeddings` table can be extended to include `"file_chunk"` —
no schema changes required to the embeddings infrastructure.

The allowed read paths (`~/Projects`, `~/Documents`, `~/Downloads`) are already defined in
`bot/handlers.py` and enforced by `sanitize_file_path()`. The RAG indexer must respect the
same allowlist and denylist (`.env`, `.ssh/`, `.aws/`, `.git/`).

### Why not ~/Downloads?

`~/Downloads` is volatile (temp files, installers, random downloads). Indexing it would
produce noisy results and could embed sensitive received files. Excluded from scope.

### Why not a separate vector database?

The existing `embeddings` + `embeddings_vec` tables are already functional. Adding a separate
Chroma / Qdrant / Weaviate instance would violate the "minimal dependencies" principle and
add an ops burden. SQLite is sufficient for a single-user home assistant at this scale.

---

## Acceptance Criteria

### 1. Background file indexer

A `FileIndexer` class in `drbot/memory/file_index.py` that:

- Walks `~/Projects` and `~/Documents` (configurable via `settings.rag_index_paths`)
- Skips: `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, binary files, files > 500 KB
- Only indexes text files: `.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`,
  `.csv`, `.html` (configurable via `settings.rag_index_extensions`)
- Splits each file into overlapping chunks of 400 tokens (~300 words), 50-token overlap
- Embeds each chunk via `EmbeddingStore.embed()` and stores in the `file_chunks` table
  (see schema below) + `embeddings_vec`
- Records a `file_index_log` entry per indexed file (path, mtime, chunk count)
- **Incremental**: only re-indexes a file if its `mtime` has changed since last index

### 2. New `file_chunks` table

```sql
CREATE TABLE IF NOT EXISTS file_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,
    content_text TEXT NOT NULL,
    embedding_id INTEGER,
    file_mtime   REAL NOT NULL,
    indexed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_file_chunks_path_chunk
    ON file_chunks(path, chunk_index);

CREATE TABLE IF NOT EXISTS file_index_log (
    path         TEXT PRIMARY KEY,
    file_mtime   REAL NOT NULL,
    chunk_count  INTEGER NOT NULL,
    indexed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`file_chunks.embedding_id` references `embeddings.id` (same join pattern as facts and goals).

### 3. Scheduled re-indexing

`ProactiveScheduler` gains a new job: `_reindex_files`, scheduled nightly at 03:00 (when the
bot is idle). This calls `FileIndexer.run_incremental()` which:
- Scans for new/modified files
- Removes stale chunks for deleted files
- Logs a summary: "Re-indexed N files, M new chunks, K removed"

On startup, if `file_index_log` is empty, a full index runs as a background task (via
`BackgroundTaskRunner`) so startup latency is not affected.

Configurable via `settings.rag_index_enabled` (default: `True`) and
`settings.rag_reindex_cron` (default: `"0 3 * * *"`).

### 4. `search_files` tool

New tool in `tool_registry.py`:

```json
{
  "name": "search_files",
  "description": "Search indexed files in ~/Projects and ~/Documents for content matching a query. Use when the user asks about something that might be in their files but doesn't know which file.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Natural language search query" },
      "limit": { "type": "integer", "description": "Max results (default 5, max 10)" },
      "path_filter": { "type": "string", "description": "Optional subdirectory to restrict search, e.g. '~/Projects/ai-agents'" }
    },
    "required": ["query"]
  }
}
```

Returns results as:
```
📂 File search results for "fence quote":

1. ~/Documents/Home/fence-notes.md (chunk 2)
   "Jim's Fencing quoted $4,200 for 40m of colorbond..."

2. ~/Projects/home-admin/README.md (chunk 1)
   "Fence repair project — see fence-notes.md for quotes received"
```

Chunks are truncated to 200 chars in the result; file path is included so the user can
call `read_file` if they want the full content.

### 5. `index_status` tool

```json
{
  "name": "index_status",
  "description": "Show the current state of the file index: how many files indexed, when last run, which paths.",
  "input_schema": { "type": "object", "properties": {} }
}
```

Returns:
```
📂 File index status:
  Paths: ~/Projects, ~/Documents
  Files indexed: 312 (last run: 2026-02-27 03:00)
  Total chunks: 1,847
  Extensions: .md, .txt, .py, .json (+6 more)
  Next scheduled: 2026-02-28 03:00
```

Natural language: "How many files have you indexed?", "When did you last index my files?"

### 6. `/reindex` command (manual trigger)

`bot/handlers.py` adds a `/reindex` command that triggers `FileIndexer.run_incremental()`
as a `BackgroundTaskRunner` task. Remy replies "Reindexing — I'll let you know when done 🔄"
and sends a summary on completion.

### 7. Security constraints (same as existing file access)

- Indexer uses the same `sanitize_file_path()` allowlist/denylist as `read_file`
- `.env`, `.ssh/`, `.aws/`, `.git/` never indexed
- File content is chunked and stored in the local SQLite DB only — never sent externally
  except when Claude uses a chunk in a reply (same as `read_file`)
- No binary files indexed (check for null bytes before embedding)

---

## Implementation

**New files:**
- `drbot/memory/file_index.py` — `FileIndexer`, `FileChunkStore`

**Modified files:**
- `drbot/memory/database.py` — add `file_chunks` + `file_index_log` DDL + migration
- `drbot/scheduler/proactive.py` — add nightly `_reindex_files` job
- `drbot/ai/tool_registry.py` — add `search_files` + `index_status` tools
- `drbot/bot/handlers.py` — add `/reindex` command
- `drbot/main.py` — instantiate `FileIndexer`, pass to `ToolRegistry` and scheduler
- `drbot/config.py` — add `rag_index_paths`, `rag_index_extensions`, `rag_index_enabled`

**New dependencies:** None. Uses existing `EmbeddingStore`, `aiosqlite`, `asyncio`, and
`pathlib`. Chunking is character-based (no tokeniser needed at this scale).

### Chunking strategy

```python
CHUNK_CHARS = 1500       # ~300 words, fits comfortably in ANN context
OVERLAP_CHARS = 200      # overlap for context continuity at boundaries

def chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start, end)
                if pos > start + CHUNK_CHARS // 2:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end - OVERLAP_CHARS
    return [c for c in chunks if len(c) > 50]  # drop near-empty trailing chunks
```

---

## Performance considerations

- `all-MiniLM-L6-v2` embeds ~500 sentences/second on CPU. A 300-file ~/Projects at ~10
  chunks/file = 3,000 chunks ≈ 6 seconds for a full initial index. Acceptable as a background task.
- Subsequent incremental runs: typically 0–20 modified files per night — negligible.
- sqlite-vec ANN search over 3,000 vectors: sub-millisecond. Even 30,000 vectors is fast.
- In container, sqlite-vec is unavailable (arm64 ELF mismatch); falls back to FTS5 over
  `file_chunks.content_text`. FTS5 handles 30,000 rows trivially.

---

## Test Cases

| Scenario | Expected |
|---|---|
| "Do I have any notes about the fence quote?" | `search_files` returns chunk from fence-notes.md |
| File modified since last index | Re-indexed on next incremental run; old chunks replaced |
| File deleted | Stale chunks removed from `file_chunks` on next run |
| Binary file (e.g. image, PDF) in ~/Projects | Skipped silently |
| File > 500 KB | Skipped; logged at DEBUG level |
| `/reindex` | Background task fires; summary sent when done |
| "How many files have you indexed?" | `index_status` tool returns count + last run time |
| `path_filter` set to `~/Projects/ai-agents` | Only chunks from that subtree returned |
| `settings.rag_index_enabled = false` | `FileIndexer` does nothing; `search_files` returns "indexing disabled" |

---

## Out of Scope

- PDF text extraction (requires `pdfminer` or similar — deferred)
- DOCX / XLSX parsing (deferred)
- Image content indexing (separate from vision; would require OCR)
- Real-time file watching (inotify/FSEvents) — nightly cron is sufficient for now
- Indexing ~/Downloads (too volatile and noisy)
- Multi-user file isolation (single-user bot; all chunks are user-agnostic in schema)
- Semantic chunking (topic-aware splits) — character overlap is sufficient for this scale
