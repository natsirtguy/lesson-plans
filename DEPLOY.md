# Deployment Guide

Complete guide for deploying the Daily Lesson Plans PWA.

## 🎯 Deployment Options

Choose one based on your preference:

1. **GitHub Pages** (Recommended - Easiest)
2. **Cloudflare Pages** (Fastest global performance)
3. **Netlify** (Best developer experience)
4. **Self-hosted** (Full control)

---

## 1. GitHub Pages (Free, Simple)

### Prerequisites
- GitHub account
- Git installed

### Steps

1. **Create GitHub repository:**
   ```bash
   # If not already a Git repo
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. **Push to GitHub:**
   ```bash
   # Create repo on GitHub first, then:
   git remote add origin https://github.com/yourusername/lesson-plans.git
   git branch -M master
   git push -u origin master
   ```

3. **Enable GitHub Pages:**
   - Go to repository on GitHub
   - Click **Settings** → **Pages**
   - Source: Deploy from a branch
   - Branch: `master`
   - Folder: `/app`
   - Click **Save**

4. **Wait ~1 minute**, then access at:
   ```
   https://yourusername.github.io/lesson-plans/
   ```

### Custom Domain (Optional)

1. Add CNAME file:
   ```bash
   echo "lessons.yourdomain.com" > app/CNAME
   git add app/CNAME
   git commit -m "Add custom domain"
   git push
   ```

2. Configure DNS:
   - Add CNAME record: `lessons` → `yourusername.github.io`
   - Wait for DNS propagation (~10 minutes)

3. Enable HTTPS in GitHub Pages settings

---

## 2. Cloudflare Pages (Free, Fast)

### Prerequisites
- Cloudflare account (free)
- GitHub/GitLab account

### Steps

1. **Push to GitHub** (same as above)

2. **Create Cloudflare Pages project:**
   - Go to Cloudflare Dashboard → Pages
   - Click **Create a project**
   - Connect to Git → Select repository

3. **Configure build settings:**
   - Project name: `lesson-plans`
   - Production branch: `master`
   - Build command: *(leave empty)*
   - Build output directory: `app`
   - Root directory: `/`

4. **Deploy:**
   - Click **Save and Deploy**
   - Wait ~1 minute

5. **Access at:**
   ```
   https://lesson-plans.pages.dev
   ```

### Custom Domain (Optional)

1. In Cloudflare Pages → Custom domains
2. Add `lessons.yourdomain.com`
3. Follow DNS instructions
4. HTTPS enabled automatically

---

## 3. Netlify (Free, Feature-Rich)

### Prerequisites
- Netlify account (free)
- GitHub account

### Steps

1. **Push to GitHub** (same as above)

2. **Create Netlify site:**
   - Go to Netlify Dashboard
   - Click **Add new site** → **Import an existing project**
   - Connect to Git → Select repository

3. **Configure build settings:**
   - Build command: *(leave empty)*
   - Publish directory: `app`
   - Click **Deploy site**

4. **Access at:**
   ```
   https://random-name-12345.netlify.app
   ```

### Custom Domain (Optional)

1. Netlify Dashboard → Domain settings
2. Add custom domain
3. Follow DNS instructions
4. HTTPS enabled automatically

---

## 4. Self-Hosted

### Apache

1. **Copy files to web root:**
   ```bash
   sudo cp -r app/* /var/www/html/lesson-plans/
   ```

2. **Ensure .htaccess is enabled:**
   ```apache
   # /etc/apache2/apache2.conf
   <Directory /var/www/html>
       AllowOverride All
   </Directory>
   ```

3. **Enable required modules:**
   ```bash
   sudo a2enmod headers expires deflate
   sudo systemctl restart apache2
   ```

4. **Access at:**
   ```
   https://yourdomain.com/lesson-plans/
   ```

### Nginx

1. **Copy files:**
   ```bash
   sudo cp -r app/* /var/www/html/lesson-plans/
   ```

2. **Configure Nginx:**
   ```nginx
   # /etc/nginx/sites-available/lesson-plans
   server {
       listen 80;
       server_name lessons.yourdomain.com;

       root /var/www/html/lesson-plans;
       index index.html;

       location / {
           try_files $uri $uri/ =404;
       }

       # Service worker headers
       location /sw.js {
           add_header Cache-Control "no-cache";
           add_header Service-Worker-Allowed "/";
       }

       # Manifest
       location /manifest.json {
           add_header Content-Type "application/manifest+json";
       }

       # Enable compression
       gzip on;
       gzip_types text/html text/css application/javascript application/json;
   }
   ```

3. **Enable and restart:**
   ```bash
   sudo ln -s /etc/nginx/sites-available/lesson-plans /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

4. **Add HTTPS with Let's Encrypt:**
   ```bash
   sudo certbot --nginx -d lessons.yourdomain.com
   ```

---

## 📱 Post-Deployment Testing

After deploying, test these critical features:

### Desktop Testing

1. Open deployed URL in Chrome/Firefox/Safari
2. Check browser console for errors
3. Test all three queues:
   - Select a topic
   - Skip a topic
   - Flag for development
4. Test menu functions:
   - Export data
   - Import data
   - View history
   - Development queue
5. Check service worker registration:
   - Chrome DevTools → Application → Service Workers
   - Should show "activated and is running"

### Mobile Testing (Critical!)

#### iOS (Safari)

1. Open URL on iPhone/iPad
2. Test touch interactions (buttons should be easy to tap)
3. Test queue operations (select, skip, flag)
4. Test export/import:
   - Export data
   - Share via AirDrop/Messages
   - Import on another device
5. **Add to Home Screen:**
   - Tap Share button
   - Scroll down → "Add to Home Screen"
   - Open from home screen (should look like native app)
6. Test offline:
   - Turn on Airplane mode
   - Open app from home screen
   - Should still work with cached data

#### Android (Chrome)

1. Open URL on Android device
2. Test touch interactions
3. Test queue operations
4. Test export/import
5. **Install as PWA:**
   - Tap menu (⋮) → "Install app"
   - Or look for install banner at bottom
   - Open from home screen
6. Test offline:
   - Turn off WiFi/mobile data
   - Open app
   - Should work offline

---

## 🔄 Continuous Deployment

### Auto-deploy on Git Push

All three platforms (GitHub Pages, Cloudflare Pages, Netlify) automatically deploy when you push to the main branch:

```bash
# Make changes to app/index.html
git add app/index.html
git commit -m "Update UI"
git push

# Wait ~1 minute, changes are live!
```

### Deployment Workflow

1. Develop locally:
   ```bash
   cd app
   python3 -m http.server 8000
   # Test at http://localhost:8000
   ```

2. Commit changes:
   ```bash
   git add .
   git commit -m "Description of changes"
   ```

3. Push to GitHub:
   ```bash
   git push origin master
   ```

4. Platform auto-deploys (~1 minute)

5. Test deployed version on mobile

---

## 🛡️ Security Checklist

- [ ] Site served over HTTPS
- [ ] Service worker only loads from same origin
- [ ] No sensitive data in localStorage (all data is non-sensitive)
- [ ] Content Security Policy headers (optional)
- [ ] CORS headers configured if needed

---

## 🚀 Performance Optimization

### Already Optimized

- ✅ CDN delivery (Tailwind, Alpine.js)
- ✅ Service worker caching
- ✅ localStorage (no network requests after initial load)
- ✅ Minimal JavaScript (~15KB Alpine.js)

### Optional Enhancements

1. **Preload critical resources:**
   ```html
   <link rel="preload" href="https://cdn.tailwindcss.com" as="script">
   ```

2. **Add resource hints:**
   ```html
   <link rel="dns-prefetch" href="https://cdn.jsdelivr.net">
   ```

3. **Self-host fonts** (if using custom fonts)

---

## 📊 Monitoring

### Simple Monitoring

Use built-in platform analytics:

- **GitHub Pages**: GitHub Insights (limited)
- **Cloudflare Pages**: Analytics dashboard (page views, bandwidth)
- **Netlify**: Analytics dashboard (page views, forms, functions)

### Advanced Monitoring (Optional)

Add lightweight analytics:

```html
<!-- Plausible (privacy-friendly) -->
<script defer data-domain="yourdomain.com" src="https://plausible.io/js/script.js"></script>

<!-- Or Fathom Analytics -->
<script src="https://cdn.usefathom.com/script.js" data-site="YOUR-SITE-ID" defer></script>
```

---

## 🔧 Troubleshooting

### Service Worker Not Updating

```bash
# Hard refresh on desktop
Ctrl+Shift+R (Windows)
Cmd+Shift+R (Mac)

# Clear cache and reload
Chrome DevTools → Application → Clear Storage → Clear site data
```

### HTTPS Issues

- GitHub Pages: Automatic, wait 10 minutes after enabling
- Cloudflare: Automatic
- Netlify: Automatic
- Self-hosted: Use Let's Encrypt (see Nginx config above)

### Custom Domain Not Working

1. Check DNS propagation: https://dnschecker.org
2. Wait up to 24 hours for full propagation
3. Ensure CNAME/A record is correct
4. Check platform-specific documentation

---

## 💰 Cost Comparison

| Platform | Cost | Bandwidth | Build Minutes | Custom Domain | HTTPS |
|----------|------|-----------|---------------|---------------|-------|
| GitHub Pages | $0 | 100GB/month | N/A (static) | ✅ Free | ✅ Free |
| Cloudflare Pages | $0 | Unlimited | 500/month | ✅ Free | ✅ Free |
| Netlify | $0 | 100GB/month | 300/month | ✅ Free | ✅ Free |
| Self-hosted (VPS) | $5-10/month | Varies | N/A | ✅ (costs $12/year) | ✅ Free (Let's Encrypt) |

**Recommendation for this project:** GitHub Pages or Cloudflare Pages (both free, unlimited for this use case)

---

## 📝 Deployment Checklist

Before first deployment:

- [ ] All files in `app/` directory
- [ ] `initial-data.json` present and valid
- [ ] Test locally with Python server
- [ ] Git repository created and pushed
- [ ] Platform selected (GitHub/Cloudflare/Netlify)
- [ ] Deployment configured
- [ ] HTTPS enabled
- [ ] Tested on real mobile devices
- [ ] Service worker registering correctly
- [ ] Offline mode working
- [ ] Export/import tested between devices

---

## 🎉 You're Live!

After deployment:

1. Share URL with family members
2. Test export/import workflow
3. Add to home screen on all devices
4. Use daily and provide feedback
5. Export data regularly as backup

**Questions?** Check `app/README.md` or open an issue.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
