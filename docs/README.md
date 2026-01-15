# Daily Lesson Plans - PWA

A queue-based lesson plan selector for early childhood education (ages 2-3+).

## Features

- 📱 Mobile-first Progressive Web App
- 🎨 Two independent queues: Knowledge, Skills & Culture; Physical Activities
- 💾 Offline support with localStorage
- 📥 Export/Import data for cross-device sync
- 🔄 Automatic queue refill with cycle tracking
- 🔧 Development queue for topics that need revision
- ✓ Touch-optimized interface (44px+ targets)

## Quick Start

### Option 1: Open Locally

1. Simply open `index.html` in any modern browser
2. The app will load initial data automatically
3. Add to home screen for app-like experience

### Option 2: Deploy to GitHub Pages

1. Push this `app/` folder to a GitHub repository
2. Enable GitHub Pages in repo settings
3. Access from any device at `https://username.github.io/repo-name/`

### Option 3: Deploy to Cloudflare Pages / Netlify

1. Connect your Git repository
2. Set build directory to `app/`
3. Deploy (no build command needed - static files only)

## Usage

### Daily Topic Selection

1. Open the app
2. Review the current topic from each queue
3. For each topic, choose:
   - **Select This**: Mark complete and move to next
   - **Skip**: Move to end of queue (try again later)
   - **Needs Work**: Flag for development queue

### Cross-Device Sync

**Manual Sync (Recommended for 2-3 users):**

1. After selecting topics, click menu → "Export Data"
2. Share the JSON file via text message, email, or AirDrop
3. On another device, click menu → "Import Data"
4. Upload the JSON file

**Frequency:** Export/import once per day after selecting topics, or when changes are made.

### Managing Data

- **View History**: See completion log
- **Development Queue**: Review topics flagged for revision
- **Reset All Data**: Start fresh (cannot be undone)

## Technical Details

### Tech Stack
- **Frontend**: Alpine.js (14KB) + Tailwind CSS
- **Storage**: localStorage (browser-based, ~200KB used)
- **Hosting**: Static files (any static host)
- **Offline**: Service Worker + Cache API

### Data Structure

Data is stored in localStorage as JSON:

```json
{
  "masterLists": {
    "arts": [...],
    "knowledge": [...],
    "physical": [...]
  },
  "queues": {
    "arts": [1, 5, 3, ...],
    "knowledge": [...],
    "physical": [...]
  },
  "completed": [
    {"topicId": 1, "queue": "arts", "date": "2025-11-29"}
  ],
  "development": [
    {"topicId": 42, "reason": "Too advanced", "dateFlagged": "2025-11-29"}
  ],
  "cycles": {"arts": 1, "knowledge": 1, "physical": 1}
}
```

### Browser Compatibility

- ✅ Chrome / Edge (desktop & mobile)
- ✅ Safari (desktop & mobile)
- ✅ Firefox (desktop & mobile)

### Storage Limits

- localStorage: 5-10MB (we use ~200KB)
- Cache API: 50MB on iOS Safari (we use <5MB)

## Add to Home Screen

### iOS (iPhone/iPad)

1. Open in Safari
2. Tap the Share button
3. Scroll down and tap "Add to Home Screen"
4. Tap "Add"

### Android

1. Open in Chrome
2. Tap the menu (⋮)
3. Tap "Install app" or "Add to Home screen"

## Troubleshooting

**App not loading?**
- Check browser console for errors
- Ensure `initial-data.json` is in the same folder as `index.html`
- Try hard refresh (Ctrl+Shift+R or Cmd+Shift+R)

**Lost data?**
- Data is stored in browser's localStorage
- Clearing browser data will delete it
- Always export data regularly as backup

**Import not working?**
- Ensure JSON file is valid
- Check file was exported from this app
- Try exporting again and re-importing

## Development

### Regenerate Initial Data

If you need to update topics from `topics.py`:

```bash
cd /path/to/lesson-plans
python3 convert_topics.py
```

This will regenerate `app/initial-data.json`.

### Local Testing

```bash
# Simple HTTP server
cd app
python3 -m http.server 8000

# Or use any static file server
npx serve .
```

Then open `http://localhost:8000` in your browser.

## Cost

- **Hosting**: $0 (GitHub Pages, Cloudflare Pages, or Netlify free tier)
- **Storage**: $0 (browser localStorage)
- **Total**: $0/month

## Future Enhancements

Possible upgrades:
- Auto-sync via remoteStorage.js (Dropbox/Google Drive)
- Toast notifications for better feedback
- Advanced filtering/search
- Custom themes
- Analytics dashboard

## License

MIT License - use freely for your family or educational institution.
