# Static PWA Architecture Research - Daily Lesson Plan Queue System

**Research Date:** November 29, 2025
**Focus:** File-based, static HTML approach with no server

---

## Key Finding: File System Access API Limitations

### ❌ The "Shared Dropbox File" Approach Won't Work on iOS

**Problem:** iOS Safari does NOT support the File System Access API for accessing user files directly.

- ✅ Desktop Chrome/Edge: Full File System Access API support
- ⚠️ iOS Safari: Only Origin Private File System (OPFS) - sandboxed storage within the browser
- ❌ iOS Safari: Cannot read/write files in user's Dropbox/Google Drive folder directly

**Source:** [Can I use File System Access API](https://caniuse.com/native-filesystem-api), [WebKit File System API blog](https://webkit.org/blog/12257/the-file-system-access-api-with-origin-private-file-system/)

**Impact:** We cannot build a simple "open index.html from Dropbox folder" app that reads/writes a shared JSON file on iOS.

---

## Recommended Architecture: Static PWA with localStorage

### Core Stack (No Build Tools, Pure CDN)

```html
<!DOCTYPE html>
<html>
<head>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="//unpkg.com/alpinejs" defer></script>
  <link rel="manifest" href="manifest.json">
</head>
<body>
  <!-- App here -->
</body>
</html>
```

**Tech Stack:**
- **Frontend:** Alpine.js (14KB, "Tailwind for JavaScript") + Tailwind CSS
- **Storage:** localStorage (5MB limit - sufficient for 433 items + logs)
- **Sync:** Manual export/import JSON file
- **Hosting:** GitHub Pages, Cloudflare Pages, or Netlify (all free, no spin-down)
- **PWA:** Service worker for offline + "Add to Home Screen"

**Sources:**
- [Alpine.js 2025 guide](https://amirkamizi.com/blog/alpinejs-beginner-to-advanced-2025)
- [Alpine + Tailwind components](https://devdojo.com/pines)

---

## Storage Options Comparison

### Option A: localStorage (Recommended for Simplicity)

**Capacity:** ~5MB per origin
**Data Type:** String only (use JSON.stringify/parse)
**Performance:** Fast for small datasets, synchronous (may block UI on large writes)
**Mobile Support:** ✅ Universal (all browsers)
**Offline:** ✅ Persists across sessions
**Service Worker Access:** ❌ Not accessible from service workers

**Estimated Storage Needed:**
- 433 topics × ~200 bytes = 87KB
- 1000 completion records × ~100 bytes = 100KB
- Total: ~200KB (well under 5MB limit)

**Verdict:** Perfect for this use case

**Sources:**
- [localStorage vs IndexedDB comparison](https://dev.to/armstrong2035/9-differences-between-indexeddb-and-localstorage-30ai)
- [RxDB localStorage guide](https://rxdb.info/articles/localstorage.html)

### Option B: IndexedDB (If Needed Later)

**Capacity:** Up to 60% of disk space
**Data Type:** Objects, arrays, blobs (no stringify needed)
**Performance:** Async (non-blocking), 10x slower writes but better for large datasets
**Mobile Support:** ✅ Universal
**Offline:** ✅ Persists
**Service Worker Access:** ✅ Yes (critical for PWA sync)

**When to use:** If you exceed 5MB or need service worker background sync

**Sources:**
- [IndexedDB vs localStorage](https://dev.to/oghenetega_adiri/indexeddb-vs-localstorage-when-to-use-which-2blf)
- [PWA offline data guide](https://web.dev/learn/pwa/offline-data/)

---

## Cross-Device Sync Options

### Option 1: Manual Export/Import (Simplest - Recommended)

**How it works:**
1. User clicks "Export Data" → downloads `lesson-plan-data.json`
2. Share file via text message, email, AirDrop, etc.
3. Other device clicks "Import Data" → uploads JSON file
4. localStorage updated with latest data

**Pros:**
- Zero complexity, zero OAuth, zero APIs
- Works offline completely
- Users control their data file
- No privacy concerns

**Cons:**
- Manual sync step (not automatic)
- Need to remember to export/import when changes are made

**Verdict:** Start here. If family finds manual sync annoying, upgrade to auto-sync.

### Option 2: remoteStorage.js (Auto-Sync via Dropbox/Google Drive)

**How it works:**
1. Include remoteStorage.js library via CDN
2. User connects their Dropbox or Google Drive account (OAuth once)
3. App automatically syncs data to cloud storage
4. Other devices automatically pull changes

**Setup:**
```javascript
remoteStorage.setApiKeys('dropbox', { appKey: 'YOUR_APP_KEY' });
remoteStorage.setApiKeys('googledrive', { clientId: 'YOUR_CLIENT_ID' });
```

**Pros:**
- Automatic sync across devices
- Works with existing Dropbox/Google Drive accounts
- No backend server needed

**Cons:**
- Requires OAuth app setup (Dropbox/Google app registration)
- Polling for changes (not push-based sync)
- More complex than manual export/import
- Privacy: data stored in cloud (though it's their own account)

**Sources:**
- [remoteStorage.js docs](https://remotestorage.io/rs.js/docs/dropbox-and-google-drive.html)
- [remoteStorage.js on npm](https://www.npmjs.com/package/remotestoragejs)

**Verdict:** Good upgrade path if manual sync becomes tedious.

### Option 3: Direct Dropbox/Google Drive API

**Complexity:** High
**Benefit:** Full control
**Downside:** Must handle OAuth, polling, conflict resolution manually

**Verdict:** Overkill for this project. remoteStorage.js already abstracts this.

**Source:** [Implementing cloud APIs guide](https://hackernoon.com/how-to-implement-cloud-apis-google-drive-api-dropbox-api-and-onedrive-api)

---

## Progressive Web App (PWA) Setup

### What Makes It a PWA?

**Required:**
1. **HTTPS** (GitHub Pages, Cloudflare Pages provide this free)
2. **Web App Manifest** (`manifest.json` with app metadata)
3. **Service Worker** (for offline functionality)

**Benefits:**
- "Add to Home Screen" on iOS/Android (looks like native app)
- Works offline
- Fast loading (cached assets)
- No App Store needed

**iOS Safari Limitations:**
- Manual "Add to Home Screen" (no automatic prompt)
- 50MB cache limit (we'll use <1MB)
- Limited push notifications, background sync
- Still totally usable for this project

**Sources:**
- [PWA guide MDN](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
- [PWA iOS strategies](https://scandiweb.com/blog/pwa-ios-strategies/)
- [PWA add to home screen guide](https://www.gomage.com/blog/pwa-add-to-home-screen/)

---

## Mobile-First UI Design

### Alpine.js + Tailwind CSS

**Why This Stack:**
- **No build tools:** Include via CDN, works immediately
- **Small footprint:** Alpine.js is 14KB, Tailwind CSS is utility-first
- **Mobile-first:** Tailwind has responsive breakpoints built-in
- **Touch-friendly:** Easy to create 44×44px touch targets

**Example Touch Button:**
```html
<button
  class="w-full py-4 px-6 text-lg bg-blue-500 text-white rounded-lg active:bg-blue-600"
  @click="selectTopic()">
  Select This Topic
</button>
```
- `py-4 px-6`: Large padding for 44px+ height
- `text-lg`: Readable on mobile
- `active:bg-blue-600`: Touch feedback

**Component Libraries (Free):**
- [Pines](https://devdojo.com/pines): Alpine + Tailwind components
- [Pinemix](https://pinemix.com/): Free Alpine components
- [TailKits](https://tailkits.com/templates/tags/alpinejs/): Templates

**Sources:**
- [Alpine.js official](https://alpinejs.dev/)
- [Tailwind CSS official](https://tailwindcss.com/)
- [Alpine + Tailwind guide](https://dev.to/hexshift/implementing-a-component-driven-ui-with-tailwind-css-and-alpinejs-42d0)

---

## Data Structure Design

### localStorage Schema

```javascript
// Store as JSON strings in localStorage
{
  // Master lists (never changes during queue operations)
  "masterLists": {
    "arts": [{ id: 1, name: "...", category: "..." }, ...],
    "knowledge": [...],
    "physical": [...]
  },

  // Active queues (current order)
  "queues": {
    "arts": [1, 5, 3, ...],      // Array of topic IDs in order
    "knowledge": [...],
    "physical": [...]
  },

  // Completion log
  "completed": [
    { topicId: 1, queue: "arts", date: "2025-11-29" },
    ...
  ],

  // Development queue (needs rework)
  "development": [
    { topicId: 42, originalQueue: "knowledge", reason: "Too advanced", dateFlagged: "2025-11-29" },
    ...
  ],

  // Cycle counters
  "cycles": {
    "arts": 1,
    "knowledge": 1,
    "physical": 1
  }
}
```

### Import Initial Data from topics.py

Python script to convert `topics.py` → `initial-data.json`:

```python
import json
from topics import KNOWLEDGE_CATEGORIES, ACTIVITY_CATEGORIES, PHYSICAL_ACTIVITIES

# Map categories to queues
knowledge_topics = []
id_counter = 1
for category, topics in KNOWLEDGE_CATEGORIES.items():
    for topic in topics:
        knowledge_topics.append({
            "id": id_counter,
            "name": topic,
            "category": category
        })
        id_counter += 1

# Similar for arts (activities) and physical
# ... (transform ACTIVITY_CATEGORIES and PHYSICAL_ACTIVITIES)

# Shuffle for initial randomization
import random
random.shuffle(knowledge_topics)

data = {
    "masterLists": {
        "arts": arts_topics,
        "knowledge": knowledge_topics,
        "physical": physical_topics
    },
    "queues": {
        "arts": [t["id"] for t in arts_topics],
        "knowledge": [t["id"] for t in knowledge_topics],
        "physical": [t["id"] for t in physical_topics]
    },
    "completed": [],
    "development": [],
    "cycles": {"arts": 1, "knowledge": 1, "physical": 1}
}

with open('initial-data.json', 'w') as f:
    json.dump(data, f, indent=2)
```

---

## Hosting Options (All Free, No Spin-Down)

### GitHub Pages (Recommended)
- **Cost:** $0
- **Setup:** Push to GitHub repo, enable Pages in settings
- **Domain:** `username.github.io/repo-name`
- **HTTPS:** ✅ Free
- **Custom Domain:** ✅ Supported
- **Spin-down:** ❌ Never (static hosting)

### Cloudflare Pages
- **Cost:** $0
- **Setup:** Connect Git repo
- **Build:** None needed (static files)
- **Unlimited bandwidth:** ✅
- **HTTPS:** ✅ Free
- **Performance:** Excellent (global CDN)

### Netlify
- **Cost:** $0
- **Setup:** Drag-and-drop or Git
- **Free tier:** 100GB bandwidth/month
- **HTTPS:** ✅ Free
- **Form handling:** ✅ Built-in (not needed for us)

**Verdict:** Any of these work perfectly. GitHub Pages is simplest if repo is already on GitHub.

**Sources:**
- [Best free hosting platforms](https://appwrite.io/blog/post/free-hosting-platform)
- [Vercel vs Netlify vs Cloudflare](https://www.digitalapplied.com/blog/vercel-vs-netlify-vs-cloudflare-pages-comparison)

---

## Final Recommended Architecture

### Phase 1: MVP (Simplest - Start Here)

```
Tech Stack:
  - Static HTML + Alpine.js + Tailwind CSS (via CDN)
  - localStorage for data persistence
  - Manual export/import for cross-device sync
  - PWA with service worker for offline use
  - Hosted on GitHub Pages (free, no spin-down)

File Structure:
  /lesson-plans-app/
    ├── index.html          (main app)
    ├── manifest.json       (PWA manifest)
    ├── sw.js              (service worker)
    ├── initial-data.json   (converted from topics.py)
    └── README.md

Sync Strategy:
  - "Export Data" button → downloads JSON
  - Share via text/email/AirDrop
  - "Import Data" button → upload JSON on other device

Cost: $0/month
Time to MVP: 1 day
Mobile Support: ✅ Excellent (PWA, touch-optimized)
Offline: ✅ Full offline support
Real-time Sync: ❌ Manual (good enough for once-daily use)
```

### Phase 2: Auto-Sync Upgrade (If Manual Sync Becomes Tedious)

```
Add remoteStorage.js:
  - Automatic sync via Dropbox or Google Drive
  - One-time OAuth setup
  - Polling every 5-10 seconds for changes

Additional Complexity:
  - Register Dropbox/Google Drive app (free)
  - Add remoteStorage.js library
  - Handle OAuth flow

Time to upgrade: 2-3 hours
Cost: Still $0/month
```

---

## Implementation Plan

### Step 1: Convert topics.py → JSON
- Python script to transform dictionaries
- Assign topics to arts/knowledge/physical queues
- Randomize initial order
- Generate `initial-data.json`

### Step 2: Build Core HTML App
- Single-page app with Alpine.js
- Three queue displays (arts, knowledge, physical)
- Buttons: Select, Skip, Needs Work
- localStorage read/write

### Step 3: Queue Logic
- Select: Remove from queue → Add to completed log → Advance
- Skip: Move to end of queue
- Needs Work: Move to development queue
- Auto-refill when queue empties

### Step 4: Export/Import
- Export: `localStorage → JSON blob → download`
- Import: `file upload → parse JSON → localStorage`

### Step 5: PWA Setup
- manifest.json (app name, icons, colors)
- Service worker (cache assets, offline support)
- Test "Add to Home Screen" on iOS/Android

### Step 6: Mobile UI Polish
- Tailwind responsive classes
- Touch-friendly buttons (44×44px min)
- Test on real devices

### Step 7: Deploy to GitHub Pages
- Push to repo
- Enable GitHub Pages
- Test on mobile browsers

---

## Requirements Coverage

| Requirement | Solution | Status |
|-------------|----------|--------|
| Mobile-first (44px touch targets) | Tailwind CSS utilities | ✅ |
| 2-3 concurrent users | Manual sync (low conflict risk) | ✅ |
| Select topics <60 seconds | Fast localStorage, simple UI | ✅ |
| Cost $0-10/month | GitHub Pages free hosting | ✅ $0 |
| Real-time sync (5 seconds) | Manual sync (acceptable for daily use) | ⚠️ Manual |
| Works offline | PWA + localStorage | ✅ |
| 433 topics + logs | ~200KB < 5MB limit | ✅ |
| No auth required | No server, no auth | ✅ |

**Trade-off:** Manual sync instead of automatic real-time sync (5 seconds requirement). Given once-daily use, this is acceptable. Can upgrade to remoteStorage.js if needed.

---

## Key Decisions Summary

✅ **Use Alpine.js + Tailwind (CDN)** - No build tools, fast development
✅ **Use localStorage** - 5MB is plenty for this dataset
✅ **Manual export/import sync** - Simplest, upgrade to auto-sync if needed
✅ **Host on GitHub Pages** - Free, no spin-down, easy deployment
✅ **Build as PWA** - Offline support, "Add to Home Screen"
❌ **Don't use File System Access API** - iOS Safari doesn't support it
❌ **Don't use server/database** - Unnecessary complexity for this use case

---

## Next Steps

1. ✅ Research complete
2. ⏭️ Build Python script: `topics.py` → `initial-data.json`
3. ⏭️ Build single-page HTML app with Alpine.js + Tailwind
4. ⏭️ Implement queue operations (select, skip, flag)
5. ⏭️ Add export/import functionality
6. ⏭️ Create PWA manifest + service worker
7. ⏭️ Test on mobile devices
8. ⏭️ Deploy to GitHub Pages

**Estimated Total Time:** 1 full day of development

---

## Sources

### File System & Storage
- [File System Access API browser support](https://caniuse.com/native-filesystem-api)
- [WebKit File System API blog](https://webkit.org/blog/12257/the-file-system-access-api-with-origin-private-file-system/)
- [localStorage vs IndexedDB comparison](https://dev.to/armstrong2035/9-differences-between-indexeddb-and-localstorage-30ai)
- [RxDB localStorage guide](https://rxdb.info/articles/localstorage.html)
- [LocalStorage vs IndexedDB guide](https://shiftasia.com/community/localstorage-vs-indexeddb-choosing-the-right-solution-for-your-web-application/)

### PWA & Offline
- [PWA guide MDN](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
- [PWA offline data guide](https://web.dev/learn/pwa/offline-data/)
- [PWA iOS strategies](https://scandiweb.com/blog/pwa-ios-strategies/)
- [PWA add to home screen guide](https://www.gomage.com/blog/pwa-add-to-home-screen/)
- [PWA offline capabilities](https://www.gomage.com/blog/pwa-offline/)

### Sync Solutions
- [remoteStorage.js Dropbox/Google Drive docs](https://remotestorage.io/rs.js/docs/dropbox-and-google-drive.html)
- [remoteStorage.js on npm](https://www.npmjs.com/package/remotestoragejs)
- [remoteStorage.js GitHub](https://github.com/RemoteStorage/remoteStorage.js)
- [Implementing cloud APIs guide](https://hackernoon.com/how-to-implement-cloud-apis-google-drive-api-dropbox-api-and-onedrive-api)

### Frontend Frameworks
- [Alpine.js 2025 beginner guide](https://amirkamizi.com/blog/alpinejs-beginner-to-advanced-2025)
- [Alpine.js official docs](https://alpinejs.dev/)
- [Tailwind CSS official](https://tailwindcss.com/)
- [Alpine + Tailwind implementation guide](https://dev.to/hexshift/implementing-a-component-driven-ui-with-tailwind-css-and-alpinejs-42d0)
- [Pines component library](https://devdojo.com/pines)
- [Pinemix components](https://pinemix.com/)

### Hosting
- [Best free hosting platforms](https://appwrite.io/blog/post/free-hosting-platform)
- [Vercel vs Netlify vs Cloudflare comparison](https://www.digitalapplied.com/blog/vercel-vs-netlify-vs-cloudflare-pages-comparison)
