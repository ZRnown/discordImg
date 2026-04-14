import os
import sys
import json
import time
import shutil
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import db
from vector_engine import VectorEngine
from config import config


def _backup_file(path: str) -> None:
    if not os.path.exists(path):
        return
    ts = time.strftime('%Y%m%d-%H%M%S')
    backup_path = f"{path}.bak.{ts}"
    shutil.copy2(path, backup_path)
    logger.info(f"Backed up {path} -> {backup_path}")


def fix_index() -> None:
    logger.info("=" * 50)
    logger.info("🚀 Starting fast FAISS rebuild from DB features")
    logger.info("=" * 50)

    index_file = config.FAISS_INDEX_FILE
    id_map_file = config.FAISS_ID_MAP_FILE

    # Backup existing files first (safer than rm)
    _backup_file(index_file)
    _backup_file(id_map_file)

    # Remove old files (if any)
    for p in (index_file, id_map_file):
        try:
            if os.path.exists(p):
                os.remove(p)
                logger.info(f"Removed old index file: {p}")
        except Exception as e:
            logger.warning(f"Failed to remove {p}: {e}")

    # Create a fresh engine (will create new empty index)
    engine = VectorEngine()

    # Read all rows with features
    logger.info("Reading features from SQLite...")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, features FROM product_images WHERE features IS NOT NULL AND features != ''"
        )
        rows = cursor.fetchall()

    total_count = len(rows)
    logger.info(f"Found {total_count} feature rows")
    if total_count == 0:
        logger.warning("No feature data in DB. Cannot rebuild.")
        return

    ok = 0
    bad = 0
    start = time.time()

    for i, row in enumerate(rows, start=1):
        db_id = row['id']
        features_json = row['features']

        try:
            vec = np.array(json.loads(features_json), dtype='float32')
            if vec.ndim != 1 or vec.shape[0] != config.VECTOR_DIMENSION:
                bad += 1
                continue

            engine.add_vector(int(db_id), vec)
            ok += 1

            if i % 5000 == 0:
                logger.info(f"Progress: {i}/{total_count} (ok={ok}, bad={bad})")

        except Exception:
            bad += 1

    logger.info("Saving FAISS index...")
    engine.save()

    dur = time.time() - start
    logger.info("=" * 50)
    logger.info("✅ Rebuild complete")
    logger.info(f"Time: {dur:.2f}s")
    logger.info(f"Success: {ok}")
    logger.info(f"Failed: {bad}")
    logger.info(f"Index total: {engine.count()}")
    logger.info("=" * 50)


if __name__ == '__main__':
    fix_index()

