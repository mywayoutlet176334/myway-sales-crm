"""Local summary timer. No networking or message sending. Run alongside Waitress."""
import logging
import time
from app import app

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            try:
                if app.assistant_summary(): logging.info('Malaysia 5 PM sample summary saved.')
            except Exception:
                logging.exception('Summary failed; will retry. Check disk and database access.')
            time.sleep(30)
    except KeyboardInterrupt:
        pass
