# User Story: Google Drive Mount RAG Indexing

**Status:** ✅ Done — 2026-03-04  
**Priority:** C (Could Have)  
**Phase:** 2 — File & Workspace Integration (extension)

## Summary

As Dale, I want Remy to index and search files on my locally mounted Google Drive so that I can find and read CVs, contracts, and other reference material via natural language and file search, just like local files.

---

## Background

Remy's RAG file index covers `~/Projects`, `~/Documents`, and `~/Downloads` (and optionally custom `RAG_INDEX_PATHS`). Dale's Google Drive is mounted locally. On macOS with Google Drive for Desktop the path is typically `~/Library/CloudStorage/GoogleDrive-<your-email>` (not `~/GoogleDrive`). These are currently invisible to Remy's file search and `read_file`.

---

## Acceptance Criteria

- [x] `GDRIVE_MOUNT_PATHS` env var accepted and validated at startup
- [x] If the mount is not available at startup, Remy logs a warning and continues (graceful degradation)
- [x] Files under configured mount path(s) are indexed by the RAG pipeline
- [x] `search_files` returns results from Drive-mounted files
- [x] `read_file` can open files from the mount path (path validation updated)
- [x] `index_status` reports the Drive mount path(s) and file count
- [x] Re-index on demand via `trigger_reindex` (existing tool)

---

## Implementation

- **Config:** `GDRIVE_MOUNT_PATHS` comma-separated; parsed and expanded; only paths that exist and are readable are used; missing paths log a warning.
- **Allowed dirs:** `allowed_base_dirs` includes validated Drive mount paths so `read_file`, `/read`, `/ls`, `/find`, etc. allow access.
- **RAG indexer:** FileIndexer receives base paths plus validated Drive mount paths; same chunking, embedding, and retrieval pipeline.
- **index_status:** Already lists all index paths; Drive paths appear in the paths list.

---

## Notes

- Mount path is configurable via `GDRIVE_MOUNT_PATHS`. On macOS (Google Drive for Desktop) use `~/Library/CloudStorage/GoogleDrive-<your-email>` (e.g. `~/Library/CloudStorage/GoogleDrive-hello@dalerogers.com.au`). The path `~/GoogleDrive` is not used by the official app.
- No new dependencies; same indexer, additional allowed base dirs.
- Security: path traversal protections unchanged; mount paths explicitly allowlisted.
- Out of scope: real-time Drive sync watching, Google Drive API (cloud-only) indexing.
