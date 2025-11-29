# Daily Lesson Plan Queue System

A simple, mobile-first Progressive Web App (PWA) for managing daily learning topics for early childhood education (ages 2-3+).

## 📱 Live Demo

**Test it now:** Open `docs/index.html` in your browser or visit the deployed version.

## ✨ Features

- **Three Independent Queues:**
  - 🎨 Arts & Culture (198 topics)
  - 🧠 Knowledge & Skills (118 topics)
  - ⚽ Physical Activities (117 topics)

- **Queue Operations:**
  - ✓ **Select**: Mark topic as complete
  - ⏭️ **Skip**: Move to end of queue
  - 🔧 **Needs Work**: Flag for development queue

- **Mobile-First Design:**
  - Touch-optimized interface (44px+ buttons)
  - Responsive layout
  - Works offline as PWA
  - Add to home screen on iOS/Android

- **Data Management:**
  - 📥 Export data as JSON
  - 📤 Import data from JSON
  - 💾 Automatic save to localStorage
  - 🔄 Automatic queue refill with cycle tracking

- **Zero Cost:**
  - No server required
  - No database required
  - Host free on GitHub Pages, Cloudflare Pages, or Netlify
  - Works completely offline

## 🚀 Quick Start

### Option 1: Run Locally

```bash
cd docs
python3 -m http.server 8000
# Open http://localhost:8000 in your browser
```

### Option 2: Deploy to GitHub Pages

1. Push this repository to GitHub
2. Go to repo Settings → Pages
3. Select branch `master` and folder `/docs`
4. Save and wait ~1 minute
5. Access at `https://yourusername.github.io/lesson-plans/`

### Option 3: Deploy to Cloudflare Pages

1. Connect your GitHub repository
2. Set build directory: `docs`
3. Leave build command empty (static files)
4. Deploy!

## 📂 Project Structure

```
lesson-plans/
├── docs/                      # PWA application (deploy this folder)
│   ├── index.html           # Main app
│   ├── manifest.json        # PWA manifest
│   ├── sw.js               # Service worker
│   ├── initial-data.json   # Initial topic data (433 items)
│   ├── .htaccess           # Apache config (optional)
│   └── README.md           # App documentation
├── planning/               # Project planning documents
│   └── research/          # Technology research
│       ├── static-pwa-architecture.md
│       └── archive/
├── topics.py              # Source topic data (Python)
├── convert_topics.py      # Data conversion script
├── REQUIREMENTS.md        # Full project requirements
├── CLAUDE.md             # Claude Code documentation
└── README.md             # This file
```

## 🛠️ Technology Stack

- **Frontend**: Alpine.js 3.x (14KB) + Tailwind CSS
- **Storage**: localStorage (browser-based)
- **Hosting**: Static files (any static host)
- **Build Tools**: None! Pure HTML/CSS/JS via CDN

### Why This Stack?

✅ **No build tools** - Edit HTML and refresh
✅ **No server** - Works completely client-side
✅ **No database** - localStorage handles everything
✅ **Fast** - Loads in <1 second on mobile
✅ **Offline** - Service worker caches everything
✅ **Free** - Zero hosting costs

## 📊 Data Flow

### Initial Setup
```
topics.py → convert_topics.py → docs/initial-data.json
                                        ↓
                                  localStorage
                                        ↓
                                   User's browser
```

### Daily Use
```
User selects topic → localStorage updated → Export JSON (optional)
                                                  ↓
                                            Share with family
                                                  ↓
                                        Import on other device
```

## 🔄 Cross-Device Sync

**Manual Sync (Recommended):**

1. **Device A**: Select topics → Menu → "Export Data"
2. Share JSON file via text/email/AirDrop
3. **Device B**: Menu → "Import Data" → Select JSON file

**Why Manual?**
- Simplest implementation (no OAuth, no APIs)
- Works offline completely
- Full data control
- Perfect for 2-3 family members using once daily

**Upgrade Path:**
- Can add automatic sync via remoteStorage.js (Dropbox/Google Drive)
- See `planning/research/static-pwa-architecture.md` for details

## 📈 Usage Stats

The app tracks:
- Completed topics (per queue, per date)
- Queue position and cycle number
- Topics flagged for development
- Completion history

Access via menu:
- **View History**: See completion count
- **Development Queue**: Review flagged topics
- **Export Data**: Download full history as JSON

## 🎯 Requirements Coverage

| Requirement | Status | Implementation |
|------------|--------|----------------|
| Mobile-first (44px touch targets) | ✅ | Tailwind CSS utilities |
| 2-3 concurrent users | ✅ | Manual export/import sync |
| Select topics <60 seconds | ✅ | Fast localStorage, simple UI |
| Cost $0-10/month | ✅ | Free static hosting |
| Works offline | ✅ | PWA + service worker |
| 433 topics support | ✅ | ~200KB < 5MB localStorage limit |
| Auto-refill queues | ✅ | Refill when queue empties |
| Development queue | ✅ | Flag topics for revision |
| Completion logging | ✅ | Date-stamped records |

**Trade-off:** Manual sync instead of real-time (5-second requirement). Acceptable for once-daily family use.

## 🔧 Development

### Regenerate Data from topics.py

If you update `topics.py`:

```bash
python3 convert_topics.py
```

This regenerates `docs/initial-data.json`.

### Add New Topics

1. Edit `topics.py` (add to appropriate category)
2. Run `python3 convert_topics.py`
3. Deploy updated `initial-data.json`
4. Users import new data or reset app

### Modify UI

Edit `docs/index.html` directly:
- Alpine.js logic is in `<script>` at bottom
- Tailwind classes are inline
- No build step needed - just refresh browser

## 📱 Mobile Testing

Test on real devices:

1. Deploy to GitHub Pages (or use ngrok/localtunnel)
2. Open on iPhone/Android
3. Test:
   - Touch targets (should be easy to tap)
   - Select/Skip/Flag operations
   - Export/Import workflow
   - Add to home screen
   - Offline mode (turn off WiFi)

## 🐛 Troubleshooting

**App won't load initial data?**
- Check browser console for errors
- Ensure `initial-data.json` is in same folder as `index.html`
- Try hard refresh (Cmd/Ctrl + Shift + R)

**Lost data after closing browser?**
- Data should persist in localStorage
- Check if browser is in private/incognito mode (localStorage disabled)
- Export data regularly as backup

**Import fails?**
- Ensure JSON file is from this app
- Check JSON is valid (use JSON validator)
- Try exporting again from working device

**Service worker not registering?**
- Must be served over HTTPS (or localhost)
- Check browser console for errors
- Try unregistering and re-registering

## 🚢 Deployment Checklist

Before deploying to production:

- [ ] Test on real mobile devices (iOS + Android)
- [ ] Verify touch targets are 44px+ and easy to tap
- [ ] Test export/import workflow between devices
- [ ] Test offline mode (disconnect WiFi)
- [ ] Test "Add to Home Screen" on iOS and Android
- [ ] Verify service worker caches all assets
- [ ] Test with 0 topics in queue (refill logic)
- [ ] Test development queue workflow
- [ ] Verify completion log accuracy

## 📖 Documentation

- **App Usage**: See `docs/README.md`
- **Requirements**: See `REQUIREMENTS.md`
- **Research**: See `planning/research/static-pwa-architecture.md`
- **Claude Code Guide**: See `CLAUDE.md`

## 🎉 Success Criteria

The app meets requirements when:

- ✅ All three queues are functional
- ✅ Users can select, skip, and flag topics
- ✅ Completion log records all selections
- ✅ Development queue stores flagged topics
- ✅ Export/import works for cross-device sync
- ✅ Queues automatically refill when cycles complete
- ✅ Accessible via mobile device (PWA)
- ✅ Multiple users can access without conflicts (via sync)
- ✅ Daily topic selection takes under 60 seconds
- ✅ System costs under $10/month (actually $0!)

## 🔮 Future Enhancements

Possible upgrades:

- **Auto-sync**: Add remoteStorage.js for Dropbox/Google Drive sync
- **Toast notifications**: Better user feedback
- **Analytics**: Track topic popularity, skip rates
- **Scheduling**: Schedule topics for specific dates
- **Themes**: Dark mode, custom colors
- **Search/Filter**: Find specific topics quickly
- **Share topics**: Share individual topics via URL

See `planning/research/static-pwa-architecture.md` for implementation details.

## 📄 License

MIT License - Use freely for your family or educational institution.

## 🤝 Contributing

This is a personal family project, but suggestions are welcome!

1. Open an issue with your idea
2. Fork and create a feature branch
3. Test on mobile devices
4. Submit pull request

## 🙏 Acknowledgments

- Built with Alpine.js and Tailwind CSS
- Inspired by early childhood education best practices
- Designed for simplicity and family use

---

**Made with ❤️ for early learners**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
