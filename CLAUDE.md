# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Discord Marketing System - a full-stack application for automated product marketing on Discord. Scrapes products from Chinese e-commerce platforms (Weidian), uses AI-powered image similarity matching (DINOv2 + YOLO) to identify products from Discord images, and auto-replies with product links.

## Architecture

Three-tier architecture:
- **Frontend** (Next.js 16, port 3000): React 19 + TypeScript + shadcn/ui + Tailwind CSS 4
- **Backend** (Flask, port 5001): REST API + SQLite + FAISS vector search
- **Discord Bot** (discord.py-self): Multi-account self-bot for image monitoring

### API Proxy Pattern
Frontend Next.js API routes (`/frontend/app/api/**/route.ts`) are thin proxies that forward requests to Flask backend. All routes use `NEXT_PUBLIC_BACKEND_URL` environment variable to locate the backend server.

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
| `config.py` | Centralized configuration with environment variable loading |

## Database Schema

SQLite database (`/backend/data/metadata.db`) with main tables:
- **products** - Product metadata (URL, title, description, shop_name, ruleEnabled)
- **users** - User accounts with role-based access (admin/user)
- **discord_accounts** - Discord bot account credentials and status
- **shops** - Shop information and settings
- **product_images** - Image metadata linked to products
- **search_history** - Image search query history
- **announcements** - System announcements
- **custom_replies** - Custom auto-reply rules
- **message_filters** - Message filtering rules

## Authentication

Session-based authentication with 30-day cookie lifetime. Admin users created via `python scripts/create_admin.py`. Session configuration in `config.py` (SECRET_KEY, SESSION_COOKIE_SECURE, SESSION_COOKIE_SAMESITE).

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

**Threading Configuration:**
- `SCRAPE_THREADS` - Product scraping concurrency (IO-bound, default: 10)
- `DOWNLOAD_THREADS` - Image download concurrency (IO-bound, default: 16)
- `FEATURE_EXTRACT_THREADS` - Legacy feature extraction threads (default: 4)
- `AI_INTRA_THREADS` - CPU cores per AI inference task (default: 2)
- `AI_MAX_WORKERS` - Concurrent AI inference tasks (default: 4)

**Discord Configuration:**
- `DISCORD_SIMILARITY_THRESHOLD` - Image match threshold 0.0-1.0 (default: 0.6)
- `GLOBAL_REPLY_MIN_DELAY` - Minimum reply delay in seconds (default: 3.0)
- `GLOBAL_REPLY_MAX_DELAY` - Maximum reply delay in seconds (default: 8.0)

**Other:**
- `DEVICE` - PyTorch device: 'cpu', 'cuda', or 'mps' (default: 'cpu')
- `NEXT_PUBLIC_BACKEND_URL` - Backend URL for frontend (default: http://localhost:5001)

## Performance Tuning

**Threading Strategy** (configured in `config.py`):
- IO-bound tasks (scraping, downloads) use high thread counts (10-20)
- CPU-bound tasks (AI inference) use worker pool pattern: `AI_MAX_WORKERS` × `AI_INTRA_THREADS` ≈ total CPU cores
- Example for 10-core CPU: 4 workers × 2 cores = 8 cores used, 2 reserved for system

**FAISS HNSW Parameters** (in `config.py`):
- `FAISS_HNSW_M=64` - Graph connectivity (higher = better recall, more memory)
- `FAISS_EF_CONSTRUCTION=80` - Index build quality (higher = better index, slower build)
- `FAISS_EF_SEARCH=64` - Search quality (higher = better recall, slower search)
