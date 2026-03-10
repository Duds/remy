# User Story: Add PDF and DOCX to RAG Indexing

**Status:** ✅ Done — 2026-03-04  
**Priority:** C (Could Have)  
**Phase:** 2 — File & Workspace Integration (extension)

## Summary

As Dale, I want PDF and Word (.docx) files to be indexed by Remy's file indexer so that I can search and find content in contracts, CVs, reports, and other documents via natural language and `search_files`, not just plain-text files. Image-only or image-heavy PDFs should be indexed using OCR so that scanned documents are searchable too.

---

## Background

The RAG file indexer in `remy/memory/file_index.py` only indexes **plain-text** files: it reads raw bytes, decodes as UTF-8, and skips any content that looks binary. Supported extensions are listed in `DEFAULT_INDEX_EXTENSIONS` (e.g. `.md`, `.txt`, `.py`, `.json`, `.csv`, `.html`). PDF and DOCX are binary formats, so they are never indexed today—even if their extensions were added, the existing `_is_binary()` check would skip them.

To support PDF and DOCX we need a **text extraction** step before chunking and embedding: use libraries to get plain text from the document, then feed that text into the existing chunk/embed pipeline. For PDFs that yield little or no extractable text (e.g. scanned pages, image-only PDFs), we add an **OCR** step: render pages to images and run Tesseract (or equivalent) to produce text, then index that.

**Related:** `remy/memory/file_index.py` (FileIndexer, `_index_file`, `DEFAULT_INDEX_EXTENSIONS`), `config.py` (`rag_index_extensions`).

---

## Acceptance Criteria

1. **PDF indexing.** Files with extension `.pdf` are considered indexable. For each PDF, extracted text is chunked and embedded; chunks are stored in `file_chunks` and returned by `search_files`.
2. **PDF OCR fallback.** If a PDF yields no or negligible extractable text (e.g. scanned/image-only pages), the indexer runs OCR on the page images and indexes the resulting text. Image-only or image-heavy PDFs become searchable.
3. **DOCX indexing.** Files with extension `.docx` are considered indexable. For each DOCX, extracted text is chunked and embedded; same storage and search behaviour as PDF.
4. **Graceful degradation.** If text extraction or OCR fails for a file (corrupted, password-protected, unsupported variant), the indexer logs a warning, skips that file, and continues. No crash; other files are still indexed.
5. **Existing behaviour unchanged.** All currently indexed extensions (e.g. `.md`, `.txt`, `.py`) continue to be read as plain UTF-8; no regression in indexing or search.
6. **Size limit respected.** PDF/DOCX files are subject to the same `MAX_FILE_SIZE` (or configured) limit before extraction; larger files are skipped.
7. **Dependencies documented.** New dependencies (e.g. `pypdf`, `python-docx`, OCR stack) are added to `requirements.txt` and docs; system dependency (e.g. Tesseract) documented where required.

---

## Implementation

**Files:**

- `remy/memory/file_index.py` — add `.pdf` and `.docx` to default extensions (or a dedicated set for “extract-first” types); add a text-extraction layer used only for these extensions; keep existing plain-text path for all other extensions.
- `remy/memory/doc_extractors.py` (or equivalent) — PDF text extraction, plus OCR path for PDFs that yield little/no text.
- `requirements.txt` — add `pypdf`, `python-docx`, and OCR dependencies (e.g. `pytesseract`, `pdf2image` or `pymupdf`; Tesseract binary documented in README/setup).

### Approach

1. **Extensions.** Add `.pdf` and `.docx` to `DEFAULT_INDEX_EXTENSIONS` in `file_index.py` (or introduce `BINARY_DOC_EXTENSIONS` and union with defaults so config `rag_index_extensions` can still override).

2. **Extractors.** Implement helpers (e.g. in `remy/memory/doc_extractors.py`):
   - `extract_text_from_pdf(path: Path) -> str | None` — use pypdf to get text from each page. If the result is empty or below a small character threshold (e.g. &lt; 50 chars per page on average), call `extract_text_from_pdf_ocr(path)` and return that instead. Return `None` on failure.
   - `extract_text_from_pdf_ocr(path: Path) -> str | None` — render each page to an image (e.g. via `pdf2image` or `pymupdf`), run Tesseract OCR on each image, concatenate text. Return `None` if OCR unavailable (e.g. Tesseract not installed) or fails.
   - `extract_text_from_docx(path: Path) -> str | None` — use python-docx to get paragraph text; return `None` on failure.

3. **`_index_file` branching.** Before reading raw bytes:
   - If `path.suffix.lower() == '.pdf'`: call `extract_text_from_pdf(path)` (which may use OCR when text extraction yields little); if result is `None`, return 0 and log; otherwise set `content = result` and proceed to chunk/embed.
   - If `path.suffix.lower() == '.docx'`: same with `extract_text_from_docx(path)`.
   - Else: keep current logic (read bytes, reject binary, decode UTF-8, chunk, embed).

4. **Size limit.** Apply existing `_should_index_file` size check (or equivalent) before running extraction so we don’t open huge PDFs/DOCX.

5. **Errors.** Wrap extraction in try/except; log warning with path and exception; return 0 chunks so the file is skipped and the run continues.

### Code sketch

```python
# In file_index.py or doc_extractors.py
def extract_text_from_pdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n\n".join(parts) if parts else None
    except Exception as e:
        logger.debug("PDF extraction failed for %s: %s", path, e)
        return None

def extract_text_from_docx(path: Path) -> str | None:
    try:
        from docx import Document
        doc = Document(path)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.debug("DOCX extraction failed for %s: %s", path, e)
        return None
```

In `_index_file`, after resolving path and before the existing `_read()`:

```python
if path.suffix.lower() == ".pdf":
    content = await asyncio.to_thread(extract_text_from_pdf, path)
elif path.suffix.lower() == ".docx":
    content = await asyncio.to_thread(extract_text_from_docx, path)
else:
    content = await asyncio.to_thread(_read)  # existing logic
if content is None or not content.strip():
    return 0
# then existing chunk + embed loop
```

### OCR notes

- **When to OCR:** If `extract_text_from_pdf` (pypdf) returns fewer than ~50 characters per page on average (or no text at all), treat as image PDF and run OCR.
- **Stack:** `pdf2image` (requires `poppler`) or `pymupdf` to render PDF pages to images; `pytesseract` to call Tesseract. Tesseract must be installed on the system (e.g. `brew install tesseract` on macOS). Document in README or setup guide.
- **Performance:** OCR is slow and CPU-heavy; run extraction (including OCR) in `asyncio.to_thread()`. Consider a config flag to disable OCR (e.g. `RAG_PDF_OCR_ENABLED=false`) if users want text-only PDF indexing.
- **Language:** Default Tesseract language (e.g. `eng`); optional config for additional languages (e.g. `RAG_OCR_LANG=eng+fra`) if needed later.

### General notes

- Use `asyncio.to_thread()` for extraction so the event loop is not blocked.
- Empty or whitespace-only extracted text should yield 0 chunks (same as empty plain-text files).
- If the project prefers a single PDF library: `pypdf` is the maintained fork of PyPDF2; prefer `pypdf` in requirements.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Index a valid PDF with text | Chunks created and stored; `search_files` returns hits for that content. |
| Index a valid DOCX with paragraphs | Chunks created and stored; `search_files` returns hits. |
| PDF extraction fails (corrupt / encrypted) | Warning logged; file skipped; 0 chunks; index run continues. |
| DOCX extraction fails (not a real DOCX) | Warning logged; file skipped; 0 chunks. |
| Existing .md / .txt file | Indexed as today; no behaviour change. |
| PDF or DOCX over `MAX_FILE_SIZE` | Skipped in `_should_index_file`; no extraction attempted. |
| Empty PDF or DOCX (no text) | 0 chunks; no crash. |
| Image-only or scanned PDF | OCR runs; extracted text chunked and indexed; `search_files` returns hits. |
| PDF with mixed text + images | Text extracted first; if sufficient, use it; otherwise OCR fallback for image pages. |
| Tesseract not installed | OCR path logs warning and returns None; PDF skipped (or text-only path still used if pypdf got some text). |

---

## Out of Scope

- **Excel (.xlsx) or PowerPoint (.pptx)** — deferred; can be a follow-up US if needed.
- **Reading PDF/DOCX via `read_file`** — this US is index-only; `read_file` today only reads plain-text files; displaying PDF/DOCX content in chat could be a separate story.
- **Streaming or partial PDF read** — use full file read for extraction; size limit already caps which files are considered.
- **Handwritten or low-quality scans** — OCR quality depends on Tesseract; no special handling for handwriting or heavy noise.
