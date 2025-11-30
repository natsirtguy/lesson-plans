# Project Overview

## Purpose
Daily Lesson Plan Queue System - a Progressive Web App (PWA) for managing daily learning topics for early childhood education (ages 2-3+ years).

## Core Functionality
Manages three independent FIFO queues of educational topics:
1. **Arts & Culture Queue** (198 topics)
2. **Knowledge & Skills Queue** (118 topics)  
3. **Physical Activities Queue** (117 topics)

## Key Features
- Queue operations: Select (mark complete), Skip (move to end), Needs Work (flag for development)
- Mobile-first design optimized for touch
- Works offline as PWA
- Automatic queue refill when cycles complete
- Data export/import for cross-device sync (manual)
- Development queue for topics needing revision
- Completion logging

## Deployment
- **Live URL**: https://natsirtguy.github.io/lesson-plans/
- **Hosting**: GitHub Pages (free static hosting)
- **Cost**: $0/month (meets <$10/month requirement)

## Status
✅ Fully implemented and deployed
✅ All requirements met (see REQUIREMENTS.md v1.1)
✅ Being used in production by family

## Key Design Decisions
- No server required (client-side only)
- No database (localStorage)
- No authentication (single household use)
- Manual sync (export/import JSON) instead of real-time
- No build tools (CDN-based dependencies)
