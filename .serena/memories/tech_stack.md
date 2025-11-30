# Technology Stack

## Frontend
- **Framework**: Alpine.js 3.x (14KB, delivered via CDN)
- **CSS**: Tailwind CSS (via CDN)
- **Pattern**: Reactive UI with x-data, x-init, x-show directives

## Storage
- **Primary**: localStorage (browser-based)
- **Capacity**: ~5MB limit (current usage ~200KB)
- **Persistence**: Automatic on every action

## Hosting & Deployment
- **Type**: Static files only
- **Current Host**: GitHub Pages
- **Alternatives**: Cloudflare Pages, Netlify, any static host
- **PWA Features**: Service worker (sw.js), manifest.json

## Build Tools
- **None!** No build step required
- Dependencies loaded via CDN
- Edit HTML directly and refresh browser

## Data Pipeline
```
topics.py (Python source)
    ↓
convert_topics.py (Python 3.13.3)
    ↓
docs/initial-data.json
    ↓
Browser localStorage
```

## Python Environment
- **Version**: Python 3.13.3 (managed via asdf)
- **Purpose**: Data conversion only (not runtime)
- **Dependencies**: None (uses stdlib only)

## Why This Stack?
✅ Zero hosting costs
✅ No build complexity
✅ Fast load times (<1 second on mobile)
✅ Works completely offline
✅ No maintenance overhead
✅ Easy to modify and deploy
