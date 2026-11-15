# Deploying MARS-X to Vercel

The MARS-X frontend is built with Next.js and CesiumJS, designed to deploy seamlessly on Vercel.

---

## 1. Deploy via Vercel Dashboard (GitHub / GitLab / Bitbucket)

1. Push your repository to GitHub, GitLab, or Bitbucket.
2. Go to [vercel.com/new](https://vercel.com/new) and import the repository.
3. In the **Configure Project** screen:
   - **Project Name:** `mars-x` (or your preferred name)
   - **Framework Preset:** `Next.js` (auto-detected)
   - **Root Directory:** Click **Edit** and select **`frontend`** *(Critical: the Next.js app lives in the `frontend` subfolder)*
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL`: The public URL of your MARS-X FastAPI backend (e.g., `https://your-backend.railway.app` or `https://your-backend.onrender.com`).
     *(Note: If left unset, the frontend defaults to `http://localhost:8000` for local testing or uses browser Cache Storage for offline viewing).*
5. Click **Deploy**.

Vercel will run `npm install` and `npm run build` (which automatically triggers `prebuild` to package CesiumJS assets into `public/cesium/`).

---

## 2. Deploy via Vercel CLI

If deploying directly from your terminal:

```bash
cd frontend
npx vercel
```

When prompted:
- **Set up and deploy?** `yes`
- **Which scope?** (Select your Vercel team/account)
- **Link to existing project?** `no`
- **Project name?** `mars-x`
- **In which directory is your code located?** `./` (since you are inside `frontend`)

For production deployment:
```bash
npx vercel --prod
```

---

## 3. Backend Deployment (FastAPI)

The MARS-X backend requires Python and a persistent disk for DEM caches (`data_cache/` and `marsx.db`). Deploy it to a container/server platform such as Railway, Render, Fly.io, or VPS:

1. **Deploy Backend with Docker or Python:**
   - **Docker:** Use the provided [`backend/Dockerfile`](file:///backend/Dockerfile) or [`docker-compose.yml`](file:///docker-compose.yml).
   - **Direct Python:**
     ```bash
     cd backend
     pip install -r requirements.txt
     alembic upgrade head
     uvicorn app.main:app --host 0.0.0.0 --port 8000
     ```
2. **Configure CORS:**
   In your backend environment variables, update `MARSX_CORS_ORIGINS` to allow your Vercel domain:
   ```env
   MARSX_CORS_ORIGINS=https://your-project.vercel.app,http://localhost:3000
   ```
3. **Connect Frontend to Backend:**
   In your Vercel Project Settings > **Environment Variables**:
   ```env
   NEXT_PUBLIC_API_URL=https://your-backend-url.domain
   ```

