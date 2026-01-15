# Daily Lesson Plan Queue System

A mobile-first Progressive Web App for managing daily learning topics for early childhood education (ages 2-3+).

## Live Demo

https://natsirtguy.github.io/lesson-plans/

Or test locally: `cd docs && python3 -m http.server 8000`

## Features

**Three Independent Queues:**
- Knowledge, Skills & Culture (316 topics - combined knowledge, skills, creative activities, and cultural activities)
- Physical Activities (117 topics)
- Songs (71 songs with lyrics, ASL signs, and cultural notes)

**Queue Operations:**
- **Select**: Mark topic as complete
- **Skip**: Move to end of queue
- **Needs Work**: Flag for development queue

**Mobile-First Design:**
- Touch-optimized interface (44px+ buttons)
- Responsive layout
- Works offline as PWA
- Add to home screen on iOS/Android

**Data Management:**
- Export/import data as JSON
- Automatic save to localStorage
- Automatic queue refill with cycle tracking

## Quick Start

### Run Locally

```bash
cd docs
python3 -m http.server 8000
# Open http://localhost:8000
```

### Deploy to GitHub Pages

1. Push this repository to GitHub
2. Go to repo Settings → Pages
3. Select branch `master` and folder `/docs`
4. Access at `https://yourusername.github.io/lesson-plans/`

## Project Structure

```
lesson-plans/
├── docs/                      # PWA application (deploy this folder)
│   ├── index.html             # Main app
│   ├── manifest.json          # PWA manifest
│   ├── sw.js                  # Service worker
│   ├── initial-data.json      # Initial topic data
│   └── lessons/               # Lesson plan content
│       ├── knowledge/         # Knowledge, Skills & Culture lesson plans
│       ├── physical/          # Physical Activities lesson plans
│       └── songs/             # Song lesson plans (lyrics, ASL, cultural notes)
├── topics.py                  # Source topic data (Python)
├── convert_topics.py          # Data conversion script
└── CLAUDE.md                  # Claude Code documentation
```

## Technology Stack

- **Frontend**: Alpine.js 3.x + Tailwind CSS (via CDN)
- **Storage**: localStorage (browser-based)
- **Hosting**: Static files (any static host, zero cost)

## Cross-Device Sync

Manual sync via export/import:

1. **Device A**: Menu → "Export Data"
2. Share JSON file via text/email/AirDrop
3. **Device B**: Menu → "Import Data" → Select JSON file

## Development

### Regenerate Data from topics.py

```bash
python3 convert_topics.py
```

### Modify UI

Edit `docs/index.html` directly—no build step needed.

## Troubleshooting

**App won't load initial data?**
- Check browser console for errors
- Try hard refresh (Cmd/Ctrl + Shift + R)

**Lost data after closing browser?**
- Check if browser is in private/incognito mode
- Export data regularly as backup

**Service worker not registering?**
- Must be served over HTTPS (or localhost)

## License

MIT License
