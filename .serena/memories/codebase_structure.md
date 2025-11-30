# Codebase Structure

## Directory Tree
```
lesson-plans/
├── docs/                      # PWA application (deployable)
│   ├── index.html            # Main app (Alpine.js + Tailwind)
│   ├── manifest.json         # PWA manifest
│   ├── sw.js                # Service worker for offline
│   ├── initial-data.json    # Initial topic data (433 items)
│   ├── .htaccess            # Apache config (optional)
│   └── README.md            # App-specific documentation
├── planning/                 # Project planning docs
│   └── research/
│       ├── static-pwa-architecture.md
│       └── archive/
│           └── technology-recommendations-server-based.md
├── .serena/                  # Serena MCP server state
├── .claude/                  # Claude Code configuration
├── topics.py                # Source topic data (Python dicts)
├── convert_topics.py        # Data conversion script
├── REQUIREMENTS.md          # Full requirements (v1.1)
├── CLAUDE.md               # Claude Code guidance
├── README.md               # Main project documentation
├── generate-lesson.md      # Lesson plan generator instructions
└── .gitignore
```

## Key Files

### Application Files (docs/)
- **index.html** - Single-page app, contains all HTML/JS/CSS
  - Alpine.js component definition
  - Tailwind utility classes
  - Complete app logic in inline <script>
  
- **initial-data.json** - Initial state for new users
  - Master lists for all 3 queues
  - Initial queue order (randomized)
  - Empty completion/development arrays
  
- **sw.js** - Service worker for offline capability
- **manifest.json** - PWA configuration

### Source Files (root)
- **topics.py** - Python dictionaries with 433 topics
  - KNOWLEDGE_CATEGORIES: 19 categories → Knowledge Queue
  - ACTIVITY_CATEGORIES: 16 categories → Arts Queue  
  - PHYSICAL_ACTIVITIES: 10 categories → Physical Queue

- **convert_topics.py** - Converts topics.py → initial-data.json
  - Assigns IDs to topics
  - Maps categories to queues
  - Randomizes initial order
  - Outputs statistics

### Documentation Files
- **README.md** - Quick start, deployment, architecture
- **REQUIREMENTS.md** - Complete functional requirements (v1.1)
- **CLAUDE.md** - Instructions for Claude Code
- **generate-lesson.md** - Instructions for AI lesson plan generation

## Data Flow

### Initial Setup
```
topics.py → convert_topics.py → docs/initial-data.json
```

### Runtime
```
index.html loads → Check localStorage
├─ If empty → Load initial-data.json → Save to localStorage
└─ If exists → Use localStorage data

User actions → Update localStorage → Update UI
```

### Cross-Device Sync
```
Device A: Export → JSON file → Share via text/email/AirDrop
Device B: Import JSON → Update localStorage
```

## Important Locations

### To modify UI
- Edit `docs/index.html`
- Alpine.js logic in bottom `<script>` tag
- Tailwind classes inline in HTML
- No build step - just refresh browser

### To modify topic data
- Edit `topics.py`
- Run `python3 convert_topics.py`
- Deploy updated `docs/initial-data.json`

### To modify PWA behavior
- Edit `docs/sw.js` (service worker)
- Edit `docs/manifest.json` (PWA config)
