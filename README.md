# Past Paper Question Extractor
### Production Desktop Application — Full Documentation

---

## Table of Contents
1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Technology Decisions](#3-technology-decisions)
4. [Project Structure](#4-project-structure)
5. [Setup — Developer Machine](#5-setup--developer-machine)
6. [Running the App](#6-running-the-app)
7. [How to Use the App](#7-how-to-use-the-app)
8. [Building the Executable (.exe)](#8-building-the-executable-exe)
9. [Sharing with Clients](#9-sharing-with-clients)
10. [Client Setup Requirements](#10-client-setup-requirements)
11. [Multi-PDF Support](#11-multi-pdf-support)
12. [Caching System](#12-caching-system)
13. [Performance Notes](#13-performance-notes)
14. [Troubleshooting](#14-troubleshooting)
15. [Future Improvements](#15-future-improvements)

---

## 1. Overview

A professional desktop application that:
- Imports past paper PDFs (one at a time, over multiple sessions)
- Detects and indexes all questions automatically
- Lets you filter by Level, Subject, Year, Season, Variant, Paper, Question Number
- Shows preview images of matched questions
- Exports selected questions to a clean downloadable PDF

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    UI Layer (CustomTkinter)              │
│  app.py → filter_panel.py → results_panel.py           │
│  import_dialog.py → documents_panel.py                 │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    Core Layer                           │
│  pdf_parser.py      — detect questions via text coords │
│  question_extractor.py — render page regions as images │
│  pdf_exporter.py    — assemble output PDF              │
│  import_worker.py   — background thread for imports    │
└──────────┬───────────────────────┬──────────────────────┘
           │                       │
┌──────────▼──────┐     ┌──────────▼──────────────────────┐
│  SQLite DB      │     │  Disk Cache (diskcache)          │
│  papers.db      │     │  ~/.past_paper_extractor/cache/ │
│  - documents    │     │  Stores rendered page PNGs       │
│  - questions    │     │  LRU eviction, 2GB limit        │
│  - import_log   │     │                                  │
└─────────────────┘     └──────────────────────────────────┘
```

**Data flow for Import:**
```
Select PDF → check duplicate (hash) → insert document record
→ parse questions (pdfplumber) → insert questions batch
→ update status to 'indexed' → warm page 1 cache
```

**Data flow for Search:**
```
User sets filters → SQL WHERE query → list of question rows
→ for each: render crop from PDF (cache-first) → show preview
```

**Data flow for Export:**
```
User selects questions → render at 200 DPI → embed in PDF
→ save to chosen output path
```

---

## 3. Technology Decisions

| Component | Choice | Why |
|-----------|--------|-----|
| GUI | CustomTkinter | Modern look, pure Python, no web server |
| PDF text extraction | pdfplumber | Best coordinate accuracy for question detection |
| PDF rendering | PyMuPDF (fitz) | Fastest renderer, preserves diagrams/images |
| PDF export | ReportLab | Industry standard, precise layout control |
| Database | SQLite (built-in) | Zero config, zero server, fast for this scale |
| Cache | diskcache | Pure Python disk LRU cache, persists across sessions |
| Threading | Python threading | Background workers keep UI responsive |
| Packaging | PyInstaller | Single .exe, no Python needed on client |

**Why NOT Redis, Vector DB, or LLM:**
- Redis = server software, unnecessary for a desktop app
- Vector DB = for fuzzy/semantic search, not exact structured filter
- LLM/RAG = for AI question answering, not for "give me Paper 1 Q2(a)"

---

## 4. Project Structure

```
past_paper_extractor/
│
├── main.py                      # Entry point
├── requirements.txt             # Python dependencies
├── log_config.py                # Logging setup
├── build.bat                    # Windows build script
├── build.sh                     # Linux/Mac build script
├── past_paper_extractor.spec    # PyInstaller config
│
├── core/
│   ├── __init__.py
│   ├── pdf_parser.py            # Detect question boundaries
│   ├── question_extractor.py   # Render page crops as images
│   ├── pdf_exporter.py         # Generate output PDF
│   └── import_worker.py        # Background import thread
│
├── database/
│   ├── __init__.py
│   └── db_manager.py           # All SQLite operations
│
├── cache/
│   ├── __init__.py
│   └── cache_manager.py        # Disk-based image cache
│
├── ui/
│   ├── __init__.py
│   ├── app.py                  # Main window
│   ├── import_dialog.py        # PDF import modal
│   ├── filter_panel.py         # Left sidebar filters
│   ├── results_panel.py        # Question results + export
│   └── documents_panel.py      # Manage imported PDFs
│
└── assets/
    └── (icon files etc.)
```

**Data stored on client machine:**
```
~/.past_paper_extractor/
├── papers.db          # SQLite database (all indexes)
├── cache/             # Rendered page image cache (up to 2GB)
└── logs/
    └── app.log        # Rotating log file
```

---

## 5. Setup — Developer Machine

### Prerequisites
- Python 3.10 or higher
- Git (optional)

### Steps

```bash
# 1. Clone or download the project
cd past_paper_extractor

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

**requirements.txt contents explained:**
```
customtkinter==5.2.2   # Modern Tkinter wrapper
pdfplumber==0.11.0     # PDF text + coordinate extraction
PyMuPDF==1.24.5        # PDF rendering (fitz)
reportlab==4.2.2       # PDF generation for export
Pillow==10.4.0         # Image processing
diskcache==5.6.3       # Disk-based LRU cache
```

---

## 6. Running the App

```bash
# Make sure venv is activated
python main.py
```

On first run, the app automatically creates the SQLite database and cache directory in `~/.past_paper_extractor/`.

---

## 7. How to Use the App

### Step 1: Import a PDF
1. Click **"+ Import PDF"** in the top bar
2. Click **"Choose PDF File"** and select your past paper
3. Fill in metadata: Level, Year, Season, Variant, Paper, Subject
4. Click **"Import PDF"** — a progress bar shows indexing progress
5. Repeat for each new PDF (on any day)

### Step 2: Search
1. Set filters in the left panel (any combination)
2. Leave any filter as "Any" to match all values
3. Click **"Search"**
4. Question cards appear with preview images

### Step 3: Export
1. Check the boxes next to questions you want
2. Click **"Select All"** to select all results
3. Set the output path (bottom bar)
4. Click **"Export Selected → PDF"**

---

## 8. Building the Executable (.exe)

### Windows

```cmd
# Make sure you're in the project folder
build.bat
```

This:
1. Creates/activates a virtual environment
2. Installs all dependencies
3. Installs PyInstaller
4. Compiles everything into a single `.exe`
5. Output: `dist\PastPaperExtractor.exe`

### Linux / macOS

```bash
chmod +x build.sh
./build.sh
# Output: dist/PastPaperExtractor
```

### Notes on the .spec file

If `customtkinter` is in a different location, update the path in `past_paper_extractor.spec`:
```python
datas=[
    ("venv/Lib/site-packages/customtkinter", "customtkinter"),
    # On Linux: ("venv/lib/python3.x/site-packages/customtkinter", "customtkinter"),
],
```

Find the correct path:
```bash
python -c "import customtkinter; print(customtkinter.__file__)"
```

---

## 9. Sharing with Clients

### Option A — Single .exe (Recommended for Windows clients)

After building:
1. Go to the `dist/` folder
2. Copy `PastPaperExtractor.exe`
3. Send this file to your client (USB drive, Google Drive, email, etc.)
4. Client double-clicks the .exe — **no installation needed**

The .exe is self-contained. It includes Python, all libraries, and the app code.

**Expected file size:** ~80–120 MB (compressed with UPX)

### Option B — Installer (Professional)

Use **Inno Setup** (free, Windows) to wrap the .exe in a proper installer:
1. Download Inno Setup from https://jrsoftware.org/isinfo.php
2. Create a simple `.iss` script pointing to your `.exe`
3. Compile to produce `Setup_PastPaperExtractor.exe`
4. Client runs the installer like any normal Windows software

Sample Inno Setup script:
```ini
[Setup]
AppName=Past Paper Extractor
AppVersion=1.0.0
DefaultDirName={autopf}\PastPaperExtractor
OutputBaseFilename=Setup_PastPaperExtractor

[Files]
Source: "dist\PastPaperExtractor.exe"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\Past Paper Extractor"; Filename: "{app}\PastPaperExtractor.exe"
```

### Option C — Python source (Technical clients)

If your client is technical:
1. Share the project folder (zip it)
2. They run `build.bat` themselves
3. Or they run `python main.py` directly after installing Python

---

## 10. Client Setup Requirements

### If sharing the .exe (Option A/B):
**Client needs NOTHING installed.** The .exe works on any Windows 10/11 PC.

### If sharing Python source (Option C):
Client needs:
- Python 3.10 or higher from https://python.org
- Run: `pip install -r requirements.txt`
- Run: `python main.py`

### Disk space:
- App itself: ~100MB
- Database + cache: grows based on usage (cache capped at 2GB)
- Original PDFs: stored wherever client puts them (app doesn't move them)

---

## 11. Multi-PDF Support

The app is designed from the ground up for incremental PDF imports:

**Day 1:** Client imports `paper_2022_oct.pdf`
```
documents: [id=1, file=paper_2022_oct.pdf, status=indexed]
questions: [100 questions linked to doc_id=1]
```

**Day 2:** Client imports `paper_2023_may.pdf`
```
documents: [id=1, ..., id=2, file=paper_2023_may.pdf, status=indexed]
questions: [100 + 95 questions]
```

**Day 3:** Client tries to import `paper_2022_oct.pdf` again
```
→ SHA-256 hash matches → "Already imported" message → No duplicate
```

Search queries automatically span all imported documents. Filters narrow down which papers to search.

**Deleting a document:**
- Removes its record from `documents` table
- Automatically removes all its questions (ON DELETE CASCADE)
- Original PDF file is NOT deleted
- Client can re-import the same PDF later

---

## 12. Caching System

The cache stores rendered PNG images of PDF page regions so the same page is never re-rendered twice.

**Cache location:** `~/.past_paper_extractor/cache/`
**Cache limit:** 2 GB (configurable in `cache_manager.py`)
**Eviction policy:** LRU (least recently used)
**Cache keys:**
```
page::{filepath}::{page_number}::{dpi}
crop::{filepath}::{page_number}::{bbox_json}::{dpi}
```

**When cache helps most:**
- Second and subsequent searches (same questions appear instantly)
- Export (pages already cached from preview)

**When cache misses:**
- First time viewing a question (renders then caches)
- After clearing cache

**Cache management:**
- Click "Cache Info" in status bar to see size
- App auto-evicts old entries when 2GB is reached
- Never manually delete the cache folder (just use the in-app button)

---

## 13. Performance Notes

| Operation | Expected Time | Notes |
|-----------|--------------|-------|
| Import 50-page PDF | 15–30 sec | One-time cost, then instant |
| Search (any filter combo) | < 100ms | SQLite index lookup |
| First question preview | 1–3 sec | Renders + caches image |
| Subsequent previews | < 100ms | Cache hit |
| Export 20 questions | 5–15 sec | Renders at 200 DPI |

**SQLite WAL mode** is enabled which means:
- Reads and writes don't block each other
- Database is safe even if the app crashes mid-write

**Threading:**
- Import runs in a background thread (UI stays responsive)
- Image previews load in background threads (results appear, images fill in)
- Export runs in background thread (progress shown in status bar)

---

## 14. Troubleshooting

### "No questions detected"
- PDF is likely a scanned image, not text-based
- Solution: Run OCR on the PDF first using Adobe Acrobat or free tools like `ocrmypdf`
- Command: `pip install ocrmypdf && ocrmypdf input.pdf output.pdf`

### Question numbers not detected correctly
- Open `core/pdf_parser.py`
- Edit `QUESTION_PATTERNS` list to add your board's format
- Edit `LEFT_MARGIN_TOLERANCE` (default 60 pts) if question numbers are further from the edge

### App opens but looks wrong (missing fonts/icons)
- Re-run the build with the correct customtkinter path in the .spec file

### Cache grows too large
- Open the app → click "Cache Info" → click Yes to clear
- Or manually delete `~/.past_paper_extractor/cache/`

### Database errors
- Close the app
- Delete `~/.past_paper_extractor/papers.db`
- Restart app (db recreated automatically)
- Re-import your PDFs

### Finding logs
```
~/.past_paper_extractor/logs/app.log
```

---

## 15. Future Improvements

| Feature | Effort | Priority |
|---------|--------|----------|
| OCR support for scanned PDFs | Medium | High |
| Topic-based semantic search (RAG) | High | Medium |
| Batch import folder of PDFs | Low | Medium |
| Mark scheme linking | Medium | Medium |
| Question difficulty scoring | High | Low |
| Cloud sync between multiple clients | High | Low |

---

*Built with Python 3.10+ | CustomTkinter | pdfplumber | PyMuPDF | ReportLab | SQLite | diskcache*
