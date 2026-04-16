import hashlib
import json
from datetime import datetime, timedelta
import sqlite3
import os


class Block:
    def __init__(self, index, product_id, product_data, previous_hash, timestamp=None):
        self.index = index
        self.timestamp = timestamp if timestamp else datetime.now().isoformat()
        self.product_id = product_id
        self.product_data = product_data
        self.previous_hash = previous_hash
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "product_id": self.product_id,
            "product_data": self.product_data,
            "previous_hash": self.previous_hash
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "product_id": self.product_id,
            "product_data": self.product_data,
            "previous_hash": self.previous_hash,
            "hash": self.hash
        }


class Blockchain:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()
        if self.get_chain_length() == 0:
            self._create_genesis_block()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                idx INTEGER PRIMARY KEY,
                product_id TEXT,
                product_data TEXT,
                previous_hash TEXT,
                block_hash TEXT,
                timestamp TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def _create_genesis_block(self):
        genesis = Block(0, "GENESIS", {"info": "Verda Genesis Block — Chain Initialized"}, "0")
        self._save_block(genesis)

    def _save_block(self, block):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            INSERT INTO blockchain
            (idx, product_id, product_data, previous_hash, block_hash, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            block.index,
            block.product_id,
            json.dumps(block.product_data),
            block.previous_hash,
            block.hash,
            block.timestamp
        ))
        conn.commit()
        conn.close()

    def get_chain_length(self):
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0]
        conn.close()
        return count

    def get_last_block_hash(self):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT block_hash FROM blockchain ORDER BY idx DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row[0] if row else "0"

    def add_product(self, product_id, product_data):
        """Register a product on the blockchain. Returns (success, hash_or_message)."""
        if self.get_block(product_id):
            return False, "Product already registered on blockchain"

        index = self.get_chain_length()
        previous_hash = self.get_last_block_hash()
        block = Block(index, product_id, product_data, previous_hash)
        self._save_block(block)
        return True, block.hash

    def get_block(self, product_id):
        """Retrieve a block by product_id. Returns dict or None."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM blockchain WHERE product_id=?", (product_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "index": row[0],
            "product_id": row[1],
            "product_data": json.loads(row[2]),
            "previous_hash": row[3],
            "hash": row[4],
            "timestamp": row[5]
        }

    def verify_product(self, product_id):
        """
        Verify a product's blockchain integrity.
        Returns (is_valid: bool, detail: str)
        """
        block = self.get_block(product_id)
        if not block:
            return False, "Product not found on blockchain"

        # Recalculate hash to detect tampering
        test_block = Block(
            block["index"],
            block["product_id"],
            block["product_data"],
            block["previous_hash"],
            timestamp=block["timestamp"]
        )

        if test_block.hash == block["hash"]:
            return True, block["hash"]
        else:
            return False, "⚠️ Blockchain tamper detected — block hash mismatch!"

    def get_verification_details(self, product_id):
        """
        Full verification report for a product.
        Returns a dict with all verification fields for display.
        """
        block = self.get_block(product_id)
        if not block:
            return {
                "found": False,
                "valid": False,
                "block_index": None,
                "block_hash": None,
                "previous_hash": None,
                "registered_at": None,
                "chain_length": self.get_chain_length(),
                "chain_valid": self.is_chain_valid(),
                "message": "Product not registered on blockchain"
            }

        # Recalculate hash
        test_block = Block(
            block["index"],
            block["product_id"],
            block["product_data"],
            block["previous_hash"],
            timestamp=block["timestamp"]
        )
        hash_valid = (test_block.hash == block["hash"])

        return {
            "found": True,
            "valid": hash_valid,
            "block_index": block["index"],
            "block_hash": block["hash"],
            "previous_hash": block["previous_hash"],
            "registered_at": block["timestamp"],
            "product_data": block["product_data"],
            "chain_length": self.get_chain_length(),
            "chain_valid": self.is_chain_valid(),
            "message": "Hash verified ✔" if hash_valid else "Hash mismatch — data tampered!"
        }

    def get_scan_velocity(self, product_id, db_conn=None):
        """
        Compute scan velocity metrics for fake detection.
        Returns dict with total, last_hour, last_5min counts.
        """
        close_after = False
        if db_conn is None:
            db_conn = sqlite3.connect(self.db_path)
            close_after = True

        now = datetime.now()
        total = db_conn.execute(
            "SELECT COUNT(*) FROM scans WHERE product_id=?", (product_id,)
        ).fetchone()[0]
        recent = db_conn.execute(
            "SELECT COUNT(*) FROM scans WHERE product_id=? AND timestamp >= ?",
            (product_id, (now - timedelta(hours=1)).isoformat())
        ).fetchone()[0]
        rapid = db_conn.execute(
            "SELECT COUNT(*) FROM scans WHERE product_id=? AND timestamp >= ?",
            (product_id, (now - timedelta(minutes=5)).isoformat())
        ).fetchone()[0]

        if close_after:
            db_conn.close()

        # Threat score
        score = 0
        if total > 20:  score += 2
        if total > 50:  score += 3
        if recent > 5:  score += 2
        if rapid > 3:   score += 3

        return {
            "total": total,
            "last_hour": recent,
            "last_5min": rapid,
            "threat_score": score
        }

    def get_full_chain(self):
        """Returns all blocks in order."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT * FROM blockchain ORDER BY idx ASC"
        ).fetchall()
        conn.close()
        chain = []
        for row in rows:
            chain.append({
                "index": row[0],
                "product_id": row[1],
                "product_data": json.loads(row[2]),
                "previous_hash": row[3],
                "hash": row[4],
                "timestamp": row[5]
            })
        return chain

    def is_chain_valid(self):
        """Validate the entire chain's hash linkage."""
        chain = self.get_full_chain()
        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]
            # Check hash linkage
            if current["previous_hash"] != previous["hash"]:
                return False
            # Recalculate current block hash
            test = Block(
                current["index"],
                current["product_id"],
                current["product_data"],
                current["previous_hash"],
                timestamp=current["timestamp"]
            )
            if test.hash != current["hash"]:
                return False
        return True

    def get_stats(self):
        """Return summary stats about the blockchain."""
        conn = sqlite3.connect(self.db_path)
        total_blocks = conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0]
        product_blocks = total_blocks - 1  # Exclude genesis
        conn.close()
        return {
            "total_blocks": total_blocks,
            "product_blocks": max(product_blocks, 0),
            "chain_valid": self.is_chain_valid(),
            "last_hash": self.get_last_block_hash()
        }