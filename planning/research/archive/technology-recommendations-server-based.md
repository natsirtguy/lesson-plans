# Technology Stack Research - Daily Lesson Plan Queue System

**Research Date:** November 28, 2025
**Focus:** Simplest solutions that satisfy requirements for family use

## Executive Summary

For this family-focused queue management system, **the simplest approach is a Python web app** using:
- **Backend:** Python + Flask (or FastAPI)
- **Database:** SQLite (file-based, zero config)
- **Frontend:** Simple HTML/CSS/JS with a mobile-responsive framework (Tailwind CSS or Bootstrap)
- **Hosting:** Free tier on Render, Railway, or Fly.io

**Alternative considered:** Streamlit (Python) - simpler to code but has mobile responsiveness limitations

---

## Research Findings

### 1. Database Solutions

#### Winner: SQLite
**Best for:** Simple, file-based storage with zero configuration

**Pros:**
- No separate database server needed
- Single file database (easy backups)
- Built into Python standard library
- Perfect for 500-1000 items + completion logs
- Concurrent reads, single writer (fine for 2-3 family users)

**Cons:**
- Not ideal for high-concurrency (but requirements only need 2-3 users)
- No built-in real-time sync (would need polling or websockets layer)

**Cost:** $0 (included with Python)

#### Alternative: Firebase/Supabase/PocketBase
**Considered but more complex than needed**

- **Firebase:** Battle-tested, great real-time sync, generous free tier, but adds complexity
  - Free tier: 50K reads/day, 20K writes/day, 1GB storage
  - [Source: Supadex Firebase vs Supabase comparison](https://www.supadex.app/blog/supabase-vs-firebase-vs-pocketbase-which-one-should-you-choose-in-2025)

- **Supabase:** Open-source Postgres, SQL-based, free tier 500MB DB
  - Better for teams wanting SQL and self-hosting options later
  - [Source: Supabase vs Firebase](https://supabase.com/alternatives/supabase-vs-firebase)

- **PocketBase:** Single executable, includes auth + file storage + admin UI
  - Excellent for MVPs, self-hosted, but requires server setup
  - [Source: Supadex comparison](https://www.supadex.app/blog/supabase-vs-firebase-vs-pocketbase-which-one-should-you-choose-in-2025)

**Recommendation:** Start with SQLite. Can migrate to Firebase/Supabase later if real-time sync becomes critical.

---

### 2. Frontend Frameworks

#### For Simplest Implementation: Plain HTML/CSS/JS + Tailwind/Bootstrap
**Best for:** Minimal dependencies, fast development, mobile-responsive out of the box

**Why this beats React/Vue/Svelte:**
- No build tools needed
- No framework-specific knowledge required
- Can add htmx for dynamic updates without full SPA complexity
- Tailwind CSS provides mobile-first utilities

#### If Using a Framework: Vue.js
**Best beginner-friendly option**

- Easiest learning curve among React/Vue/Svelte
- Great documentation
- Good PWA support with Quasar framework
- [Source: React vs Vue vs Svelte 2025 guide](https://clinkitsolutions.com/react-vs-vue-vs-svelte-the-real-2025-guide-to-picking-your-first-javascript-framework/)

#### Performance Alternative: Svelte
- Smallest bundle sizes (1/10th size of React)
- Very fast, minimal boilerplate
- [Source: Frontend frameworks comparison](https://fleischer.design/en/blog/frontend-frameworks-2025-react-vue-svelte-solid-angular)

**Recommendation:** Start with plain HTML/CSS/JS + Tailwind for maximum simplicity.

---

### 3. Hosting Solutions

All three major platforms have excellent free tiers:

#### Cloudflare Pages (Winner for static + workers)
- **Free tier:** Unlimited bandwidth, 500 builds/month
- Best performance via global CDN
- Can add Cloudflare Workers for backend logic
- [Source: Vercel vs Netlify vs Cloudflare comparison](https://www.digitalapplied.com/blog/vercel-vs-netlify-vs-cloudflare-pages-comparison)

#### Vercel
- **Free tier:** 100GB bandwidth, 100K serverless function calls
- Best for Next.js, excellent DX
- [Source: Best free static hosting](https://appwrite.io/blog/post/best-free-static-website-hosting)

#### Netlify
- **Free tier:** 100GB bandwidth, 125K requests/month
- Simplest deployment, form handling built-in
- [Source: Vercel vs Netlify comparison](https://www.digitalapplied.com/blog/vercel-vs-netlify-vs-cloudflare-pages-comparison)

#### For Python Apps: Render / Railway / Fly.io
- **Render:** Free tier for web services (spins down after 15min inactivity)
- **Railway:** Free $5 credit/month
- **Fly.io:** Free tier includes 3 small VMs

**Recommendation:** Render or Railway for Python Flask app (free tier sufficient)

---

### 4. Streamlit Alternative (Python-First)

#### What is Streamlit?
Python framework that turns scripts into web apps in minutes. Designed for data apps.

**Pros:**
- Extremely fast development (write only Python, no HTML/CSS/JS)
- Free hosting on Streamlit Community Cloud
- Built-in state management (st.session_state)
- [Source: Streamlit official site](https://streamlit.io/)

**Cons:**
- **Mobile responsiveness is limited** - primary focus is desktop
  - Touch interfaces require manual CSS workarounds
  - Layout issues on small screens
  - [Source: Streamlit mobile discussion](https://discuss.streamlit.io/t/how-to-use-a-streamlit-site-on-the-smartphone/22393)
  - [Source: Streamlit pros/cons](https://digitaldefynd.com/IQ/pros-cons-of-streamlit/)

- **Session state not persistent** across page refreshes
  - Requires SQLite/file storage for persistence
  - [Source: Streamlit session state docs](https://docs.streamlit.io/develop/concepts/architecture/session-state)
  - [Source: SQLite with Streamlit discussion](https://discuss.streamlit.io/t/full-stack-streamlit-app-3-ways-sqlite-postgres-go-api/22790)

**Verdict:** Streamlit could work but the mobile requirement is critical for this use case. Traditional Flask/FastAPI gives better mobile control.

---

### 5. Minimal Python Web Frameworks

For building the queue app with minimal dependencies:

#### Flask (Recommended)
- Lightweight micro-framework
- Provides essentials without forcing structure
- Perfect for small-medium apps and RESTful APIs
- Large ecosystem of extensions
- [Source: Simple web frameworks](https://neontri.com/blog/simple-web-frameworks/)

#### FastAPI (Alternative)
- Modern, fast, automatic API docs
- Built-in type checking with Pydantic
- Good choice if building API-first

**Example:** There's an existing Flask-based queue management system ([FQM](https://github.com/mrf345/FQM)) that could serve as reference.

**Recommendation:** Flask for simplicity, FastAPI if you want modern API features.

---

## Recommended Stack (Simplest Path)

### Option 1: Pure Python Approach (Recommended)
```
Backend:  Flask (Python)
Database: SQLite (file-based)
Frontend: Jinja2 templates + Tailwind CSS + htmx (for dynamic updates)
Hosting:  Render.com (free tier)
```

**Why this is simplest:**
- All Python, leverage your existing topics.py data
- No build tools or compilation needed
- SQLite = zero database configuration
- htmx = minimal JavaScript for interactivity
- Render = one-click deploy from Git

**Time to MVP:** 1-2 days

**Tradeoffs:**
- Real-time sync requires polling or websockets (add if needed)
- Render free tier spins down after 15min inactivity (takes ~30sec to wake)

---

### Option 2: Modern SPA Approach
```
Backend:  FastAPI (Python) or Supabase
Database: Supabase (Postgres with real-time)
Frontend: Vue.js + Tailwind CSS
Hosting:  Cloudflare Pages (frontend) + Railway (backend if using FastAPI)
```

**Why this works:**
- Better real-time sync out of the box
- More "modern" architecture
- Better separation of concerns

**Time to MVP:** 3-5 days

**Tradeoffs:**
- More moving parts
- Learning curve for Vue.js
- More complex deployment

---

## Key Findings for Your Requirements

### Mobile-First (44px touch targets)
✅ Tailwind CSS has mobile-first utilities built-in
✅ Bootstrap has touch-friendly components
⚠️ Streamlit requires manual CSS tweaking

### Multi-User (2-3 concurrent)
✅ SQLite handles 2-3 concurrent users fine (mostly reads)
✅ Flask/FastAPI can handle this easily
✅ Real-time updates: Add polling (simple) or websockets (more complex)

### Cost ($0-10/month)
✅ SQLite: Free
✅ Render/Railway free tiers: $0
✅ Cloudflare Pages: Free
✅ Streamlit Community Cloud: Free

### Speed (select topics in <60 seconds)
✅ All options meet this easily
✅ SQLite queries are milliseconds for 500 items

### Data Import (433 items from topics.py)
✅ Simple Python script to transform dict → SQLite
✅ Can preserve all category metadata

---

## Next Steps Recommendation

1. **Start with Option 1** (Flask + SQLite + htmx)
2. Build core queue operations (select, skip, flag)
3. Test with family on mobile devices
4. If real-time sync becomes critical, add websockets or migrate to Supabase

**The simpler you keep it, the faster your family can start using it.**

---

## Sources

- [Supabase vs Firebase vs PocketBase comparison](https://www.supadex.app/blog/supabase-vs-firebase-vs-pocketbase-which-one-should-you-choose-in-2025)
- [Supabase vs Firebase](https://supabase.com/alternatives/supabase-vs-firebase)
- [Frontend Frameworks 2025 - React, Vue, Svelte comparison](https://fleischer.design/en/blog/frontend-frameworks-2025-react-vue-svelte-solid-angular)
- [React vs Vue vs Svelte 2025 guide](https://clinkitsolutions.com/react-vs-vue-vs-svelte-the-real-2025-guide-to-picking-your-first-javascript-framework/)
- [Vercel vs Netlify vs Cloudflare Pages](https://www.digitalapplied.com/blog/vercel-vs-netlify-vs-cloudflare-pages-comparison)
- [Best free static hosting platforms](https://appwrite.io/blog/post/best-free-static-website-hosting)
- [Streamlit official site](https://streamlit.io/)
- [Streamlit Community Cloud](https://streamlit.io/cloud)
- [Streamlit mobile discussion](https://discuss.streamlit.io/t/how-to-use-a-streamlit-site-on-the-smartphone/22393)
- [Streamlit session state docs](https://docs.streamlit.io/develop/concepts/architecture/session-state)
- [Full Stack Streamlit with SQLite](https://discuss.streamlit.io/t/full-stack-streamlit-app-3-ways-sqlite-postgres-go-api/22790)
- [Streamlit pros and cons](https://digitaldefynd.com/IQ/pros-cons-of-streamlit/)
- [Simple web frameworks overview](https://neontri.com/blog/simple-web-frameworks/)
- [Flask Queue Management System (FQM)](https://github.com/mrf345/FQM)
- [Building minimal task queue in Python](https://hexshift.medium.com/building-a-minimal-task-queue-system-into-your-python-web-framework-without-celery-9dd379b13ccd)
