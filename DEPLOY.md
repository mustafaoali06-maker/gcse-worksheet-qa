# Deploying examqa online (Railway)

Railway gives you a private HTTPS URL in about 5 minutes. Free tier includes 500 hours/month — plenty for a small team.

---

## Step 1 — Push your code to GitHub

If you don't have a GitHub account, create one at https://github.com

1. Open **Terminal** and navigate to your project folder:
   ```bash
   cd ~/gcse_worksheets_system
   ```

2. Initialise a git repo and push:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```

3. Go to https://github.com/new and create a **private** repository named `examqa`

4. Push to GitHub (replace `YOUR_USERNAME`):
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/examqa.git
   git branch -M main
   git push -u origin main
   ```

---

## Step 2 — Deploy on Railway

1. Go to https://railway.app and sign up (free, use GitHub login)

2. Click **New Project → Deploy from GitHub repo**

3. Select your `examqa` repository

4. Railway will detect the Dockerfile and start building automatically

---

## Step 3 — Set environment variables

In your Railway project, click **Variables** and add:

| Key | Value |
|-----|-------|
| `OPENAI_API_KEY` | `sk-...your key...` |
| `AUTH_USER` | `examqa` (or any username you like) |
| `AUTH_PASSWORD` | `choose-a-strong-password` |

Railway will redeploy automatically after saving.

---

## Step 4 — Get your URL

1. Click **Settings → Networking → Generate Domain**
2. You'll get a URL like `https://examqa-production.up.railway.app`

---

## Step 5 — Share with colleagues

Send your colleagues:
- **URL:** `https://examqa-production.up.railway.app`
- **Username:** `examqa` (or whatever you set)
- **Password:** your AUTH_PASSWORD

When they visit the URL, their browser will show a login prompt. Only people with the password can access it.

---

## Updating the app

Whenever you make changes locally:
```bash
git add .
git commit -m "Update"
git push
```
Railway redeploys automatically within ~2 minutes.

---

## Cost

- **Free tier**: 500 compute-hours/month — enough for a small team with normal usage
- **Hobby plan** ($5/month): Unlimited hours, never sleeps — recommended if you use it daily

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Build fails | Check Railway logs → usually a missing package |
| App crashes | Check `OPENAI_API_KEY` is set correctly |
| Can't log in | Double-check `AUTH_USER` and `AUTH_PASSWORD` variables |
| App is slow first load | Free tier "sleeps" after 10 min idle — upgrade to Hobby plan |
