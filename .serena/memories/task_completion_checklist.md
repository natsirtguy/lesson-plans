# Task Completion Checklist

## When a Development Task is Complete

Since this is a simple static app with no build tools, testing, or linting, the completion checklist is minimal:

### 1. Code Changes
- [ ] Changes made to appropriate files
- [ ] Code follows existing patterns and conventions
- [ ] No unnecessary complexity added

### 2. Manual Testing
- [ ] If changed `docs/index.html`:
  - [ ] Open `http://localhost:8000` in browser
  - [ ] Test affected functionality manually
  - [ ] Check browser console for errors
  - [ ] Test on mobile device if UI changes

- [ ] If changed `topics.py`:
  - [ ] Run `python3 convert_topics.py`
  - [ ] Verify `docs/initial-data.json` updated correctly
  - [ ] Check topic counts in output

### 3. Documentation
- [ ] Update README.md if user-facing changes
- [ ] Update CLAUDE.md if development workflow changes
- [ ] Update comments in code if complex logic added

### 4. Git Workflow (if ready to commit)
- [ ] Review changes with `git status` and `git diff`
- [ ] Stage changes: `git add <files>`
- [ ] Commit with clear message: `git commit -m "..."`
- [ ] Push to GitHub: `git push origin master`
- [ ] Verify deployment on GitHub Pages (auto-deploys)

## What NOT to Do

❌ Don't run linting (none configured)
❌ Don't run tests (none exist)
❌ Don't run build process (none exists)
❌ Don't run type checking (not used)
❌ Don't run formatting (not configured)

## Mobile Testing (When Needed)

For significant UI changes:
- [ ] Deploy to GitHub Pages (push to master)
- [ ] Test on real iPhone/Android device
- [ ] Verify touch targets are easy to tap
- [ ] Test offline mode (turn off WiFi)
- [ ] Test export/import workflow

## Deployment

Deployment is automatic via GitHub Pages:
1. Push to master branch
2. GitHub Pages rebuilds (takes ~1 minute)
3. Changes live at https://natsirtguy.github.io/lesson-plans/

No manual deployment step required.

## Special Cases

### Adding New Topics
1. Edit `topics.py`
2. Run `python3 convert_topics.py`
3. Commit both files
4. Users need to import new data or reset app

### Modifying App Logic
1. Edit `docs/index.html` (Alpine.js code)
2. Test locally: `cd docs && python3 -m http.server 8000`
3. Test in browser at `http://localhost:8000`
4. Commit and push when working

### Fixing Bugs
1. Identify issue in browser console or user report
2. Fix in `docs/index.html`
3. Test locally
4. Commit and deploy
