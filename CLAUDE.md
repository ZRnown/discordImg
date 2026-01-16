# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Discord Marketing System - a full-stack application for automated product marketing on Discord. Scrapes products from Chinese e-commerce platforms (Weidian), uses AI-powered image similarity matching (DINOv2 + YOLO) to identify products from Discord images, and auto-replies with product links.

## Architecture

Three-tier architecture:
- **Frontend** (Next.js 16, port 3000): React 19 + TypeScript + shadcn/ui + Tailwind CSS 4
- **Backend** (Flask, port 5001): REST API + SQLite + FAISS vector search
- **Discord Bot** (discord.py-self): Multi-account self-bot for image monitoring

## Commands

### Frontend (`/frontend` directory)
```bash
pnpm install          # Install dependencies
pnpm dev              # Development server (port 3000)
pnpm build            # Production build
pnpm lint             # ESLint
```

### Backend (`/backend` directory)
```bash
pip install -r requirements.txt    # Install dependencies
python app.py                      # Start Flask API (port 5001)
python bot.py                      # Start Discord bot
python scripts/create_admin.py     # Create admin user
python scripts/clear_database.py   # Clear database
```

## Key Backend Modules

| Module | Purpose |
|--------|---------|
| `app.py` | Flask API server with all REST endpoints |
| `bot.py` | Discord bot with multi-account support and cooldown management |
| `database.py` | SQLite operations for products, users, accounts, shops |
| `feature_extractor.py` | AI pipeline: YOLO-World (object detection/cropping) + DINOv2 (feature extraction) |
| `vector_engine.py` | FAISS HNSW index for vector similarity search |
| `weidian_scraper.py` | Selenium-based Weidian product scraper |

## Key Frontend Components

Main views in `/frontend/components/`:
- `dashboard-view.tsx` - System statistics
- `accounts-view.tsx` - Discord account management
- `scraper-view.tsx` - Product scraping interface
- `image-search-view.tsx` - Image similarity search
- `rules-view.tsx` - Auto-reply rules configuration

UI components use shadcn/ui (57 components in `/frontend/components/ui/`).

## Data Flow

1. **Scraping**: Weidian URL → scrape product info/images → YOLO crop → DINOv2 features → FAISS index + SQLite metadata
2. **Discord Monitoring**: Image detected → extract features → FAISS similarity search → auto-reply with product link if match above threshold

## Data Storage

- `/backend/data/metadata.db` - SQLite database
- `/backend/data/faiss_index.bin` - FAISS vector index
- `/backend/data/scraped_images/` - Downloaded product images
- `/backend/data/logs/` - Application logs

## Environment Variables

Key variables (see `.env.example`):
- `SCRAPE_THREADS`, `DOWNLOAD_THREADS`, `FEATURE_EXTRACT_THREADS` - Concurrency settings
- `DISCORD_SIMILARITY_THRESHOLD` - Image match threshold (default 0.6)
- `GLOBAL_REPLY_MIN_DELAY`, `GLOBAL_REPLY_MAX_DELAY` - Reply delay range
- `NEXT_PUBLIC_BACKEND_URL` - Backend URL for frontend

## API Proxy

Frontend Next.js routes in `/frontend/app/api/` proxy requests to the Flask backend. Backend URL configured in `/frontend/next.config.mjs`.
