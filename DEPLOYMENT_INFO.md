# Deployment Information

## 🚀 Live Deployment

**Your app is live at:**
```
https://natsirtguy.github.io/lesson-plans/
```

## 📊 Deployment Details

- **GitHub Repository:** https://github.com/natsirtguy/lesson-plans
- **Deployment Branch:** `gh-pages`
- **Source Branch:** `master`
- **Deployment Status:** Building (wait ~1-2 minutes)

## 🔄 How It Works

1. **Master branch** contains full project (code, docs, research)
2. **gh-pages branch** contains only the app files (for deployment)
3. GitHub Pages serves from gh-pages branch
4. Every push to gh-pages triggers automatic redeployment

## 📝 Future Deployments

When you make changes to the app:

```bash
# 1. Make changes in master branch
cd /Users/tristanmckinney/Projects/lesson-plans
# Edit app/index.html or other files

# 2. Commit to master
git add app/
git commit -m "Update app"
git push origin master

# 3. Deploy to gh-pages
git checkout gh-pages
git checkout master -- app/
mv app/* .
git add .
git commit -m "Deploy updates"
git push origin gh-pages
git checkout master
```

Or use this one-liner:

```bash
# Quick deploy script
git checkout gh-pages && \
git checkout master -- app/ && \
mv app/* . 2>/dev/null ; \
git add . && \
git commit -m "Deploy: $(date +%Y-%m-%d)" && \
git push origin gh-pages && \
git checkout master
```

## 🧪 Testing Deployment

Once deployment is complete (~2 minutes):

1. Visit: https://natsirtguy.github.io/lesson-plans/
2. Test on desktop browser first
3. Test on mobile (iPhone Safari, Android Chrome)
4. Try "Add to Home Screen" on mobile
5. Test offline mode (turn off WiFi after loading)
6. Test export/import between devices

## 📱 Share with Family

Send them this URL:
```
https://natsirtguy.github.io/lesson-plans/
```

Instructions for them:
1. Open link on phone
2. Tap "Add to Home Screen" (iOS Safari) or "Install app" (Android Chrome)
3. Open app from home screen
4. Start selecting daily topics!

## 🔒 Repository Visibility

Your repo is **public**, which means:
- ✅ Anyone can view the code
- ✅ Anyone can use the app
- ✅ Free GitHub Pages hosting
- ❌ Cannot make it private (GitHub Pages requires public repos on free plan)

If you need privacy, you can:
- Host on Netlify/Cloudflare (supports private repos)
- Self-host on your own server

## 📊 Monitoring

Check deployment status anytime:

```bash
gh api repos/natsirtguy/lesson-plans/pages | jq -r '.status'
```

Statuses:
- `building` - Deployment in progress
- `built` - Deployed successfully
- `errored` - Deployment failed

## 🎉 Success!

Your app is now:
- ✅ Hosted on GitHub Pages
- ✅ Free forever
- ✅ Automatic HTTPS
- ✅ Global CDN (fast worldwide)
- ✅ Automatic deployments from gh-pages branch

---

**Deployed:** November 29, 2025
**Repository:** https://github.com/natsirtguy/lesson-plans
**Live URL:** https://natsirtguy.github.io/lesson-plans/

🤖 Generated with [Claude Code](https://claude.com/claude-code)
