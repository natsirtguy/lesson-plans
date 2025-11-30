# Suggested Commands

## Development Commands

### Run Locally
```bash
cd docs && python3 -m http.server 8000
# Then open http://localhost:8000 in browser
```

### Regenerate Data from Source
```bash
python3 convert_topics.py
# Converts topics.py → docs/initial-data.json
# Run this after editing topics.py
```

## Git Commands (Standard)
```bash
git status
git add .
git commit -m "message"
git push origin master
```

## Deployment
Deployment happens automatically via GitHub Pages when pushing to master branch.
No manual deployment step needed.

## Testing
- **Unit Tests**: None (simple static app)
- **Manual Testing**: Open in browser and test operations
- **Mobile Testing**: Deploy to GitHub Pages and test on real devices

## Code Quality
- **Linting**: None configured (simple project)
- **Formatting**: None configured
- **Type Checking**: None (no TypeScript)

## Utility Commands (macOS Darwin)
Standard Unix commands available:
- `ls`, `cd`, `grep`, `find`
- `cat`, `less`, `head`, `tail`
- `mkdir`, `rm`, `mv`, `cp`

## File Editing
- Edit `docs/index.html` directly for UI changes
- Edit `topics.py` for topic data changes
- No compilation or build step required
